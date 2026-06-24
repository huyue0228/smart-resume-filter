"""Step5 简历分配：筛选(待处理+第一志愿+目标院校) → 按部门分配 → 下发接口人。"""
from collections import defaultdict

from django.db.models import Max

from apps.core import models as m


def get_multiplier(default=5):
    cfg = m.Config.objects.filter(key="allocation_multiplier").first()
    if cfg and isinstance(cfg.value, (int, float)):
        return int(cfg.value)
    if cfg and isinstance(cfg.value, dict) and "value" in cfg.value:
        try:
            return int(cfg.value["value"])
        except (TypeError, ValueError):
            return default
    return default


def run(scope=None, mode="rule"):
    multiplier = get_multiplier()
    m.Allocation.objects.all().delete()

    qs = (
        m.Resume.objects.filter(volunteer_rank=1, candidate__is_target_school=True)
        .filter(status__icontains="待")
        .select_related("job", "candidate")
    )

    by_dept = defaultdict(list)
    for r in qs:
        dept = r.job.department if r.job else None
        by_dept[dept].append(r)

    created = 0
    for dept, resumes in by_dept.items():
        if dept:
            max_hc = (
                m.Job.objects.filter(department=dept).aggregate(mx=Max("headcount"))["mx"]
                or 0
            )
            cap = max_hc * multiplier if max_hc else len(resumes)
            contact = m.Contact.objects.filter(department=dept).first()
        else:
            cap = len(resumes)
            contact = None
        for r in resumes[:cap]:
            m.Allocation.objects.create(
                resume=r,
                department=dept,
                contact=contact,
                reason="志愿优先/专业匹配",
                match_mode=mode,
                status=m.Allocation.STATUS_PENDING,
            )
            created += 1
    return f"已生成 {created} 条分配（最大HC×{multiplier}）"
