"""岗位需求汇总兼容工具；需求维护属于基础数据准备，不再占用流水线步骤。"""
from django.db.models import Sum

from apps.core import models as m


def run(scope=None):
    total = m.Job.objects.count()
    hc = m.Job.objects.aggregate(s=Sum("headcount"))["s"] or 0
    return f"结构化需求表：{total} 个岗位，合计需求数量(HC) {hc}"
