"""初始化本地开发基础配置、RBAC 和测试账号。"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.accounts.permissions import ensure_rbac_defaults
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
    help = "初始化基础配置、RBAC 角色权限和本地测试账号"

    def handle(self, *args, **options):
        ensure_rbac_defaults()
        for p in NORTH:
            m.ProvinceRegion.objects.update_or_create(province=p, defaults={"region": "北"})
        for p in SOUTH:
            m.ProvinceRegion.objects.update_or_create(province=p, defaults={"region": "南"})
        defaults = {
            "ai_dispatch_threshold": 0.75,
            "ai_review_threshold": 0.5,
            "ai_timeout_seconds": 60,
            "ai_concurrency": 2,
            "ai_retry_count": 1,
            "ai_retry_backoff_seconds": 10,
            "welink_enabled": False,
            "w3_auth_enabled": False,
        }
        for key, value in defaults.items():
            m.Config.objects.update_or_create(key=key, defaults={"value": value})

        tech_l2, _ = m.Department.objects.update_or_create(
            name="技术二部", parent=None, defaults={"level": 2}
        )
        product_l2, _ = m.Department.objects.update_or_create(
            name="产品二部", parent=None, defaults={"level": 2}
        )
        tech_l3, _ = m.Department.objects.update_or_create(
            name="技术平台组", parent=tech_l2, defaults={"level": 3}
        )
        algo_l3, _ = m.Department.objects.update_or_create(
            name="算法应用组", parent=tech_l2, defaults={"level": 3}
        )
        product_l3, _ = m.Department.objects.update_or_create(
            name="产品运营组", parent=product_l2, defaults={"level": 3}
        )

        contacts = {
            "L2001": ("技术二级接口人A", tech_l2, m.Contact.LEVEL_SECONDARY),
            "L2002": ("产品二级接口人B", product_l2, m.Contact.LEVEL_SECONDARY),
            "T3001": ("技术三级接口人A", tech_l3, m.Contact.LEVEL_TERTIARY),
            "T3002": ("算法三级接口人B", algo_l3, m.Contact.LEVEL_TERTIARY),
            "T3003": ("产品三级接口人C", product_l3, m.Contact.LEVEL_TERTIARY),
        }
        contact_objects = {}
        for employee_no, (name, department, level) in contacts.items():
            contact, _ = m.Contact.objects.update_or_create(
                employee_no=employee_no,
                defaults={
                    "name": name,
                    "department": department,
                    "contact_level": level,
                    "is_active": True,
                },
            )
            contact_objects[employee_no] = contact

        users = [
            ("admin", "管理员", User.ROLE_ADMIN, None),
            ("hr", "HR", User.ROLE_HR, None),
            ("sec_tech", "二级接口人", User.ROLE_SECONDARY_CONTACT, contact_objects["L2001"]),
            ("sec_product", "二级接口人", User.ROLE_SECONDARY_CONTACT, contact_objects["L2002"]),
            ("ter_tech", "三级接口人", User.ROLE_TERTIARY_CONTACT, contact_objects["T3001"]),
            ("ter_algo", "三级接口人", User.ROLE_TERTIARY_CONTACT, contact_objects["T3002"]),
            ("ter_product", "三级接口人", User.ROLE_TERTIARY_CONTACT, contact_objects["T3003"]),
        ]
        for username, group_name, role, contact in users:
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    "role": role,
                    "contact": contact,
                    "is_active": True,
                    "is_staff": group_name == "管理员",
                },
            )
            if created or not user.has_usable_password():
                user.set_password("pass1234")
                user.save(update_fields=["password"])
            user.groups.set([Group.objects.get(name=group_name)])

        self.stdout.write(
            self.style.SUCCESS(
                "基础数据已初始化（配置 + RBAC + 多接口人测试账号，默认密码 pass1234）"
            )
        )
