from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """系统用户。角色区分 HR / 二级接口人 / 三级接口人 / 管理员。"""

    ROLE_HR = "hr"
    ROLE_SECONDARY_CONTACT = "secondary_contact"
    ROLE_TERTIARY_CONTACT = "tertiary_contact"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_HR, "HR"),
        (ROLE_SECONDARY_CONTACT, "二级接口人"),
        (ROLE_TERTIARY_CONTACT, "三级接口人"),
        (ROLE_ADMIN, "管理员"),
    ]

    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_HR)
    contact = models.ForeignKey(
        "core.Contact", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="users",
    )
