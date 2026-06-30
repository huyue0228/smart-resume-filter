"""初始化省份南北字典与基础配置。"""
from django.core.management.base import BaseCommand

from apps.core import models as m

NORTH = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "山东", "河南", "陕西", "甘肃", "宁夏", "新疆", "青海",
]
SOUTH = [
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "湖北", "湖南",
    "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏",
]


class Command(BaseCommand):
    help = "初始化省份南北字典与基础配置"

    def handle(self, *args, **options):
        for p in NORTH:
            m.ProvinceRegion.objects.update_or_create(province=p, defaults={"region": "北"})
        for p in SOUTH:
            m.ProvinceRegion.objects.update_or_create(province=p, defaults={"region": "南"})
        m.Config.objects.update_or_create(
            key="ai_timeout_seconds", defaults={"value": 60}
        )
        m.Config.objects.update_or_create(
            key="welink_enabled", defaults={"value": False}
        )
        if not m.SchoolTagRule.objects.exists():
            m.SchoolTagRule.objects.create(
                name="Demo 默认目标院校",
                first_degree_tags=["平台A", "平台B", "平台C"],
                highest_degree_tags=["平台A", "平台B", "平台C"],
                is_active=True,
                priority=0,
            )
        self.stdout.write(
            self.style.SUCCESS("基础数据已初始化（省份字典 + 基础配置 + Demo 院校规则）")
        )
