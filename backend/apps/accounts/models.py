from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """系统用户。角色区分 HR / 接口人 / 管理员，接口人可绑定到 Contact。"""

    ROLE_HR = "hr"
    ROLE_CONTACT = "contact"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_HR, "HR"),
        (ROLE_CONTACT, "接口人"),
        (ROLE_ADMIN, "管理员"),
    ]

    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_HR)
    contact = models.ForeignKey(
        "core.Contact", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="users",
    )
