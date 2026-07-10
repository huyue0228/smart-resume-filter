"""Step3 院校分类：第一/最高学历对照院校清单打院校标签。"""
from apps.core import models as m


NON_TARGET_TAG_NAME = "非目标院校"


def _normalized(value):
    return "".join((value or "").lower().split())


def _default_school_tag():
    default_tag = m.SchoolTag.objects.filter(is_default=True, is_active=True).first()
    if default_tag:
        return default_tag
    non_target = _normalized(NON_TARGET_TAG_NAME)
    return next(
        (
            tag
            for tag in m.SchoolTag.objects.filter(is_active=True).order_by("id")
            if _normalized(tag.name) == non_target
            or _normalized(tag.code) == non_target
        ),
        None,
    )


def _school_tag(school, default_tag):
    if school and school.school_tag:
        return school.school_tag
    return default_tag


def _tag_name(tag, fallback="非目标院校"):
    return tag.name if tag else fallback


def _school_platform_name(tag, school):
    if tag:
        return _tag_name(tag)
    if school and school.platform:
        return school.platform
    return "非目标院校"


def classify_candidates(candidates, *, overwrite=True):
    """按院校清单给指定候选人集合补院校标签。

    简历库“处理简历”只重跑 Step2，但 Step2 的院校准入依赖 Step3 产出的
    `first_degree_tag` / `highest_degree_tag`。这里允许 Step2 在锁定本次
    处理范围后只补这批候选人的标签，避免未预分类候选人被误判为非目标院校。
    Step2 调用时使用 `overwrite=False`，只补缺失标签，不覆盖已有准入结果；
    完整重分类仍由 Step3 显式执行。
    """
    count = 0
    school_map = {s.name: s for s in m.School.objects.select_related("school_tag")}
    default_tag = _default_school_tag()
    for cand in candidates:
        first_school = (
            school_map.get(cand.first_degree_school) if cand.first_degree_school else None
        )
        highest_school = (
            school_map.get(cand.highest_degree_school) if cand.highest_degree_school else None
        )
        first_tag = _school_tag(first_school, default_tag)
        highest_tag = _school_tag(highest_school, default_tag)
        should_update_first = overwrite or not cand.first_degree_tag_id
        should_update_highest = overwrite or not cand.highest_degree_tag_id
        # Step2 的补分类只补空字段。已有标签/平台可能来自 HR 手工修正或
        # 完整 Step3 分类结果，不能因为单次处理简历而被院校清单兜底覆盖。
        should_update_first_platform = overwrite or not cand.first_degree_platform
        should_update_highest_platform = overwrite or not cand.highest_degree_platform
        if should_update_first:
            cand.first_degree_tag = first_tag
        if should_update_highest:
            cand.highest_degree_tag = highest_tag
        if should_update_first_platform:
            cand.first_degree_platform = _school_platform_name(
                cand.first_degree_tag, first_school
            )
        if should_update_highest_platform:
            cand.highest_degree_platform = _school_platform_name(
                cand.highest_degree_tag, highest_school
            )
        update_fields = []
        if should_update_first:
            update_fields.append("first_degree_tag")
        if should_update_highest:
            update_fields.append("highest_degree_tag")
        if should_update_first_platform:
            update_fields.append("first_degree_platform")
        if should_update_highest_platform:
            update_fields.append("highest_degree_platform")
        if update_fields:
            cand.save(update_fields=update_fields)
        count += 1
    return count


def run(scope=None):
    count = classify_candidates(m.Candidate.objects.all())
    return f"已为 {count} 名候选人完成院校分类打标"
