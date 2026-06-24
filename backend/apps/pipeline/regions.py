"""判定候选人南北：先看户籍省份字典，缺失则按学校所在地。"""
from apps.core import models as m


def candidate_region(cand) -> str:
    prov = (cand.household_province or "").strip()
    if prov:
        for pr in m.ProvinceRegion.objects.all():
            if pr.province and pr.province in prov:
                return pr.region
    for sname in (cand.highest_degree_school, cand.first_degree_school):
        if sname:
            s = m.School.objects.filter(name=sname).exclude(region="").first()
            if s:
                return s.region
    return ""
