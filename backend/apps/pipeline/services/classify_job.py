"""岗位分类兼容工具；正式 Rule-first 流程由 Step3 按当前志愿完成匹配。"""
from apps.core import models as m

from ..strategies import get_rule_strategy


def run(scope=None):
    strategy = get_rule_strategy()
    jobs = list(m.Job.objects.filter(is_active=True))
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
    return f"已为 {count} 条投递完成岗位分类"
