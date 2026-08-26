"""单级撤销快照：上传简历前保存候选、投递和分配工作流。"""
import json

from django.core import serializers
from django.db import transaction

from apps.core import models as m

_SNAPSHOT_MODELS = [
    m.Candidate,
    m.Resume,
    m.ResumeProfile,
    m.CandidateWorkflow,
    m.AgentDispatchDecision,
    m.AssignmentAttempt,
    m.AssignmentHandlingEvent,
]


def take_snapshot(label=""):
    objs = []
    for Model in _SNAPSHOT_MODELS:
        objs.extend(Model.objects.all())
    payload = serializers.serialize("json", objs)
    m.ImportSnapshot.objects.all().delete()
    return m.ImportSnapshot.objects.create(label=label, payload=payload)


def latest_snapshot():
    return m.ImportSnapshot.objects.order_by("-created_at").first()


def _deserialize_payload(payload):
    raw = json.loads(payload or "[]")
    workflows = []
    decisions = []
    attempts = []
    handling_events = []
    others = []
    for item in raw:
        if item.get("model") == "core.candidateworkflow":
            workflows.append(item)
        elif item.get("model") == "core.agentdispatchdecision":
            decisions.append(item)
        elif item.get("model") == "core.assignmentattempt":
            attempts.append(item)
        elif item.get("model") == "core.assignmenthandlingevent":
            handling_events.append(item)
        else:
            others.append(item)
    return others, workflows, decisions, attempts, handling_events


@transaction.atomic
def restore_latest():
    snap = latest_snapshot()
    if not snap:
        return False

    others, workflows, decisions, attempts, handling_events = _deserialize_payload(
        snap.payload
    )

    m.AssignmentHandlingEvent.objects.all().delete()
    m.AssignmentAttempt.objects.all().delete()
    m.AgentDispatchDecision.objects.all().delete()
    m.ResumeProfile.objects.all().delete()
    m.CandidateWorkflow.objects.all().delete()
    m.Resume.objects.all().delete()
    m.Candidate.objects.all().delete()

    for obj in serializers.deserialize("json", json.dumps(others)):
        obj.save()

    passed_attempts = {}
    for item in workflows:
        fields = item.get("fields", {})
        passed_attempts[item["pk"]] = fields.get("passed_attempt")
        fields["passed_attempt"] = None

    for obj in serializers.deserialize("json", json.dumps(workflows)):
        obj.save()

    for obj in serializers.deserialize("json", json.dumps(decisions)):
        obj.save()

    for obj in serializers.deserialize("json", json.dumps(attempts)):
        obj.save()

    for obj in serializers.deserialize("json", json.dumps(handling_events)):
        obj.save()

    for workflow_pk, attempt_pk in passed_attempts.items():
        if attempt_pk:
            m.CandidateWorkflow.objects.filter(pk=workflow_pk).update(
                passed_attempt_id=attempt_pk
            )

    snap.delete()
    return True
