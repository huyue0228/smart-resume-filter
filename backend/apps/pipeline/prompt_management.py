"""共享 Prompt 草稿、真实测试、发布和历史恢复服务。"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core import models as m
from apps.pipeline import ai_config
from apps.pipeline.ai import prompt_harness, school_province
from apps.pipeline.ai import service as ai_service


class PromptConflictError(Exception):
    """共享草稿已被其他管理员更新。"""


class PromptStateError(ValueError):
    """测试、发布或恢复的当前状态不满足要求。"""


class PromptTestError(Exception):
    """真实模型测试失败，错误内容已经脱敏。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _actor(user):
    if user and getattr(user, "is_authenticated", False):
        return user, user.username
    return None, ""


def _clear_test_fields(record):
    record.tested_by = None
    record.tested_by_username_snapshot = ""
    record.tested_at = None
    record.test_content_hash = ""
    record.test_model_name = ""
    record.test_connection_fingerprint = ""
    record.test_summary = {}


def clear_shared_draft_test():
    """连接保存/测试失效时立即使共享草稿测试失效。"""
    m.AIPromptVersion.objects.filter(
        status=m.AIPromptVersion.STATUS_DRAFT
    ).update(
        tested_by=None,
        tested_by_username_snapshot="",
        tested_at=None,
        test_content_hash="",
        test_model_name="",
        test_connection_fingerprint="",
        test_summary={},
    )


def _draft_test_valid(record):
    if (
        record.status != m.AIPromptVersion.STATUS_DRAFT
        or not record.tested_at
        or record.test_content_hash != record.content_hash
        or not record.test_connection_fingerprint
        or not ai_config.is_ai_connection_tested()
    ):
        return False
    try:
        return (
            record.test_connection_fingerprint
            == ai_config.current_ai_connection_fingerprint()
        )
    except (RuntimeError, ValueError):
        return False


