"""Step4 需求录入：岗位需求在导入时已结构化，此步做汇总核对。"""
from django.db.models import Sum

from apps.core import models as m


def run(scope=None):
    total = m.Job.objects.count()
    hc = m.Job.objects.aggregate(s=Sum("headcount"))["s"] or 0
    return f"结构化需求表：{total} 个岗位，合计需求数量(HC) {hc}"
