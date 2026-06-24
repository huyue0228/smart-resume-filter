"""Step1 查重与志愿排序：按 Candidate 聚合投递，组内按南北规则 + 投递时间排序。"""
from datetime import date

from apps.core import models as m

from ..regions import candidate_region


def run(scope=None):
    count = 0
    for cand in m.Candidate.objects.prefetch_related("resumes").all():
        resumes = list(cand.resumes.all())
        if not resumes:
            continue
        region = candidate_region(cand)
        preferred = "GW" if region == "北" else ("YLS" if region == "南" else None)

        def sort_key(r):
            pref = 0 if (preferred and r.entity == preferred) else 1
            return (pref, r.apply_date or date.max)

        resumes.sort(key=sort_key)
        for i, r in enumerate(resumes, start=1):
            r.volunteer_rank = i
            r.assigned_entity = r.entity
            r.save(update_fields=["volunteer_rank", "assigned_entity"])
            count += 1
    return f"已为 {count} 条投递完成查重与志愿排序"