def serialize_prompt(record, *, include_modules=True):
    payload = {
        "version": record.version,
        "status": record.status,
        "release_sequence": record.release_sequence,
        "content_hash": record.content_hash,
        "lock_version": record.lock_version,
        "created_by_username": record.created_by_username_snapshot,
        "updated_by_username": record.updated_by_username_snapshot,
        "tested_by_username": record.tested_by_username_snapshot,
        "tested_at": record.tested_at,
        "test_model_name": record.test_model_name,
        "test_summary": deepcopy(record.test_summary or {}),
        "test_valid": _draft_test_valid(record)
        if record.status == m.AIPromptVersion.STATUS_DRAFT
        else bool(record.tested_at and record.test_content_hash == record.content_hash),
        "published_by_username": record.published_by_username_snapshot,
        "published_at": record.published_at,
        "restored_from_version": (
            record.restored_from.version if record.restored_from_id else ""
        ),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if include_modules:
        payload["modules"] = deepcopy(record.modules)
    return payload


def prompt_management_payload():
    active = m.AIPromptVersion.objects.select_related("restored_from").get(
        status=m.AIPromptVersion.STATUS_ACTIVE
    )
    draft = m.AIPromptVersion.objects.select_related("restored_from").get(
        status=m.AIPromptVersion.STATUS_DRAFT
    )
    return {
        "module_definitions": prompt_harness.module_definitions(),
        "limits": {
            "module_max_chars": prompt_harness.MODULE_MAX_CHARS,
            "total_max_chars": prompt_harness.TOTAL_MAX_CHARS,
        },
        "default_modules": prompt_harness.default_modules(),
        "assembly_preview": prompt_harness.assembly_preview(),
        "active": serialize_prompt(active),
        "draft": serialize_prompt(draft),
    }


@transaction.atomic
def save_draft(*, modules, lock_version, user):
    normalized = prompt_harness.normalize_modules(modules)
    if isinstance(lock_version, bool) or not isinstance(lock_version, int):
        raise prompt_harness.PromptValidationError("lock_version 必须是整数")
    draft = m.AIPromptVersion.objects.select_for_update().get(
        status=m.AIPromptVersion.STATUS_DRAFT
    )
    if draft.lock_version != lock_version:
        raise PromptConflictError("共享草稿已被其他管理员更新，请刷新后重试")
    actor, username = _actor(user)
    draft.modules = normalized
    draft.content_hash = prompt_harness.modules_content_hash(normalized)
    draft.lock_version += 1
    draft.updated_by = actor
    draft.updated_by_username_snapshot = username
    draft.restored_from = None
    _clear_test_fields(draft)
    draft.save()
    return draft


@transaction.atomic
def reset_draft(*, source, lock_version, user):
    if source not in {"active", "default"}:
        raise prompt_harness.PromptValidationError(
            "source 必须是 active 或 default"
        )
    draft = m.AIPromptVersion.objects.select_for_update().get(
        status=m.AIPromptVersion.STATUS_DRAFT
    )
    if isinstance(lock_version, bool) or not isinstance(lock_version, int):
        raise prompt_harness.PromptValidationError("lock_version 必须是整数")
    if draft.lock_version != lock_version:
        raise PromptConflictError("共享草稿已被其他管理员更新，请刷新后重试")
    active = None
    if source == "active":
        active = m.AIPromptVersion.objects.get(status=m.AIPromptVersion.STATUS_ACTIVE)
        modules = active.modules
    else:
        modules = prompt_harness.default_modules()
    actor, username = _actor(user)
    normalized = prompt_harness.normalize_modules(modules)
    draft.modules = normalized
    draft.content_hash = prompt_harness.modules_content_hash(normalized)
    draft.lock_version += 1
    draft.updated_by = actor
    draft.updated_by_username_snapshot = username
    draft.restored_from = active
    _clear_test_fields(draft)
    draft.save()
    return draft


def _normalized_evidence_in_text(evidence, text):
    normalized_evidence = "".join(str(evidence or "").casefold().split())
    normalized_text = "".join(str(text or "").casefold().split())
    return len(normalized_evidence) >= 4 and normalized_evidence in normalized_text


def _run_screening_prompt_test(modules):
    resume_text = (
        "项目：企业知识库 RAG 智能体。使用 Python、向量数据库和检索增强生成实现多轮问答，"
        "负责离线评测集构建与召回率评估。\n"
        "实习：在平台研发团队开发 Django 接口，完成服务监控、性能优化和单元测试。\n"
        "技能：Python、Django、RAG、向量检索、大模型评测。"
    )
    resume = SimpleNamespace(
        position_name="AI 平台研发工程师",
        candidate=SimpleNamespace(highest_major="计算机科学与技术"),
    )
    job_context = {
        "entity": "示例招聘主体",
        "public_name": "AI 平台研发工程师",
        "position_name": "AI 平台研发工程师",
        "category": "技术类",
        "job_family": "软件开发",
        "location": "上海",
        "required_majors": ["计算机科学与技术"],
        "responsibilities": (
            "负责 RAG 应用、智能体工程、模型评测平台和 Python 服务开发。"
        ),
    }
    output = ai_service._call_model(
        resume,
        resume_text,
        job_context,
        prompt_modules=modules,
    )
    evidence = list(output.decision.evidence or [])
    if not evidence or any(
        not _normalized_evidence_in_text(item, resume_text) for item in evidence
    ):
        raise PromptTestError(
            "prompt_evidence_invalid",
            "简历筛选测试未返回可在合成简历中定位的证据",
        )
    specialist_evidence = list(output.decision.ai_specialist_evidence or [])
    if any(
        not _normalized_evidence_in_text(item, resume_text)
        for item in specialist_evidence
    ):
        raise PromptTestError(
            "prompt_specialist_evidence_invalid",
            "AI 专项测试证据无法在合成简历中定位",
        )
    return {
        "ok": True,
        "recommendation": output.decision.recommendation,
        "evidence_count": len(evidence),
        "specialist_evidence_count": len(specialist_evidence),
    }


def _run_school_prompt_test(modules):
    school_names = ["北京大学", "中国人民大学苏州校区", "不确定名称研究院"]
    output = school_province.call_school_province_model(
        school_names,
        prompt_modules=modules,
    )
    requested = set(school_names)
    for item in output.schools:
        if item.name not in requested:
            raise PromptTestError(
                "prompt_school_name_out_of_scope",
                "院校省份测试返回了输入范围外的院校名称",
            )
        if item.province and item.province not in prompt_harness.SUPPORTED_PROVINCES:
            raise PromptTestError(
                "prompt_school_province_invalid",
                "院校省份测试返回了白名单外的省份",
            )
    returned_names = {item.name for item in output.schools}
    return {
        "ok": True,
        "requested_count": len(school_names),
        "returned_count": len(returned_names),
        "unresolved_count": sum(
            1 for item in output.schools if not item.province
        ),
    }


def _clear_failed_test_if_unchanged(draft_id, content_hash):
    with transaction.atomic():
        draft = m.AIPromptVersion.objects.select_for_update().get(pk=draft_id)
        if draft.content_hash == content_hash:
            _clear_test_fields(draft)
            draft.save()


def test_saved_draft(*, user):
    if not ai_config.is_ai_connection_tested():
        raise PromptStateError("当前模型连接尚未测试成功，不能测试 Prompt 草稿")
    draft = m.AIPromptVersion.objects.get(status=m.AIPromptVersion.STATUS_DRAFT)
    content_hash = draft.content_hash
    modules = prompt_harness.normalize_modules(draft.modules)
    fingerprint = ai_config.current_ai_connection_fingerprint()
    model_config = ai_config.get_ai_model_config()

    try:
        screening_summary = _run_screening_prompt_test(modules)
        school_summary = _run_school_prompt_test(modules)
    except PromptTestError:
        _clear_failed_test_if_unchanged(draft.id, content_hash)
        raise
    except ai_service.AIServiceError as exc:
        _clear_failed_test_if_unchanged(draft.id, content_hash)
        raise PromptTestError(exc.code, exc.message) from exc
    except (RuntimeError, ValueError) as exc:
        _clear_failed_test_if_unchanged(draft.id, content_hash)
        raise PromptTestError("prompt_test_failed", str(exc)) from exc

    with transaction.atomic():
        draft = m.AIPromptVersion.objects.select_for_update().get(pk=draft.id)
        if draft.content_hash != content_hash:
            raise PromptConflictError(
                "真实模型测试期间共享草稿已被修改，请重新测试"
            )
        if (
            not ai_config.is_ai_connection_tested()
            or ai_config.current_ai_connection_fingerprint() != fingerprint
        ):
            raise PromptConflictError(
                "真实模型测试期间模型连接已变化，请重新测试"
            )
        actor, username = _actor(user)
        draft.tested_by = actor
        draft.tested_by_username_snapshot = username
        draft.tested_at = timezone.now()
        draft.test_content_hash = content_hash
        draft.test_model_name = model_config.model_name
        draft.test_connection_fingerprint = fingerprint
        draft.test_summary = {
            "screening": screening_summary,
            "school_province": school_summary,
        }
        draft.save()
    return draft


@transaction.atomic
def publish_draft(*, lock_version, user):
    if isinstance(lock_version, bool) or not isinstance(lock_version, int):
        raise prompt_harness.PromptValidationError("lock_version 必须是整数")
    active = m.AIPromptVersion.objects.select_for_update().get(
        status=m.AIPromptVersion.STATUS_ACTIVE
    )
    draft = m.AIPromptVersion.objects.select_for_update().get(
        status=m.AIPromptVersion.STATUS_DRAFT
    )
    if draft.lock_version != lock_version:
        raise PromptConflictError("共享草稿已被其他管理员更新，请刷新后重试")
    if not _draft_test_valid(draft):
        raise PromptStateError(
            "草稿内容或模型连接已变化，必须重新执行真实模型测试后才能发布"
        )

    actor, username = _actor(user)
    next_sequence = (
        m.AIPromptVersion.objects.aggregate(value=Max("release_sequence"))["value"]
        or 0
    ) + 1
    published_version = (
        f"prompt-v{next_sequence:06d}-{draft.content_hash[:8]}"
    )
    now = timezone.now()

    active.status = m.AIPromptVersion.STATUS_ARCHIVED
    active.updated_by = actor
    active.updated_by_username_snapshot = username
    active.save()

    draft.status = m.AIPromptVersion.STATUS_ACTIVE
    draft.version = published_version
    draft.release_sequence = next_sequence
    draft.lock_version += 1
    draft.updated_by = actor
    draft.updated_by_username_snapshot = username
    draft.published_by = actor
    draft.published_by_username_snapshot = username
    draft.published_at = now
    draft.save()

    new_draft = m.AIPromptVersion.objects.create(
        version=f"draft-{published_version}",
        status=m.AIPromptVersion.STATUS_DRAFT,
        modules=deepcopy(draft.modules),
        content_hash=draft.content_hash,
        created_by=actor,
        created_by_username_snapshot=username,
        updated_by=actor,
        updated_by_username_snapshot=username,
        restored_from=draft,
    )
    return draft, new_draft


@transaction.atomic
def restore_version_to_draft(*, version, lock_version, user):
    if isinstance(lock_version, bool) or not isinstance(lock_version, int):
        raise prompt_harness.PromptValidationError("lock_version 必须是整数")
    source = m.AIPromptVersion.objects.get(
        version=version,
        status__in=[
            m.AIPromptVersion.STATUS_ACTIVE,
            m.AIPromptVersion.STATUS_ARCHIVED,
        ],
    )
    draft = m.AIPromptVersion.objects.select_for_update().get(
        status=m.AIPromptVersion.STATUS_DRAFT
    )
    if draft.lock_version != lock_version:
        raise PromptConflictError("共享草稿已被其他管理员更新，请刷新后重试")
    actor, username = _actor(user)
    normalized = prompt_harness.normalize_modules(source.modules)
    draft.modules = normalized
    draft.content_hash = prompt_harness.modules_content_hash(normalized)
    draft.lock_version += 1
    draft.updated_by = actor
    draft.updated_by_username_snapshot = username
    draft.restored_from = source
    _clear_test_fields(draft)
    draft.save()
    return draft
