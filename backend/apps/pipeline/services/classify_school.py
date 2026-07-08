"""Step3 院校分类：第一/最高学历对照院校清单打院校标签。"""
from apps.core import models as m


def _school_tag(school, default_tag):
    if school and school.school_tag:
        return school.school_tag
    return default_tag


def _tag_name(tag, fallback="非目标院校"):
    return tag.name if tag else fallback


def run(scope=None):
    count = 0
    school_map = {s.name: s for s in m.School.objects.select_related("school_tag")}
    default_tag = m.SchoolTag.objects.filter(is_default=True, is_active=True).first()
    for cand in m.Candidate.objects.all():
        first_school = (
            school_map.get(cand.first_degree_school) if cand.first_degree_school else None
        )
        highest_school = (
            school_map.get(cand.highest_degree_school) if cand.highest_degree_school else None
        )
        first_tag = _school_tag(first_school, default_tag)
        highest_tag = _school_tag(highest_school, default_tag)
        cand.first_degree_tag = first_tag
        cand.highest_degree_tag = highest_tag
        cand.first_degree_platform = (
            _tag_name(first_tag)
            if first_tag
            else (first_school.platform if first_school and first_school.platform else "非目标院校")
        )
        cand.highest_degree_platform = (
            _tag_name(highest_tag)
            if highest_tag
            else (
                highest_school.platform
                if highest_school and highest_school.platform
                else "非目标院校"
            )
        )
        cand.save(
            update_fields=[
                "first_degree_tag",
                "highest_degree_tag",
                "first_degree_platform",
                "highest_degree_platform",
            ]
        )
        count += 1
    return f"已为 {count} 名候选人完成院校分类打标"
