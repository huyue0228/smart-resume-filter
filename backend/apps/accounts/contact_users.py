from django.contrib.auth.models import Group
from django.db import transaction

from apps.accounts.models import User
from apps.core import models as m


CONTACT_GROUP_NAMES = ["二级接口人", "三级接口人"]


def _contact_user_role(contact):
    if contact.contact_level == m.Contact.LEVEL_TERTIARY:
        return User.ROLE_TERTIARY_CONTACT, "三级接口人"
    return User.ROLE_SECONDARY_CONTACT, "二级接口人"


@transaction.atomic
def sync_contact_user(contact):
    """按接口人工号同步登录账号，同时保留已有密码和非接口人角色。"""

    bound_user = User.objects.filter(contact=contact).order_by("id").first()
    username_user = User.objects.filter(username=contact.employee_no).first()

    if username_user and username_user.contact_id not in (None, contact.id):
        raise ValueError("该工号已绑定其他接口人")
    if bound_user and username_user and bound_user.id != username_user.id:
        raise ValueError("该工号已被其他账号使用")

    user = bound_user or username_user
    created = user is None
    if created:
        user = User(username=contact.employee_no)

    role, group_name = _contact_user_role(contact)
    user.username = contact.employee_no
    user.role = role
    user.contact = contact
    user.is_active = contact.is_active
    user.save()

    if created or not user.has_usable_password():
        user.set_password("pass1234")
        user.save(update_fields=["password"])

    contact_groups = Group.objects.filter(name__in=CONTACT_GROUP_NAMES)
    user.groups.remove(*contact_groups.exclude(name=group_name))
    target_group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(target_group)
    return user
