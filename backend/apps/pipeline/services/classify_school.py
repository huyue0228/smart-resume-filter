"""Step3 院校分类：第一/最高学历对照院校清单打平台标签，非命中=非目标院校。"""
from apps.core import models as m


def run(scope=None):
    count = 0
    school_map = {s.name: s.platform for s in m.School.objects.all()}
    for cand in m.Candidate.objects.all():
        fp = school_map.get(cand.first_degree_school, "") if cand.first_degree_school else ""
        hp = school_map.get(cand.highest_degree_school, "") if cand.highest_degree_school else ""
        cand.first_degree_platform = fp or "非目标院校"
        cand.highest_degree_platform = hp or "非目标院校"
        cand.save(
            update_fields=[
                "first_degree_platform",
                "highest_degree_platform",
            ]
        )
        count += 1
    return f"已为 {count} 名候选人完成院校分类打标"
