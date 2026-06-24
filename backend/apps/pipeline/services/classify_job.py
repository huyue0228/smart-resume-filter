"""Step2 岗位分类：按岗位类别映射表打标签，规则/AI 双模式（统一策略接口）。"""
from apps.core import models as m

from ..strategies import get_strategy


def run(scope=None, mode="rule"):
    strategy = get_strategy(mode)
    jobs = list(m.Job.objects.all())
    count = 0
    for resume in m.Resume.objects.select_related("candidate").all():
        job, category, reason = strategy.classify(resume, jobs)
        resume.job = job
        resume.job_category = category
        resume.category_mode = mode
        resume.category_reason = reason
        resume.save(
            update_fields=["job", "job_category", "category_mode", "category_reason"]
        )
        count += 1
    return f"已为 {count} 条投递完成岗位分类（模式：{mode}）"
