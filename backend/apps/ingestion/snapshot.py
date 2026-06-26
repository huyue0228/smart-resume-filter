"""单级撤销快照：上传简历前保存 Candidate/Resume/Allocation，可一键还原。

仅保留最近一份。撤销后快照清除（再次可撤销需先有新上传）。
"""
from django.core import serializers
from django.db import transaction

from apps.core import models as m

# 序列化顺序需保证 FK 先于引用方（Candidate → Resume → Allocation）
_SNAPSHOT_MODELS = [m.Candidate, m.Resume, m.Allocation]


def take_snapshot(label=""):
    objs = []
    for Model in _SNAPSHOT_MODELS:
        objs.extend(Model.objects.all())
    payload = serializers.serialize("json", objs)
    m.ImportSnapshot.objects.all().delete()  # 单级：只留最新一份
    return m.ImportSnapshot.objects.create(label=label, payload=payload)


def latest_snapshot():
    return m.ImportSnapshot.objects.order_by("-created_at").first()


@transaction.atomic
def restore_latest():
    snap = latest_snapshot()
    if not snap:
        return False
    # 反向清空（先删引用方），再按快照顺序还原（Candidate 先建，满足 Resume FK）
    m.Allocation.objects.all().delete()
    m.Resume.objects.all().delete()
    m.Candidate.objects.all().delete()
    for obj in serializers.deserialize("json", snap.payload):
        obj.save()
    snap.delete()
    return True
