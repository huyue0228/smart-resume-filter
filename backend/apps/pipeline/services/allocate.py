"""岗位与分配前置检查、AI 深度筛选及强制分配领域服务。"""
import time
import uuid
from datetime import timedelta
from fractions import Fraction

from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.core import models as m
from apps.core import system_status
from apps.core.departments import secondary_department as _secondary_department
from apps.pipeline import ai_config
from apps.pipeline.ai import service as ai_service

from ..cancellation import raise_if_cancel_requested
from ..strategies import get_rule_strategy
from . import classify_school, school_admission
from .job_mapping import JobMappingError, resolve_job_pool


UNFEEDBACKED_STATUSES = [
    m.AssignmentAttempt.STATUS_PENDING_REVIEW,
    m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
    m.AssignmentAttempt.STATUS_DISPATCHED_L2,
    m.AssignmentAttempt.STATUS_ASSIGNED_L3,
]

RESULT_COMPLETED = m.ProcessingRunScopeItem.RESULT_COMPLETED
RESULT_NEEDS_ATTENTION = m.ProcessingRunScopeItem.RESULT_NEEDS_ATTENTION
RESULT_FAILED = m.ProcessingRunScopeItem.RESULT_FAILED
RESULT_CANCELLED = m.ProcessingRunScopeItem.RESULT_CANCELLED

AI_ATTENTION_REASON_CODES = {
    "pdf_missing": "resume_text_unavailable",
    "pdf_parse_failed": "resume_text_unavailable",
    "profile_incomplete": "resume_text_unavailable",
    "ai_not_configured": "ai_connection_error",
    "ai_connection_error": "ai_connection_error",
    "llm_connection_error": "ai_connection_error",
    "llm_error": "ai_connection_error",
    "ai_limiter_unavailable": "ai_connection_error",
    "ai_rate_limited": "ai_rate_limited",
    "invalid_ai_output": "ai_invalid_output",
    "ai_invalid_output": "ai_invalid_output",
    "reference_not_found": "ai_reference_invalidated",
    "guardrail_blocked": "ai_reference_invalidated",
    "ai_reference_invalidated": "ai_reference_invalidated",
    "job_responsibility_missing": "job_responsibility_missing",
    "task_execution_error": "ai_connection_error",
}


def _scope_result(item, *, status, result_type, reason_code="", message=""):
    item.status = status
    item.result_type = result_type
    item.reason_code = reason_code
    item.result_message = message
    item.error_code = reason_code if result_type != RESULT_COMPLETED else ""
    item.error_message = message if result_type != RESULT_COMPLETED else ""
    item.skip_reason = ""
    item.finished_at = timezone.now() if result_type else None
    item.save(
        update_fields=[
            "status",
            "result_type",
            "reason_code",
            "result_message",
            "error_code",
            "error_message",
            "skip_reason",
            "finished_at",
        ]
    )


def _ai_failure_result(error_code):
    if error_code == "llm_timeout":
        return "failed", RESULT_FAILED, "llm_timeout"
    return (
        "needs_attention",
        RESULT_NEEDS_ATTENTION,
        AI_ATTENTION_REASON_CODES.get(error_code, "ai_connection_error"),
    )


def sync_processing_run_results(processing_run, processing_stage=None):
    """按 ScopeItem 统一结果口径重算父任务，兼容 Rule 同步和 AI 并发阶段。"""
    if not processing_run:
        return
    items = processing_run.scope_items.all()
    completed = items.filter(result_type=RESULT_COMPLETED).count()
    attention = items.filter(result_type=RESULT_NEEDS_ATTENTION).count()
    failed = items.filter(result_type=RESULT_FAILED).count()
    cancelled = items.filter(result_type=RESULT_CANCELLED).count()
    skipped = items.filter(status="skipped_manual_change").count()
    processed = completed + attention + failed + cancelled + skipped
    processing_run.total_count = items.count()
    processing_run.processed_count = processed
    processing_run.success_count = completed
    processing_run.completed_count = completed
    processing_run.needs_attention_count = attention
    processing_run.failed_count = failed
    processing_run.cancelled_count = cancelled
    processing_run.skipped_count = skipped
    processing_run.last_heartbeat_at = timezone.now()
    processing_run.save(
        update_fields=[
            "total_count",
            "processed_count",
            "success_count",
            "completed_count",
            "needs_attention_count",
            "failed_count",
            "cancelled_count",
            "skipped_count",
            "last_heartbeat_at",
        ]
    )
    if processing_stage:
        processing_stage.total_count = processing_run.total_count
        processing_stage.processed_count = processing_run.total_count
        processing_stage.success_count = completed
        processing_stage.completed_count = completed
        processing_stage.needs_attention_count = attention
        processing_stage.failed_count = failed
        processing_stage.cancelled_count = cancelled
        processing_stage.skipped_count = skipped
        processing_stage.save(
            update_fields=[
                "total_count",
                "processed_count",
                "success_count",
                "completed_count",
                "needs_attention_count",
                "failed_count",
                "cancelled_count",
                "skipped_count",
            ]
        )


def _archive(workflow, reason, detail):
    workflow.status = m.CandidateWorkflow.STATUS_ARCHIVED
    workflow.archive_reason = reason
    workflow.archive_detail = detail
    workflow.block_reason = ""
    workflow.block_detail = ""
    workflow.completed_at = timezone.now()
    workflow.save(
        update_fields=[
            "status",
            "archive_reason",
            "archive_detail",
            "block_reason",
            "block_detail",
            "completed_at",
            "updated_at",
        ]
    )


def _clear_block(workflow):
    """清除当前志愿阻塞标记。

    阻塞原因只表示“当前志愿暂时无法继续自动分配”，一旦流程生成有效尝试、
    被人工处理、重新跑批、归档或通过，都必须清空，避免简历库展示过期原因。
    """
    workflow.block_reason = ""
    workflow.block_detail = ""


def _block_current_volunteer(workflow, reason, detail):
    """把流程停留在当前志愿，等待 HR 补齐前置数据后重新处理。"""
    workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
    workflow.archive_reason = ""
    workflow.archive_detail = ""
    workflow.block_reason = reason
    workflow.block_detail = detail
    workflow.completed_at = None
    workflow.save(
        update_fields=[
            "status",
            "archive_reason",
            "archive_detail",
            "block_reason",
            "block_detail",
            "completed_at",
            "updated_at",
        ]
    )


def _cancel_unfeedbacked_attempts(workflow, reason, source=None, sources=None):
    qs = workflow.attempts.filter(status__in=UNFEEDBACKED_STATUSES)
    if source:
        qs = qs.filter(source=source)
    if sources:
        qs = qs.filter(source__in=sources)
    attempts = list(qs.select_for_update().order_by("id"))
    now = timezone.now()
    for attempt in attempts:
        _release_attempt_capacity(attempt, released_at=now)
        attempt.status = m.AssignmentAttempt.STATUS_CANCELLED
        attempt.cancelled_at = now
        attempt.cancel_reason = reason
        attempt.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancel_reason",
                "capacity_released_at",
                "updated_at",
            ]
        )
    return len(attempts)


def _release_attempt_capacity(attempt, *, released_at=None):
    if (
        not attempt.capacity_reservation_id
        or attempt.capacity_released_at
        or attempt.status
        not in {
            m.AssignmentAttempt.STATUS_PENDING_REVIEW,
            m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
        }
    ):
        return False
    capacity = m.ProcessingRunJobCapacity.objects.select_for_update().get(
        pk=attempt.capacity_reservation_id
    )
    if capacity.used_count <= 0:
        raise ValueError("岗位 HC 容量占用记录异常，无法释放")
    capacity.used_count -= 1
    capacity.save(update_fields=["used_count"])
    attempt.capacity_released_at = released_at or timezone.now()
    return True


def _candidate_queryset(scope):
    scope = scope or {}
    candidate_filters = scope.get("candidate_filters") or {}
    qs = m.Candidate.objects.prefetch_related("resumes")
    candidate_ids = scope.get("candidate_ids") or []
    if candidate_ids:
        qs = qs.filter(id__in=candidate_ids)
    if candidate_filters:
        qs = system_status.apply_candidate_filters(qs, candidate_filters)
    statuses = scope.get("system_statuses") or []
    if statuses:
        qs = system_status.filter_queryset_by_system_status(qs, statuses)
    return qs.prefetch_related("resumes")


def candidate_ids_for_scope(scope=None):
    """返回提交时可被冻结的候选人范围，顺序固定以降低并发任务锁冲突。"""
    return _candidate_queryset(scope).order_by("id").values_list("id", flat=True)


def _is_scoped_reprocess(scope):
    scope = scope or {}
    return bool(
        scope.get("force_reprocess") is True
        or system_status.normalize_statuses(scope.get("system_statuses"))
        or scope.get("source") == "ai_retry"
    )


def _should_force_ai(scope):
    scope = scope or {}
    return scope.get("source") == "ai_retry" or scope.get("force_reprocess") is True


def _reopen_workflow(workflow, mode):
    workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
    workflow.passed_attempt = None
    workflow.archive_reason = ""
    workflow.archive_detail = ""
    _clear_block(workflow)
    workflow.completed_at = None
    workflow.dispatch_strategy = mode
    workflow.save(
        update_fields=[
            "status",
            "passed_attempt",
            "archive_reason",
            "archive_detail",
            "block_reason",
            "block_detail",
            "completed_at",
            "dispatch_strategy",
            "updated_at",
        ]
    )


def _next_attempt_no(workflow):
    max_no = workflow.attempts.aggregate(max_no=Max("attempt_no"))["max_no"] or 0
    return max_no + 1


def _first_secondary_contact(department):
    return (
        m.Contact.objects.filter(
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        .order_by("id")
        .first()
    )


def _mapped_job_pool(resume, *, mode):
    jobs_query = (
        m.Job.objects.select_related("department", "department__parent")
        .filter(is_active=True)
        .order_by("id")
    )
    if mode == "rule":
        jobs_query = jobs_query.prefetch_related("majors")
    jobs = list(jobs_query)
    jobs, mapping = resolve_job_pool(resume, jobs)
    if mode == "rule":
        return get_rule_strategy().filter_major_eligible_jobs(resume, jobs, mapping)
    if mode == "ai":
        return jobs, mapping
    raise ValueError(f"未知岗位池模式: {mode}")


def _targetable_job_pool(resume, *, mode):
    jobs, mapping = _mapped_job_pool(resume, mode=mode)
    _save_mapped_classification(resume, jobs[0], mapping, mode)
    jobs_with_departments = [
        job for job in jobs if _secondary_department(job.department)
    ]
    if not jobs_with_departments:
        raise JobMappingError(
            "secondary_department_missing",
            f"已映射内部职位“{mapping['internal_name']}”，但未配置有效二级部门岗位",
        )
    contacts = {}
    targetable = []
    for job in jobs_with_departments:
        contact = _first_secondary_contact(_secondary_department(job.department))
        if contact:
            targetable.append(job)
            contacts[job.id] = contact
    if not targetable:
        department_names = "、".join(
            sorted(
                {
                    _secondary_department(job.department).name
                    for job in jobs_with_departments
                }
            )
        )
        raise JobMappingError(
            "secondary_contact_missing",
            f"已映射内部职位“{mapping['internal_name']}”，但二级部门“{department_names}”"
            "没有启用的二级接口人",
        )
    return targetable, contacts, mapping


def _select_job_capacity(processing_run, jobs, *, reserve):
    """按 `(已用量 + 1) / 容量` 选择岗位；任务内行锁保证并发不超配。"""
    jobs = sorted(jobs, key=lambda item: item.id)
    if not processing_run:
        return jobs[0], None
    capacities = list(
        m.ProcessingRunJobCapacity.objects.select_for_update()
        .filter(run=processing_run, job_id__in=[job.id for job in jobs])
        .order_by("job_id")
    )
    available = [
        capacity
        for capacity in capacities
        if capacity.capacity > 0 and capacity.used_count < capacity.capacity
    ]
    if not available:
        return None, None
    selected = min(
        available,
        key=lambda item: (
            Fraction(item.used_count + 1, item.capacity),
            item.job_id,
        ),
    )
    if reserve:
        selected.used_count += 1
        selected.save(update_fields=["used_count"])
    jobs_by_id = {job.id: job for job in jobs}
    return jobs_by_id[selected.job_id], selected


def _mapped_classification_reason(mapping, job):
    major_reason = mapping.get("major_reasons", {}).get(job.id, "")
    return "；".join(
        part
        for part in [
            f"对外职位名称精确映射内部职位：{mapping['internal_name']}",
            f"岗位名精确命中对外发布名称：{mapping['public_name']}",
            major_reason,
        ]
        if part
    )


def _save_mapped_classification(resume, job, mapping, mode):
    resume.job = job
    resume.job_category = job.category or "未分类"
    resume.category_mode = mode
    resume.category_reason = _mapped_classification_reason(mapping, job)
    resume.save(
        update_fields=["job", "job_category", "category_mode", "category_reason"]
    )


def _archive_reason_for_mapping_code(code):
    if code == "job_mapping_ambiguous":
        return m.CandidateWorkflow.ARCHIVE_JOB_MAPPING_AMBIGUOUS
    if code == "internal_position_name_missing":
        return m.CandidateWorkflow.ARCHIVE_INTERNAL_POSITION_NAME_MISSING
    if code == "secondary_department_missing":
        return m.CandidateWorkflow.ARCHIVE_DEPARTMENT_NOT_FOUND
    return m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED


def _assert_tertiary_contact(sub_contact, secondary_department):
    if not sub_contact or sub_contact.contact_level != m.Contact.LEVEL_TERTIARY:
        raise ValueError("目标三级接口人不存在")
    if not sub_contact.is_active:
        raise ValueError("目标三级接口人未启用")
    if not sub_contact.department or sub_contact.department.parent_id != secondary_department.id:
        raise ValueError("三级接口人不属于当前二级部门")


def _set_snapshots(attempt):
    attempt.department_name_snapshot = attempt.department.name if attempt.department else ""
    attempt.contact_name_snapshot = attempt.contact.name if attempt.contact else ""
    attempt.contact_employee_no_snapshot = (
        attempt.contact.employee_no if attempt.contact else ""
    )
    attempt.sub_department_name_snapshot = (
        attempt.sub_department.name if attempt.sub_department else ""
    )
    attempt.sub_contact_name_snapshot = (
        attempt.sub_contact.name if attempt.sub_contact else ""
    )
    attempt.sub_contact_employee_no_snapshot = (
        attempt.sub_contact.employee_no if attempt.sub_contact else ""
    )
    attempt.resume_apply_id_snapshot = attempt.resume.apply_id
    attempt.position_name_snapshot = attempt.resume.position_name
    attempt.created_by_username_snapshot = (
        attempt.created_by.username if attempt.created_by else ""
    )


def _create_handoff(
    *,
    attempt,
    action,
    to_contact,
    to_department=None,
    from_contact=None,
    note="",
    created_by=None,
):
    actual_to_department = to_department or (to_contact.department if to_contact else None)
    actual_created_by = (
        created_by if getattr(created_by, "is_authenticated", False) else None
    )
    return m.AssignmentHandoff.objects.create(
        attempt=attempt,
        action=action,
        from_contact=from_contact,
        to_department=actual_to_department,
        to_contact=to_contact,
        from_contact_name_snapshot=from_contact.name if from_contact else "",
        from_contact_employee_no_snapshot=(
            from_contact.employee_no if from_contact else ""
        ),
        to_department_name_snapshot=(
            actual_to_department.name if actual_to_department else ""
        ),
        to_contact_name_snapshot=to_contact.name if to_contact else "",
        to_contact_employee_no_snapshot=to_contact.employee_no if to_contact else "",
        note=note,
        created_by=actual_created_by,
        created_by_username_snapshot=actual_created_by.username
        if actual_created_by
        else "",
    )


def _touch_workflow(workflow, resume, mode):
    workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
    workflow.current_resume = resume
    workflow.current_rank = resume.volunteer_rank
    workflow.dispatch_strategy = mode
    workflow.archive_reason = ""
    workflow.archive_detail = ""
    _clear_block(workflow)
    workflow.started_at = workflow.started_at or timezone.now()
    workflow.completed_at = None
    workflow.save(
        update_fields=[
            "status",
            "current_resume",
            "current_rank",
            "dispatch_strategy",
            "archive_reason",
            "archive_detail",
            "block_reason",
            "block_detail",
            "started_at",
            "completed_at",
            "updated_at",
        ]
    )


def _create_attempt(
    *,
    workflow,
    resume,
    contact,
    source,
    mode,
    matched_rule=None,
    match_reason="",
    manual_reason="",
    created_by=None,
    sub_contact=None,
    agent_decision=None,
    confidence_score=None,
    review_required=False,
    status=None,
    route_code="",
    special_route_confidence=None,
    special_route_evidence=None,
    special_route_config_snapshot=None,
    capacity_reservation=None,
):
    now = timezone.now()
    sub_department = sub_contact.department if sub_contact else None
    attempt = m.AssignmentAttempt(
        workflow=workflow,
        resume=resume,
        attempt_no=_next_attempt_no(workflow),
        source=source,
        status=status
        or (
            m.AssignmentAttempt.STATUS_ASSIGNED_L3
            if sub_contact
            else m.AssignmentAttempt.STATUS_PENDING_DISPATCH
        ),
        department=contact.department if contact else None,
        contact=contact,
        sub_department=sub_department,
        sub_contact=sub_contact,
        matched_rule=matched_rule,
        agent_decision=agent_decision,
        confidence_score=confidence_score,
        review_required=review_required,
        match_mode=mode,
        match_reason=match_reason,
        manual_reason=manual_reason,
        route_code=route_code,
        special_route_confidence=special_route_confidence,
        special_route_evidence=special_route_evidence or [],
        special_route_config_snapshot=special_route_config_snapshot or {},
        dispatched_at=now if sub_contact else None,
        assigned_to_sub_at=now if sub_contact else None,
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
        capacity_reservation=capacity_reservation,
    )
    _set_snapshots(attempt)
    attempt.save()

    if sub_contact:
        direct_note = (
            "系统 AI 自动分配"
            if route_code == "ai_special_route"
            else "HR 手动直达三级接口人"
        )
        _create_handoff(
            attempt=attempt,
            action=m.AssignmentHandoff.ACTION_HR_DISPATCH,
            to_contact=contact,
            to_department=attempt.department,
            created_by=created_by,
            note=direct_note,
        )
        _create_handoff(
            attempt=attempt,
            action=m.AssignmentHandoff.ACTION_SUB_ASSIGN,
            from_contact=contact,
            to_contact=sub_contact,
            to_department=sub_department,
            created_by=created_by,
            note=direct_note,
        )

    _touch_workflow(workflow, resume, mode)
    return attempt


def _candidate_resumes(candidate, after_rank=None):
    """按志愿顺序取候选人接下来可尝试的投递。

    workflow.current_rank 记录已经进入处理链路的志愿。三级反馈未通过后，
    这里只取更高 rank 的投递，确保系统按志愿顺序推进，不提前暴露后续志愿。
    """
    qs = candidate.resumes.filter(volunteer_rank__isnull=False).select_related(
        "job__department"
    ).order_by("volunteer_rank", "apply_date", "id")
    if after_rank is not None:
        qs = qs.filter(volunteer_rank__gt=after_rank)
    return qs


def _effective_resume_for_attempt(
    workflow,
    *,
    retry_resume_id=None,
    advance_after_feedback=False,
):
    """选择本轮唯一有效志愿；只有未通过反馈链路可以推进到下一志愿。"""
    resumes = _candidate_resumes(workflow.candidate)
    if retry_resume_id:
        return resumes.filter(pk=retry_resume_id).first()
    if advance_after_feedback:
        return _candidate_resumes(
            workflow.candidate,
            after_rank=workflow.current_rank,
        ).first()
    if workflow.current_resume_id:
        current = resumes.filter(pk=workflow.current_resume_id).first()
        if current:
            return current
    return resumes.first()


def _classify_resume(resume, strategy, jobs, mode):
    """执行岗位分类并把分类结果写回 Resume。

    分类结果既用于本次分配，也用于简历库展示和筛选。即使未命中岗位，也会
    写入 `未匹配`/category_reason，方便 HR 判断是岗位名、主体还是专业造成
    自动分配中断。
    """
    job, category, reason = strategy.classify(resume, jobs)
    resume.job = job
    resume.job_category = category
    resume.category_mode = mode
    resume.category_reason = reason
    resume.save(
        update_fields=["job", "job_category", "category_mode", "category_reason"]
    )
    return job, category, reason


def _rule_match_reason(admission, resume, job, contact, classify_reason):
    """生成 Rule 分配尝试的人可读匹配理由。

    AssignmentAttempt.match_reason 是 HR 查看自动分配结果时最直接的审计线索，
    因此这里把硬规则和匹配链路串起来：院校准入、志愿序号、岗位/专业命中、
    最终分配到的二级部门和接口人。
    """
    admission_reason = (
        f"院校准入：命中{admission.matched_rule.name}"
        if admission.matched_rule
        else "院校准入：未启用规则，放行"
    )
    rank_reason = f"第{resume.volunteer_rank}志愿"
    department_name = contact.department.name if contact and contact.department else ""
    contact_name = contact.name if contact else ""
    dispatch_reason = (
        f"分配至{department_name}/{contact_name}"
        if department_name or contact_name
        else "分配目标待确认"
    )
    return "；".join(
        part
        for part in [
            admission_reason,
            rank_reason,
            classify_reason,
            dispatch_reason,
        ]
        if part
    )


def _retry_allowed(decision):
    if decision.error_code:
        return True
    if decision.recommendation == m.AgentDispatchDecision.RECOMMEND_ARCHIVE:
        return True
    if (
        decision.confidence_score is not None
        and decision.confidence_score
        < ai_config.get_ai_runtime_config().dispatch_threshold
    ):
        return True
    return False


def validate_agent_decision_retry(decision):
    if not _retry_allowed(decision):
        raise ValueError("仅失败、建议归档或低于自动下发阈值的 AI 决策可以重试")


def _create_agent_decision(workflow, resume, result):
    runtime_config = ai_config.get_ai_runtime_config()
    versions = _ai_audit_versions(getattr(workflow, "_processing_run", None))
    proposed = result.output.decision.recommendation
    confidence = result.confidence
    if proposed == m.AgentDispatchDecision.RECOMMEND_DISPATCH and confidence >= runtime_config.dispatch_threshold:
        recommendation = m.AgentDispatchDecision.RECOMMEND_DISPATCH
    elif proposed != m.AgentDispatchDecision.RECOMMEND_ARCHIVE and confidence >= runtime_config.review_threshold:
        recommendation = m.AgentDispatchDecision.RECOMMEND_REVIEW
    else:
        recommendation = m.AgentDispatchDecision.RECOMMEND_ARCHIVE
    output = result.output.decision
    risks = list(dict.fromkeys([*output.risks, *result.output.profile.risk_flags]))
    return m.AgentDispatchDecision.objects.create(
        workflow=workflow,
        resume=resume,
        profile=result.profile,
        processing_run=getattr(workflow, "_processing_run", None),
        recommendation=recommendation,
        evaluated_job=result.job,
        recommended_job=result.job,
        matched_job_category=result.job.category if result.job else "",
        recommended_department=result.department,
        recommended_contact=result.contact,
        recommended_contact_name_snapshot=result.contact.name if result.contact else "",
        recommended_contact_employee_no_snapshot=(
            result.contact.employee_no if result.contact else ""
        ),
        confidence_score=confidence,
        score_breakdown=result.score_breakdown,
        summary=output.summary,
        reason=output.reason,
        evidence=output.evidence,
        risks=risks,
        risk_flags=risks,
        ai_specialist_match=bool(getattr(output, "ai_specialist_match", False)),
        ai_specialist_confidence=float(
            getattr(output, "ai_specialist_confidence", 0) or 0
        ),
        ai_specialist_evidence=list(
            getattr(output, "ai_specialist_evidence", []) or []
        ),
        model_name=getattr(result, "model_name", versions["model_name"]),
        prompt_version=getattr(
            result, "prompt_version", versions["prompt_version"]
        ),
        decision_version=getattr(
            result, "decision_version", versions["decision_version"]
        ),
    )


def _ai_audit_versions(processing_run=None):
    """AI 未配置时仍可记录失败决策，但不构造或回退任何模型连接。"""
    if processing_run is not None:
        return {
            "model_name": processing_run.model_name,
            "prompt_version": processing_run.prompt_version,
            "decision_version": processing_run.decision_version,
        }
    try:
        config = ai_config.get_ai_model_config()
    except (RuntimeError, ValueError):
        return {
            "model_name": "",
            "prompt_version": "resume-screening-v2",
            "decision_version": "decision-v1",
        }
    return {
        "model_name": config.model_name,
        "prompt_version": config.prompt_version,
        "decision_version": config.decision_version,
    }


def _create_agent_failure_decision(
    workflow,
    resume,
    *,
    error_code,
    error_message,
    profile=None,
):
    return m.AgentDispatchDecision.objects.create(
        workflow=workflow,
        resume=resume,
        profile=profile,
        processing_run=getattr(workflow, "_processing_run", None),
        recommendation=None,
        evaluated_job=None,
        recommended_job=None,
        matched_job_category="",
        recommended_department=None,
        recommended_contact=None,
        confidence_score=None,
        score_breakdown={},
        summary="AI 未形成有效下发建议",
        reason="",
        evidence=[],
        risks=[error_message],
        risk_flags=[error_code],
        error_code=error_code,
        error_message=error_message,
        **_ai_audit_versions(getattr(workflow, "_processing_run", None)),
    )


def _ai_current_volunteer_prerequisite(resume, processing_run=None):
    """直接完成 AI 当前志愿的岗位、部门、接口人和 HC 目标选择。"""
    try:
        jobs, _contacts, mapping = _targetable_job_pool(resume, mode="ai")
    except JobMappingError as exc:
        error_code = (
            "reference_not_found"
            if exc.code in {"secondary_department_missing", "secondary_contact_missing"}
            else "guardrail_blocked"
        )
        return None, error_code, exc.detail
    job, _capacity = _select_job_capacity(processing_run, jobs, reserve=False)
    if not job:
        return (
            None,
            "guardrail_blocked",
            f"当前任务中内部职位“{mapping['internal_name']}”的岗位 HC 容量已用尽",
        )
    _save_mapped_classification(resume, job, mapping, "ai")
    return job, "", ""


def _process_ai_recommendation(
    workflow,
    resume,
    *,
    matched_rule,
    job,
    force=False,
):
    _touch_workflow(workflow, resume, "ai")
    try:
        department = _secondary_department(job.department)
        result = ai_service.screen_resume(
            resume,
            job,
            department=department,
            contact=_first_secondary_contact(department),
            force=force,
        )
    except ai_service.AIServiceError as exc:
        _create_agent_failure_decision(
            workflow,
            resume,
            error_code=exc.code,
            error_message=exc.message,
            profile=exc.profile,
        )
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
            f"AI 未形成有效建议：{exc.message}",
        )
        return None

    return _apply_ai_result(
        workflow,
        resume,
        matched_rule=matched_rule,
        result=result,
    )


def _apply_ai_result(workflow, resume, *, matched_rule, result):
    """把已完成的模型结果写入候选人业务流程；调用方必须持有流程锁。"""

    decision = _create_agent_decision(workflow, resume, result)
    resume.job = result.job
    resume.job_category = result.job.category if result.job else "未匹配"
    resume.category_mode = "ai"
    resume.category_reason = decision.reason
    resume.save(
        update_fields=["job", "job_category", "category_mode", "category_reason"]
    )
    capacity_reservation = None
    automatic_contact = result.contact
    if decision.recommendation != m.AgentDispatchDecision.RECOMMEND_ARCHIVE:
        try:
            job_pool, contacts, mapping = _targetable_job_pool(resume, mode="ai")
        except JobMappingError as exc:
            if exc.code == "secondary_contact_missing":
                _block_current_volunteer(
                    workflow, m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND, exc.detail
                )
            else:
                _archive(
                    workflow, _archive_reason_for_mapping_code(exc.code), exc.detail
                )
            return None
        selected_job, capacity_reservation = _select_job_capacity(
            getattr(workflow, "_processing_run", None), job_pool, reserve=True
        )
        if not selected_job:
            _save_mapped_classification(resume, job_pool[0], mapping, "ai")
            _block_current_volunteer(
                workflow,
                m.CandidateWorkflow.BLOCK_JOB_HC_EXHAUSTED,
                f"当前任务中内部职位“{mapping['internal_name']}”的岗位 HC 容量已用尽，"
                "候选人保留当前志愿，等待新任务重新分配",
            )
            return None
        _save_mapped_classification(resume, selected_job, mapping, "ai")
        automatic_contact = contacts[selected_job.id]
        decision.recommended_job = selected_job
        decision.recommended_department = _secondary_department(selected_job.department)
        decision.recommended_contact = automatic_contact
        decision.recommended_contact_name_snapshot = automatic_contact.name
        decision.recommended_contact_employee_no_snapshot = automatic_contact.employee_no
        decision.save(
            update_fields=[
                "recommended_job",
                "recommended_department",
                "recommended_contact",
                "recommended_contact_name_snapshot",
                "recommended_contact_employee_no_snapshot",
            ]
        )
    try:
        special_config = ai_config.get_ai_special_route_config()
    except (TypeError, ValueError) as exc:
        decision.special_route_config_snapshot = {
            "fallback_code": "config_invalid",
            "fallback_error_type": type(exc).__name__,
        }
        decision.save(update_fields=["special_route_config_snapshot"])
        special_config = None
    special_hit = (
        special_config is not None
        and special_config.enabled
        and decision.ai_specialist_match
        and decision.ai_specialist_confidence is not None
        and decision.ai_specialist_confidence > special_config.threshold
    )
    if special_hit:
        try:
            special_config = ai_config.get_ai_special_route_config(validate=True)
            secondary_contact = m.Contact.objects.select_related("department").get(
                pk=special_config.secondary_contact_id
            )
            tertiary_contact = m.Contact.objects.select_related(
                "department__parent"
            ).get(pk=special_config.tertiary_contact_id)
            snapshot = special_config.snapshot()
            attempt = _force_assign_locked(
                workflow=workflow,
                resume=resume,
                contact=tertiary_contact,
                secondary_contact=secondary_contact,
                source=m.AssignmentAttempt.SOURCE_AI,
                mode="ai",
                match_reason="AI 自动分配",
                agent_decision=decision,
                confidence_score=decision.confidence_score,
                route_code="ai_special_route",
                special_route_confidence=decision.ai_specialist_confidence,
                special_route_evidence=decision.ai_specialist_evidence,
                special_route_config_snapshot=snapshot,
                invalidate_processing=False,
                capacity_reservation=capacity_reservation,
            )
        except (m.Contact.DoesNotExist, TypeError, ValueError) as exc:
            # 专项路由是后台增强能力，目标配置瞬时失效不能阻断普通 AI 结果。
            # 失败原因仅写入内部审计快照，不进入候选人结果或公开错误码。
            snapshot = special_config.snapshot()
            snapshot["fallback_code"] = "target_unavailable"
            snapshot["fallback_error_type"] = type(exc).__name__
            decision.special_route_config_snapshot = snapshot
            decision.save(
                update_fields=["special_route_config_snapshot"]
            )
        else:
            decision.special_route_applied = True
            decision.special_route_config_snapshot = snapshot
            decision.save(
                update_fields=["special_route_applied", "special_route_config_snapshot"]
            )
            return attempt
    if decision.recommendation == m.AgentDispatchDecision.RECOMMEND_ARCHIVE:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
            "AI 建议归档或置信度低于人工复核阈值",
        )
        return None
    if decision.recommendation == m.AgentDispatchDecision.RECOMMEND_REVIEW:
        return _create_attempt(
            workflow=workflow,
            resume=resume,
            contact=result.contact,
            source=m.AssignmentAttempt.SOURCE_AI,
            mode="ai",
            matched_rule=matched_rule,
            agent_decision=decision,
            confidence_score=decision.confidence_score,
            match_reason=decision.reason,
            review_required=True,
            status=m.AssignmentAttempt.STATUS_PENDING_REVIEW,
            capacity_reservation=capacity_reservation,
        )
    return _create_attempt(
        workflow=workflow,
        resume=resume,
        contact=automatic_contact,
        source=m.AssignmentAttempt.SOURCE_AI,
        mode="ai",
        matched_rule=matched_rule,
        agent_decision=decision,
        confidence_score=decision.confidence_score,
        match_reason=decision.reason,
        capacity_reservation=capacity_reservation,
    )


AI_SCOPE_TERMINAL_STATUSES = {
    "success",
    "needs_attention",
    "failed",
    "skipped_manual_change",
    "cancelled",
}


def _claim_expiry():
    config = ai_config.get_ai_runtime_config()
    max_backoff = sum(
        min(300, config.retry_backoff_seconds * (2 ** retry_index))
        for retry_index in range(config.retry_count)
    )
    seconds = (
        config.timeout_seconds * (config.retry_count + 1)
        + max_backoff
        + 120
    )
    return timezone.now() + timedelta(seconds=max(180, seconds))


def _release_processing_claim(workflow_id, token):
    m.CandidateWorkflow.objects.filter(
        pk=workflow_id,
        active_processing_token=token,
    ).update(
        active_processing_scope_item=None,
        active_processing_token=None,
        active_processing_expires_at=None,
    )


def release_ai_scope_claim(scope_item_id):
    """任务异常重试前释放本次租约；令牌不匹配时不影响其它 worker。"""
    item = m.ProcessingRunScopeItem.objects.filter(pk=scope_item_id).first()
    if not item or not item.dispatch_token:
        return
    workflow = m.CandidateWorkflow.objects.filter(candidate_id=item.candidate_id).first()
    if workflow:
        _release_processing_claim(workflow.id, item.dispatch_token)


def _scope_revision_changed(scope_item, workflow, workflow_created):
    expected = (
        scope_item.workflow_revision_at_prepare
        if scope_item.workflow_revision_at_prepare is not None
        else scope_item.workflow_revision_at_submit
    )
    if expected is None:
        # revision=0 且仅带自动处理租约时，表示另一个自动任务刚创建流程；
        # 先等待它结束，再依据最终 revision 决定是否跳过。
        return not workflow_created and workflow.revision > 0
    return workflow.revision != expected


def process_ai_scope_item(run_id, scope_item_id):
    """候选人 AI 两阶段处理：短事务领取，模型调用，短事务提交。"""
    now = timezone.now()
    with transaction.atomic():
        run = m.ProcessingRun.objects.select_for_update().get(pk=run_id)
        item = (
            m.ProcessingRunScopeItem.objects.select_for_update()
            .select_related("candidate")
            .get(pk=scope_item_id, run=run)
        )
        if item.status in AI_SCOPE_TERMINAL_STATUSES:
            return {"status": item.status, "already_terminal": True}
        if run.cancel_requested_at:
            _scope_result(
                item,
                status="cancelled",
                result_type=RESULT_CANCELLED,
                reason_code="cancelled",
                message="任务已取消",
            )
            return {"status": "cancelled"}

        candidate = m.Candidate.objects.select_for_update().get(pk=item.candidate_id)
        workflow, workflow_created = (
            m.CandidateWorkflow.objects.select_for_update().get_or_create(
                candidate=candidate
            )
        )
        active_elsewhere = (
            workflow.active_processing_scope_item_id
            and workflow.active_processing_scope_item_id != item.id
            and workflow.active_processing_expires_at
            and workflow.active_processing_expires_at > now
        )
        if active_elsewhere:
            item.status = "waiting_conflict"
            item.save(update_fields=["status"])
            return {"status": "waiting_conflict"}
        if _scope_revision_changed(item, workflow, workflow_created):
            item.status = "skipped_manual_change"
            item.skip_reason = "workflow_changed_after_submit"
            item.finished_at = now
            item.save(update_fields=["status", "skip_reason", "finished_at"])
            return {"status": "skipped_manual_change"}

        scoped_reprocess = _is_scoped_reprocess(run.scope)
        if not scoped_reprocess and workflow.status in {
            m.CandidateWorkflow.STATUS_PASSED,
            m.CandidateWorkflow.STATUS_ARCHIVED,
        }:
            item.status = "success"
            item.skip_reason = "terminal_workflow"
            item.finished_at = now
            item.save(update_fields=["status", "skip_reason", "finished_at"])
            return {"status": "success"}

        token = item.dispatch_token or uuid.uuid4()
        m.CandidateWorkflow.objects.filter(pk=workflow.pk).update(
            active_processing_scope_item=item,
            active_processing_token=token,
            active_processing_expires_at=_claim_expiry(),
        )
        item.dispatch_token = token
        item.status = "processing"
        item.attempt_count = F("attempt_count") + 1
        item.started_at = item.started_at or now
        item.error_code = ""
        item.error_message = ""
        item.save(
            update_fields=[
                "dispatch_token",
                "status",
                "attempt_count",
                "started_at",
                "error_code",
                "error_message",
            ]
        )
        claimed_revision = workflow.revision
        candidate_id = candidate.id
        prepared_resume_id = item.prepared_resume_id
        prepared_job_id = item.prepared_job_id
        prepared_department_id = item.prepared_department_id
        prepared_contact_id = item.prepared_contact_id
        force_ai = _should_force_ai(run.scope)

    resume = m.Resume.objects.filter(pk=prepared_resume_id).first()
    job = m.Job.objects.select_related("department", "department__parent").filter(
        pk=prepared_job_id,
        is_active=True,
    ).first()
    department = m.Department.objects.filter(pk=prepared_department_id, level=2).first()
    contact = m.Contact.objects.select_related("department").filter(
        pk=prepared_contact_id,
        contact_level=m.Contact.LEVEL_SECONDARY,
        is_active=True,
    ).first()
    result = None
    ai_error = None
    last_cancel_check = [0.0, False]

    def cancelled():
        now_monotonic = time.monotonic()
        if now_monotonic - last_cancel_check[0] >= 1:
            last_cancel_check[0] = now_monotonic
            last_cancel_check[1] = m.ProcessingRun.objects.filter(
                pk=run_id, cancel_requested_at__isnull=False
            ).exists()
        return last_cancel_check[1]

    references_valid = bool(
        resume
        and job
        and department
        and contact
        and contact.department_id == department.id
        and _secondary_department(job.department)
        and _secondary_department(job.department).id == department.id
    )
    if not references_valid:
        ai_error = ai_service.AIServiceError(
            "ai_reference_invalidated",
            "岗位与分配前置检查固定的岗位、二级部门或二级接口人在 AI 执行前已失效",
        )
    else:
        try:
            result = ai_service.screen_resume(
                resume,
                job,
                department=department,
                contact=contact,
                force=force_ai,
                processing_run_id=run_id,
                cancelled=cancelled,
                prompt_version=run.prompt_version,
            )
        except ai_service.AIServiceError as exc:
            ai_error = exc

    with transaction.atomic():
        run = m.ProcessingRun.objects.select_for_update().get(pk=run_id)
        item = m.ProcessingRunScopeItem.objects.select_for_update().get(pk=scope_item_id)
        workflow = m.CandidateWorkflow.objects.select_for_update().get(
            candidate_id=candidate_id
        )
        if item.status in AI_SCOPE_TERMINAL_STATUSES:
            return {"status": item.status, "already_terminal": True}
        token_matches = (
            workflow.active_processing_scope_item_id == item.id
            and workflow.active_processing_token == item.dispatch_token
        )
        revision_matches = workflow.revision == claimed_revision
        if not token_matches or not revision_matches:
            if token_matches:
                _release_processing_claim(workflow.id, item.dispatch_token)
            item.status = "skipped_manual_change"
            item.skip_reason = "workflow_changed_during_ai"
            item.finished_at = timezone.now()
            item.save(update_fields=["status", "skip_reason", "finished_at"])
            return {"status": "skipped_manual_change"}
        if run.cancel_requested_at:
            _release_processing_claim(workflow.id, item.dispatch_token)
            _scope_result(
                item,
                status="cancelled",
                result_type=RESULT_CANCELLED,
                reason_code="cancelled",
                message="任务已取消",
            )
            return {"status": "cancelled"}

        workflow._processing_run = run
        cancelled_attempts = _cancel_unfeedbacked_attempts(
            workflow,
            m.AssignmentAttempt.CANCEL_RERUN,
            sources=[m.AssignmentAttempt.SOURCE_AI, m.AssignmentAttempt.SOURCE_RULE]
            if scoped_reprocess
            else None,
            source=None if scoped_reprocess else m.AssignmentAttempt.SOURCE_AI,
        )
        workflow.dispatch_strategy = "ai"
        _clear_block(workflow)
        workflow.save(
            update_fields=[
                "dispatch_strategy",
                "block_reason",
                "block_detail",
                "updated_at",
            ]
        )

        created = False
        recommendation = ""
        if ai_error:
            if resume:
                _touch_workflow(workflow, resume, "ai")
                decision = _create_agent_failure_decision(
                    workflow,
                    resume,
                    error_code=ai_error.code,
                    error_message=ai_error.message,
                    profile=ai_error.profile,
                )
                error_message = decision.error_message
            else:
                error_message = ai_error.message
            status_value, result_type, reason_code = _ai_failure_result(ai_error.code)
            _block_current_volunteer(
                workflow,
                reason_code,
                f"AI 未形成有效建议：{ai_error.message}",
            )
            _release_processing_claim(workflow.id, item.dispatch_token)
            _scope_result(
                item,
                status=status_value,
                result_type=result_type,
                reason_code=reason_code,
                message=error_message,
            )
            return {
                "status": item.status,
                "result_type": item.result_type,
                "reason_code": item.reason_code,
                "recommendation": "",
                "created": False,
                "cancelled_attempts": cancelled_attempts,
            }
        else:
            _touch_workflow(workflow, resume, "ai")
            attempt = _apply_ai_result(
                workflow,
                resume,
                matched_rule=item.matched_rule,
                result=result,
            )
            created = attempt is not None
            decision = workflow.agent_decisions.filter(processing_run=run).latest("id")
            recommendation = decision.recommendation or ""

        _release_processing_claim(workflow.id, item.dispatch_token)
        if workflow.block_reason == m.CandidateWorkflow.BLOCK_JOB_HC_EXHAUSTED:
            reason_code = "job_hc_exhausted"
            result_message = workflow.block_detail
            recommendation = ""
        elif (
            workflow.archive_reason
            == m.CandidateWorkflow.ARCHIVE_JOB_MAPPING_AMBIGUOUS
        ):
            reason_code = "job_mapping_ambiguous"
            result_message = workflow.archive_detail
            recommendation = ""
        elif (
            workflow.archive_reason
            == m.CandidateWorkflow.ARCHIVE_INTERNAL_POSITION_NAME_MISSING
        ):
            reason_code = "internal_position_name_missing"
            result_message = workflow.archive_detail
            recommendation = ""
        else:
            reason_code = {
                m.AgentDispatchDecision.RECOMMEND_DISPATCH: "ai_dispatched",
                m.AgentDispatchDecision.RECOMMEND_REVIEW: "ai_review",
                m.AgentDispatchDecision.RECOMMEND_ARCHIVE: "ai_archived",
            }.get(decision.recommendation, "ai_completed")
            result_message = decision.reason or decision.summary
        _scope_result(
            item,
            status="success",
            result_type=RESULT_COMPLETED,
            reason_code=reason_code,
            message=result_message,
        )
        return {
            "status": item.status,
            "result_type": item.result_type,
            "reason_code": item.reason_code,
            "recommendation": recommendation,
            "created": created,
            "cancelled_attempts": cancelled_attempts,
        }


def _create_next_auto_attempt(
    workflow,
    rules,
    mode="rule",
    processing_run=None,
    *,
    force_ai=False,
    retry_resume_id=None,
    admission=None,
    advance_after_feedback=False,
):
    """为候选人创建下一条自动分配尝试。

    这是 Rule/AI 共用的自动分配入口。共同硬规则先于策略执行：
    1. 院校准入不通过则直接归档，不进入岗位/专业匹配。
    2. 每次只处理当前有效志愿；收到未通过反馈后，workflow.current_rank 才推进。
    3. 当前志愿必须能匹配岗位、二级部门和启用的二级接口人，才生成尝试。

    AI 只评估当前有效志愿；任何 AI 失败都不会跳志愿或回退 Rule。
    """
    workflow._processing_run = processing_run
    candidate = workflow.candidate
    # 正式流水线已在 Step2 固化院校标签与准入结果，Step3 直接使用该快照，
    # 避免后续规则或 AI 重复判断、改写院校结论。旧的直接调用入口仍可自行评估。
    admission = admission or school_admission.evaluate(candidate, rules)
    if not admission.passed:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_SCHOOL_RULE_NOT_MATCHED,
            admission.failure_detail,
        )
        return None

    if mode == "ai":
        resume = _effective_resume_for_attempt(
            workflow,
            retry_resume_id=retry_resume_id,
            advance_after_feedback=advance_after_feedback,
        )
        if not resume:
            _archive(
                workflow,
                m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME,
                "没有下一条可尝试志愿",
            )
            return None
        _touch_workflow(workflow, resume, "ai")
        job, prerequisite_code, prerequisite_detail = _ai_current_volunteer_prerequisite(
            resume, processing_run
        )
        if prerequisite_detail:
            _create_agent_failure_decision(
                workflow,
                resume,
                error_code=prerequisite_code,
                error_message=prerequisite_detail,
            )
            _archive(
                workflow,
                m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
                prerequisite_detail,
            )
            return None
        return _process_ai_recommendation(
            workflow,
            resume,
            matched_rule=admission.matched_rule,
            job=job,
            force=force_ai,
        )

    resume = _effective_resume_for_attempt(
        workflow,
        advance_after_feedback=advance_after_feedback,
    )
    if not resume:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME,
            "没有下一条可尝试志愿",
        )
        return None

    _touch_workflow(workflow, resume, mode)
    try:
        job_pool, contacts, mapping = _targetable_job_pool(resume, mode="rule")
    except JobMappingError as exc:
        if exc.code == "secondary_contact_missing":
            _block_current_volunteer(
                workflow, m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND, exc.detail
            )
        else:
            _archive(workflow, _archive_reason_for_mapping_code(exc.code), exc.detail)
        return None

    # 即使本任务容量已耗尽，也保留职位映射和岗位分类，供新任务直接回池。
    _save_mapped_classification(resume, job_pool[0], mapping, "rule")
    job, capacity_reservation = _select_job_capacity(
        processing_run, job_pool, reserve=True
    )
    if not job:
        detail = (
            f"当前任务中内部职位“{mapping['internal_name']}”的岗位 HC 容量已用尽，"
            "候选人保留当前志愿，等待新任务重新分配"
        )
        _block_current_volunteer(
            workflow, m.CandidateWorkflow.BLOCK_JOB_HC_EXHAUSTED, detail
        )
        return None
    _save_mapped_classification(resume, job, mapping, "rule")
    contact = contacts[job.id]
    classify_reason = _mapped_classification_reason(mapping, job)

    return _create_attempt(
        workflow=workflow,
        resume=resume,
        contact=contact,
        source=m.AssignmentAttempt.SOURCE_RULE,
        mode="rule",
        matched_rule=admission.matched_rule,
        match_reason=_rule_match_reason(
            admission, resume, job, contact, classify_reason
        ),
        capacity_reservation=capacity_reservation,
    )


def _admission_reason_code(admission):
    if admission.reason_code:
        return admission.reason_code
    detail = admission.failure_detail or ""
    return (
        "education_not_eligible"
        if "最高学历缺失" in detail or "最高学历不在" in detail
        else "school_not_eligible"
    )


def run_school_gate(scope=None, mode="rule", processing_run=None, processing_stage=None):
    """Step2：在指定范围内完整重算院校标签，并执行学历/院校准入。"""
    scope = scope or {}
    rules = school_admission.active_rules()
    candidate_ids = list(candidate_ids_for_scope(scope))
    scoped_reprocess = _is_scoped_reprocess(scope)
    passed = 0
    rejected = 0

    for candidate_id in candidate_ids:
        raise_if_cancel_requested(processing_run)
        with transaction.atomic():
            item = (
                m.ProcessingRunScopeItem.objects.select_for_update().get(
                    run=processing_run, candidate_id=candidate_id
                )
                if processing_run
                else None
            )
            if item and item.result_type:
                continue
            candidate = m.Candidate.objects.select_for_update().get(pk=candidate_id)
            workflow, created = m.CandidateWorkflow.objects.select_for_update().get_or_create(
                candidate=candidate
            )
            if item and _scope_revision_changed(item, workflow, created):
                item.status = "skipped_manual_change"
                item.skip_reason = "workflow_changed_after_submit"
                item.finished_at = timezone.now()
                item.save(update_fields=["status", "skip_reason", "finished_at"])
                continue
            if scoped_reprocess:
                _reopen_workflow(workflow, mode)
                _cancel_unfeedbacked_attempts(
                    workflow,
                    m.AssignmentAttempt.CANCEL_RERUN,
                    sources=[m.AssignmentAttempt.SOURCE_RULE, m.AssignmentAttempt.SOURCE_AI],
                )
            elif workflow.status in {
                m.CandidateWorkflow.STATUS_PASSED,
                m.CandidateWorkflow.STATUS_ARCHIVED,
            }:
                if item:
                    _scope_result(
                        item,
                        status="success",
                        result_type=RESULT_COMPLETED,
                        reason_code="terminal_workflow",
                        message="候选人已处于终态，本次导入不重复处理",
                    )
                passed += 1
                continue

            classify_school.classify_candidates([candidate], overwrite=True)
            admission = school_admission.evaluate(candidate, rules)
            workflow.dispatch_strategy = mode
            workflow.started_at = workflow.started_at or timezone.now()
            workflow.save(update_fields=["dispatch_strategy", "started_at", "updated_at"])
            if not admission.passed:
                resumes = list(_candidate_resumes(candidate))
                if resumes:
                    workflow.current_resume = resumes[0]
                    workflow.current_rank = resumes[0].volunteer_rank
                    workflow.save(
                        update_fields=["current_resume", "current_rank", "updated_at"]
                    )
                _archive(
                    workflow,
                    m.CandidateWorkflow.ARCHIVE_SCHOOL_RULE_NOT_MATCHED,
                    admission.failure_detail,
                )
                if item:
                    _scope_result(
                        item,
                        status="success",
                        result_type=RESULT_COMPLETED,
                        reason_code=_admission_reason_code(admission),
                        message=admission.failure_detail,
                    )
                rejected += 1
                continue

            if item:
                item.matched_rule = admission.matched_rule
                item.workflow_revision_at_prepare = workflow.revision
                item.status = "pending"
                item.save(
                    update_fields=[
                        "matched_rule",
                        "workflow_revision_at_prepare",
                        "status",
                    ]
                )
            passed += 1

    sync_processing_run_results(processing_run, processing_stage)
    if processing_stage:
        processing_stage.total_count = len(candidate_ids)
        processing_stage.processed_count = len(candidate_ids)
        processing_stage.success_count = len(candidate_ids)
        processing_stage.completed_count = rejected
        processing_stage.save(
            update_fields=[
                "total_count",
                "processed_count",
                "success_count",
                "completed_count",
            ]
        )
    return f"院校分类与准入完成：通过 {passed}，规则不通过 {rejected}"


def _prepare_ai_target(resume, processing_run=None):
    try:
        job_pool, contacts, mapping = _targetable_job_pool(resume, mode="ai")
    except JobMappingError as exc:
        return None, None, None, exc.code, exc.detail
    _save_mapped_classification(resume, job_pool[0], mapping, "ai")
    job, _capacity = _select_job_capacity(processing_run, job_pool, reserve=False)
    if not job:
        return (
            job_pool[0],
            _secondary_department(job_pool[0].department),
            contacts[job_pool[0].id],
            "job_hc_exhausted",
            f"当前任务中内部职位“{mapping['internal_name']}”的岗位 HC 容量已用尽，"
            "候选人保留当前志愿，等待新任务重新分配",
        )
    _save_mapped_classification(resume, job, mapping, "ai")
    return job, _secondary_department(job.department), contacts[job.id], "", ""


def _rule_result_code(workflow, attempt):
    if attempt:
        return "rule_assigned", attempt.match_reason
    if workflow.block_reason == m.CandidateWorkflow.BLOCK_JOB_HC_EXHAUSTED:
        return "job_hc_exhausted", workflow.block_detail
    if workflow.block_reason == m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND:
        return "secondary_contact_missing", workflow.block_detail
    if workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_SCHOOL_RULE_NOT_MATCHED:
        code = (
            "education_not_eligible"
            if "最高学历缺失" in (workflow.archive_detail or "")
            or "最高学历不在" in (workflow.archive_detail or "")
            else "school_not_eligible"
        )
        return code, workflow.archive_detail
    if workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_DEPARTMENT_NOT_FOUND:
        return "secondary_department_missing", workflow.archive_detail
    if workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_JOB_MAPPING_AMBIGUOUS:
        return "job_mapping_ambiguous", workflow.archive_detail
    if (
        workflow.archive_reason
        == m.CandidateWorkflow.ARCHIVE_INTERNAL_POSITION_NAME_MISSING
    ):
        return "internal_position_name_missing", workflow.archive_detail
    if workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED:
        code = (
            "major_not_matched"
            if "专业" in (workflow.archive_detail or "")
            else "job_not_found"
        )
        return code, workflow.archive_detail
    return "no_resume_available", workflow.archive_detail or "没有下一条可尝试志愿"


def run_allocation_precheck(
    scope=None, mode="rule", processing_run=None, processing_stage=None
):
    """Step3：Rule 完成专业审核与分配；AI 独立冻结岗位/部门/接口人引用。"""
    scope = scope or {}
    candidate_ids = list(candidate_ids_for_scope(scope))
    rules = school_admission.active_rules()
    prepared = 0
    completed = 0
    retry_resume_id = scope.get("retry_resume_id")

    for candidate_id in candidate_ids:
        raise_if_cancel_requested(processing_run)
        with transaction.atomic():
            item = (
                m.ProcessingRunScopeItem.objects.select_for_update().get(
                    run=processing_run, candidate_id=candidate_id
                )
                if processing_run
                else None
            )
            if item and (item.result_type or item.status == "skipped_manual_change"):
                continue
            candidate = m.Candidate.objects.select_for_update().prefetch_related(
                "resumes"
            ).get(pk=candidate_id)
            workflow = m.CandidateWorkflow.objects.select_for_update().get(
                candidate=candidate
            )
            expected_revision = (
                item.workflow_revision_at_prepare
                if item and item.workflow_revision_at_prepare is not None
                else item.workflow_revision_at_submit if item else workflow.revision
            )
            if workflow.revision != expected_revision:
                if item:
                    item.status = "skipped_manual_change"
                    item.skip_reason = "workflow_changed_before_rule_precheck"
                    item.finished_at = timezone.now()
                    item.save(update_fields=["status", "skip_reason", "finished_at"])
                continue

            workflow._processing_run = processing_run
            if mode == "rule":
                admission = school_admission.SchoolAdmissionResult(
                    passed=True,
                    matched_rule=item.matched_rule if item else None,
                    has_active_rules=bool(item and item.matched_rule_id),
                )
                attempt = _create_next_auto_attempt(
                    workflow,
                    rules,
                    mode="rule",
                    processing_run=processing_run,
                    admission=admission,
                )
                code, message = _rule_result_code(workflow, attempt)
                if item:
                    _scope_result(
                        item,
                        status="success",
                        result_type=RESULT_COMPLETED,
                        reason_code=code,
                        message=message,
                    )
                completed += 1
                continue

            resume = _effective_resume_for_attempt(
                workflow,
                retry_resume_id=retry_resume_id,
            )
            if not resume:
                _archive(
                    workflow,
                    m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME,
                    "没有下一条可尝试志愿",
                )
                if item:
                    _scope_result(
                        item,
                        status="success",
                        result_type=RESULT_COMPLETED,
                        reason_code="no_resume_available",
                        message="没有下一条可尝试志愿",
                    )
                completed += 1
                continue

            job, department, contact, reason_code, detail = _prepare_ai_target(
                resume, processing_run
            )
            _touch_workflow(workflow, resume, "ai")
            if reason_code:
                if reason_code in {"secondary_contact_missing", "job_hc_exhausted"}:
                    block_reason = (
                        m.CandidateWorkflow.BLOCK_JOB_HC_EXHAUSTED
                        if reason_code == "job_hc_exhausted"
                        else m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND
                    )
                    _block_current_volunteer(workflow, block_reason, detail)
                else:
                    archive_reason = _archive_reason_for_mapping_code(reason_code)
                    _archive(workflow, archive_reason, detail)
                if item:
                    _scope_result(
                        item,
                        status="success",
                        result_type=RESULT_COMPLETED,
                        reason_code=reason_code,
                        message=detail,
                    )
                completed += 1
                continue

            if item:
                item.prepared_resume = resume
                item.prepared_job = job
                item.prepared_department = department
                item.prepared_contact = contact
                item.workflow_revision_at_prepare = workflow.revision
                item.status = "pending"
                item.save(
                    update_fields=[
                        "prepared_resume",
                        "prepared_job",
                        "prepared_department",
                        "prepared_contact",
                        "workflow_revision_at_prepare",
                        "status",
                    ]
                )
            prepared += 1

    sync_processing_run_results(processing_run, processing_stage)
    if processing_stage:
        processing_stage.total_count = len(candidate_ids)
        processing_stage.processed_count = len(candidate_ids)
        processing_stage.success_count = len(candidate_ids)
        processing_stage.completed_count = completed
        processing_stage.save(
            update_fields=[
                "total_count",
                "processed_count",
                "success_count",
                "completed_count",
            ]
        )
    return (
        f"岗位与分配前置检查完成：AI 待深度筛选 {prepared}，"
        f"已形成明确业务结果 {completed}"
    )


def _sync_stage_progress(processing_stage, processing_run):
    if not processing_stage or not processing_run:
        return
    for field in [
        "total_count",
        "processed_count",
        "success_count",
        "failed_count",
        "review_count",
        "dispatch_count",
        "archive_count",
        "skipped_count",
        "cancelled_count",
    ]:
        setattr(processing_stage, field, getattr(processing_run, field))
    processing_stage.save(
        update_fields=[
            "total_count",
            "processed_count",
            "success_count",
            "failed_count",
            "review_count",
            "dispatch_count",
            "archive_count",
            "skipped_count",
            "cancelled_count",
        ]
    )


def run(scope=None, mode="rule", processing_run=None, processing_stage=None):
    scope = scope or {}
    rules = school_admission.active_rules()

    cancelled = 0
    created = 0
    scoped_reprocess = _is_scoped_reprocess(scope)
    archived_before = m.CandidateWorkflow.objects.filter(
        status=m.CandidateWorkflow.STATUS_ARCHIVED
    ).count()

    candidate_ids = list(candidate_ids_for_scope(scope))
    if processing_run:
        processing_run.total_count = len(candidate_ids)
        processing_run.processed_count = 0
        processing_run.success_count = 0
        processing_run.failed_count = 0
        processing_run.review_count = 0
        processing_run.dispatch_count = 0
        processing_run.archive_count = 0
        processing_run.skipped_count = 0
        processing_run.cancelled_count = 0
        processing_run.save(
            update_fields=[
                "total_count", "processed_count", "success_count", "failed_count",
                "review_count", "dispatch_count", "archive_count", "skipped_count",
                "cancelled_count",
            ]
        )
        _sync_stage_progress(processing_stage, processing_run)
    candidates = list(m.Candidate.objects.filter(id__in=candidate_ids).order_by("id"))
    classify_school.classify_candidates(candidates, overwrite=False)
    scope_items = (
        {
            item.candidate_id: item
            for item in processing_run.scope_items.all()
        }
        if processing_run
        else {}
    )

    for candidate_id in candidate_ids:
        raise_if_cancel_requested(processing_run)
        # 同一候选人的自动处理必须串行：持有 Candidate 行锁直到该人的流程、
        # 尝试和 AI 决策全部落库，避免两个 HR 的后台任务互相取消或重复建尝试。
        with transaction.atomic():
            candidate = m.Candidate.objects.select_for_update().get(pk=candidate_id)
            workflow, workflow_created = m.CandidateWorkflow.objects.select_for_update().get_or_create(candidate=candidate)
            scope_item = scope_items.get(candidate_id)
            if scope_item:
                expected_revision = scope_item.workflow_revision_at_submit
                changed_after_submit = (
                    (expected_revision is None and not workflow_created)
                    or (
                        expected_revision is not None
                        and workflow.revision != expected_revision
                    )
                )
                if changed_after_submit:
                    scope_item.status = "skipped_manual_change"
                    scope_item.skip_reason = "workflow_changed_after_submit"
                    scope_item.finished_at = timezone.now()
                    scope_item.save(update_fields=["status", "skip_reason", "finished_at"])
                    if processing_run:
                        processing_run.processed_count += 1
                        processing_run.skipped_count += 1
                        processing_run.last_heartbeat_at = timezone.now()
                        processing_run.save(
                            update_fields=["processed_count", "skipped_count", "last_heartbeat_at"]
                        )
                        _sync_stage_progress(processing_stage, processing_run)
                    continue
            if not scoped_reprocess and workflow.status in [
            m.CandidateWorkflow.STATUS_PASSED,
            m.CandidateWorkflow.STATUS_ARCHIVED,
            ]:
                if processing_run:
                    processing_run.processed_count += 1
                    processing_run.success_count += 1
                    processing_run.last_heartbeat_at = timezone.now()
                    processing_run.save(update_fields=["processed_count", "success_count", "last_heartbeat_at"])
                    _sync_stage_progress(processing_stage, processing_run)
                if scope_item:
                    scope_item.status = "success"
                    scope_item.skip_reason = ""
                    scope_item.save(update_fields=["status", "skip_reason"])
                continue
            if scoped_reprocess:
                _reopen_workflow(workflow, mode)
            cancelled += _cancel_unfeedbacked_attempts(
                workflow,
                m.AssignmentAttempt.CANCEL_RERUN,
                sources=[
                    m.AssignmentAttempt.SOURCE_AI,
                    m.AssignmentAttempt.SOURCE_RULE,
                ]
                if scoped_reprocess
                else None,
                source=(
                    None
                    if scoped_reprocess
                    else m.AssignmentAttempt.SOURCE_AI
                    if mode == "ai"
                    else m.AssignmentAttempt.SOURCE_RULE
                ),
            )
            workflow.current_rank = None
            workflow.current_resume = None
            workflow.dispatch_strategy = mode
            _clear_block(workflow)
            workflow.save(
                update_fields=[
                    "current_rank",
                    "current_resume",
                    "dispatch_strategy",
                    "block_reason",
                    "block_detail",
                    "updated_at",
                ]
            )
            if _create_next_auto_attempt(
                workflow,
                rules,
                mode=mode,
                processing_run=processing_run,
                force_ai=_should_force_ai(scope),
                retry_resume_id=scope.get("retry_resume_id"),
            ):
                created += 1

            if processing_run:
                has_failure = m.AgentDispatchDecision.objects.filter(
                    processing_run=processing_run,
                    workflow=workflow,
                ).exclude(error_code="").exists()
                processing_run.processed_count += 1
                if has_failure:
                    processing_run.failed_count += 1
                else:
                    processing_run.success_count += 1
                latest_decision = m.AgentDispatchDecision.objects.filter(
                    processing_run=processing_run, workflow=workflow
                ).order_by("-created_at", "-id").first()
                if latest_decision:
                    if latest_decision.recommendation == m.AgentDispatchDecision.RECOMMEND_REVIEW:
                        processing_run.review_count += 1
                    elif latest_decision.recommendation == m.AgentDispatchDecision.RECOMMEND_DISPATCH:
                        processing_run.dispatch_count += 1
                    elif latest_decision.recommendation == m.AgentDispatchDecision.RECOMMEND_ARCHIVE:
                        processing_run.archive_count += 1
                processing_run.last_heartbeat_at = timezone.now()
                processing_run.save(
                    update_fields=[
                        "processed_count", "success_count", "failed_count",
                        "review_count", "dispatch_count", "archive_count", "last_heartbeat_at",
                    ]
                )
                _sync_stage_progress(processing_stage, processing_run)

            if scope_item:
                scope_item.status = "success"
                scope_item.skip_reason = ""
                scope_item.save(update_fields=["status", "skip_reason"])

    return (
        f"已生成 {created} 条候选人分配尝试，取消 {cancelled} 条未反馈自动尝试，"
        f"保留 {archived_before} 个已归档流程（策略：{mode}）"
    )


def _manual_target(contact, secondary_contact=None):
    if contact.contact_level == m.Contact.LEVEL_SECONDARY:
        if not contact.department or contact.department.level != 2:
            raise ValueError("二级接口人必须绑定二级部门")
        return contact, None
    if contact.contact_level == m.Contact.LEVEL_TERTIARY:
        if not contact.department or contact.department.level != 3 or not contact.department.parent:
            raise ValueError("三级接口人必须绑定三级部门")
        candidates = list(
            m.Contact.objects.filter(
                department=contact.department.parent,
                contact_level=m.Contact.LEVEL_SECONDARY,
                is_active=True,
            ).order_by("id")
        )
        if not candidates:
            raise ValueError("三级接口人所属二级部门没有可用二级接口人")
        if len(candidates) == 1:
            secondary_contact = candidates[0]
        elif not secondary_contact:
            raise ValueError("该三级部门存在多个二级接口人，请明确 secondary_contact_id")
        elif secondary_contact.id not in {item.id for item in candidates}:
            raise ValueError("指定二级接口人不属于三级接口人的上级二级部门")
        return secondary_contact, contact
    raise ValueError("目标接口人层级无效")


def _force_assign_locked(
    *,
    workflow,
    resume,
    contact,
    secondary_contact=None,
    source,
    mode,
    match_reason,
    manual_reason="",
    created_by=None,
    agent_decision=None,
    confidence_score=None,
    route_code="",
    special_route_confidence=None,
    special_route_evidence=None,
    special_route_config_snapshot=None,
    invalidate_processing=True,
    capacity_reservation=None,
):
    """人工接口与 AI 专项分流共用的强制分配核心；调用方必须锁定 workflow。"""
    if invalidate_processing:
        _invalidate_active_processing(workflow)
    if workflow.status == m.CandidateWorkflow.STATUS_PASSED:
        raise ValueError("已通过候选人不可再强制分配")
    if not contact.is_active:
        raise ValueError("目标接口人未启用")
    secondary_contact, sub_contact = _manual_target(contact, secondary_contact)
    _cancel_unfeedbacked_attempts(workflow, m.AssignmentAttempt.CANCEL_MANUAL_REPLACED)
    return _create_attempt(
        workflow=workflow,
        resume=resume,
        contact=secondary_contact,
        sub_contact=sub_contact,
        source=source,
        mode=mode,
        match_reason=match_reason,
        manual_reason=manual_reason,
        created_by=created_by,
        agent_decision=agent_decision,
        confidence_score=confidence_score,
        route_code=route_code,
        special_route_confidence=special_route_confidence,
        special_route_evidence=special_route_evidence,
        special_route_config_snapshot=special_route_config_snapshot,
        capacity_reservation=capacity_reservation,
    )


def _invalidate_active_processing(workflow):
    """人工流程优先：清除自动处理令牌，使在途 AI 结果无法提交。"""
    m.CandidateWorkflow.objects.filter(pk=workflow.pk).update(
        active_processing_scope_item=None,
        active_processing_token=None,
        active_processing_expires_at=None,
    )
    workflow.active_processing_scope_item_id = None
    workflow.active_processing_token = None
    workflow.active_processing_expires_at = None


def _lock_attempt_for_manual_write(attempt):
    locked_attempt = (
        m.AssignmentAttempt.objects.select_for_update()
        .select_related("workflow")
        .get(pk=attempt.pk)
    )
    workflow = m.CandidateWorkflow.objects.select_for_update().get(
        pk=locked_attempt.workflow_id
    )
    _invalidate_active_processing(workflow)
    # 即使本次只写 AssignmentAttempt，也推进候选人流程版本，阻止旧 AI 结果提交。
    workflow.save(update_fields=["updated_at"])
    locked_attempt.workflow = workflow
    return locked_attempt, workflow


@transaction.atomic
def manual_assign(
    resume,
    contact,
    user=None,
    manual_reason="",
    secondary_contact=None,
):
    candidate = m.Candidate.objects.select_for_update().get(pk=resume.candidate_id)
    workflow, _ = m.CandidateWorkflow.objects.select_for_update().get_or_create(
        candidate=candidate
    )
    return _force_assign_locked(
        workflow=workflow,
        resume=resume,
        contact=contact,
        secondary_contact=secondary_contact,
        source=m.AssignmentAttempt.SOURCE_MANUAL,
        mode="manual",
        match_reason="HR 手动强制分配",
        manual_reason=manual_reason,
        created_by=user,
    )


@transaction.atomic
def dispatch_attempt(attempt, user=None):
    attempt, _workflow = _lock_attempt_for_manual_write(attempt)
    if attempt.status != m.AssignmentAttempt.STATUS_PENDING_DISPATCH:
        raise ValueError("仅待下发尝试可以下发")
    attempt.status = m.AssignmentAttempt.STATUS_DISPATCHED_L2
    attempt.dispatched_at = timezone.now()
    _set_snapshots(attempt)
    attempt.save(
        update_fields=[
            "status",
            "dispatched_at",
            "department_name_snapshot",
            "contact_name_snapshot",
            "contact_employee_no_snapshot",
            "created_by_username_snapshot",
            "updated_at",
        ]
    )
    _create_handoff(
        attempt=attempt,
        action=m.AssignmentHandoff.ACTION_HR_DISPATCH,
        to_contact=attempt.contact,
        to_department=attempt.department,
        created_by=user,
    )
    return attempt


@transaction.atomic
def assign_sub_contact(attempt, sub_contact, operator_contact=None, user=None, note=""):
    attempt, _workflow = _lock_attempt_for_manual_write(attempt)
    if attempt.status not in [
        m.AssignmentAttempt.STATUS_DISPATCHED_L2,
        m.AssignmentAttempt.STATUS_ASSIGNED_L3,
    ]:
        raise ValueError("仅已下发二级的尝试可以转派三级接口人")
    if not attempt.department:
        raise ValueError("分配尝试缺少二级部门")
    if operator_contact and operator_contact.id != attempt.contact_id:
        raise ValueError("只能转派下发给自己的分配尝试")
    if attempt.contact and not attempt.contact.can_delegate:
        raise ValueError("当前二级接口人没有转派权限")

    _assert_tertiary_contact(sub_contact, attempt.department)
    old_sub_contact = attempt.sub_contact
    attempt.sub_contact = sub_contact
    attempt.sub_department = sub_contact.department
    attempt.status = m.AssignmentAttempt.STATUS_ASSIGNED_L3
    attempt.assigned_to_sub_at = timezone.now()
    _set_snapshots(attempt)
    attempt.save(
        update_fields=[
            "sub_contact",
            "sub_department",
            "status",
            "assigned_to_sub_at",
            "sub_department_name_snapshot",
            "sub_contact_name_snapshot",
            "sub_contact_employee_no_snapshot",
            "created_by_username_snapshot",
            "updated_at",
        ]
    )
    _create_handoff(
        attempt=attempt,
        action=(
            m.AssignmentHandoff.ACTION_SUB_REASSIGN
            if old_sub_contact
            else m.AssignmentHandoff.ACTION_SUB_ASSIGN
        ),
        from_contact=attempt.contact,
        to_contact=sub_contact,
        to_department=sub_contact.department,
        created_by=user,
        note=note,
    )
    return attempt


@transaction.atomic
def submit_feedback(attempt, result, note="", *, user=None):
    attempt, workflow = _lock_attempt_for_manual_write(attempt)
    if attempt.feedback_at:
        raise ValueError("反馈已提交，不允许重复修改")
    allowed_statuses = {
        m.AssignmentAttempt.STATUS_DISPATCHED_L2,
        m.AssignmentAttempt.STATUS_ASSIGNED_L3,
    }
    if attempt.status not in allowed_statuses:
        raise ValueError("仅已下发且未转派的二级尝试或已转派三级尝试可以反馈")
    if user is not None:
        from apps.accounts.permissions import user_permission_codes

        permissions = user_permission_codes(user)
        contact_id = getattr(user, "contact_id", None)
        if "attempt.feedback" not in permissions:
            raise ValueError("当前用户没有提交反馈权限")
        is_bound_secondary = (
            attempt.status == m.AssignmentAttempt.STATUS_DISPATCHED_L2
            and "attempt.view_received" in permissions
            and contact_id
            and attempt.contact_id == contact_id
        )
        is_bound_tertiary = (
            attempt.status == m.AssignmentAttempt.STATUS_ASSIGNED_L3
            and "attempt.view_assigned" in permissions
            and contact_id
            and attempt.sub_contact_id == contact_id
        )
        if not (is_bound_secondary or is_bound_tertiary):
            raise ValueError("当前用户不是该阶段绑定的反馈接口人")
    if result not in [
        m.AssignmentAttempt.FEEDBACK_PASSED,
        m.AssignmentAttempt.FEEDBACK_REJECTED,
    ]:
        raise ValueError("反馈结果必须是 passed 或 rejected")

    now = timezone.now()
    attempt.feedback_result = result
    attempt.feedback_note = note
    attempt.feedback_at = now

    if result == m.AssignmentAttempt.FEEDBACK_PASSED:
        attempt.status = m.AssignmentAttempt.STATUS_PASSED
        attempt.save(
            update_fields=[
                "status",
                "feedback_result",
                "feedback_note",
                "feedback_at",
                "updated_at",
            ]
        )
        workflow.status = m.CandidateWorkflow.STATUS_PASSED
        workflow.passed_attempt = attempt
        _clear_block(workflow)
        workflow.completed_at = now
        workflow.save(
            update_fields=[
                "status",
                "passed_attempt",
                "block_reason",
                "block_detail",
                "completed_at",
                "updated_at",
            ]
        )
        _cancel_unfeedbacked_attempts(
            workflow, m.AssignmentAttempt.CANCEL_WORKFLOW_PASSED
        )
        return attempt

    attempt.status = m.AssignmentAttempt.STATUS_REJECTED
    attempt.save(
        update_fields=[
            "status",
            "feedback_result",
            "feedback_note",
            "feedback_at",
            "updated_at",
        ]
    )
    rules = school_admission.active_rules()
    origin_run = (
        attempt.capacity_reservation.run
        if attempt.capacity_reservation_id
        else None
    )
    created = _create_next_auto_attempt(
        workflow,
        rules,
        mode=workflow.dispatch_strategy or attempt.match_mode or "rule",
        processing_run=origin_run,
        advance_after_feedback=True,
    )
    if not created and workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME:
        workflow.archive_reason = m.CandidateWorkflow.ARCHIVE_ALL_REJECTED
        workflow.archive_detail = "全部可尝试志愿均已反馈未通过"
        workflow.save(update_fields=["archive_reason", "archive_detail", "updated_at"])
    return attempt


@transaction.atomic
def confirm_review(attempt):
    attempt, _workflow = _lock_attempt_for_manual_write(attempt)
    if attempt.status != m.AssignmentAttempt.STATUS_PENDING_REVIEW:
        raise ValueError("仅待 HR 复核的 AI 尝试可以确认下发")
    attempt.status = m.AssignmentAttempt.STATUS_PENDING_DISPATCH
    attempt.review_required = False
    attempt.save(update_fields=["status", "review_required", "updated_at"])
    return attempt


@transaction.atomic
def cancel_attempt(attempt, reason="hr_cancelled"):
    attempt, workflow = _lock_attempt_for_manual_write(attempt)
    if attempt.status not in [
        m.AssignmentAttempt.STATUS_PENDING_REVIEW,
        m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
    ]:
        raise ValueError("仅待复核或待下发尝试可以取消")
    now = timezone.now()
    _release_attempt_capacity(attempt, released_at=now)
    attempt.status = m.AssignmentAttempt.STATUS_CANCELLED
    attempt.cancelled_at = now
    attempt.cancel_reason = reason
    attempt.save(
        update_fields=[
            "status",
            "cancelled_at",
            "cancel_reason",
            "capacity_released_at",
            "updated_at",
        ]
    )
    if not workflow.attempts.filter(status__in=UNFEEDBACKED_STATUSES).exists():
        _archive(
            workflow,
            (
                m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION
                if attempt.source == m.AssignmentAttempt.SOURCE_AI
                else m.CandidateWorkflow.ARCHIVE_HR_CANCELLED
            ),
            (
                "HR 已取消 AI 复核/下发建议，可重试 AI、切换 Rule 或手动分配"
                if attempt.source == m.AssignmentAttempt.SOURCE_AI
                else "HR 已取消当前待下发尝试，可重新处理或手动分配"
            ),
        )
    return attempt


@transaction.atomic
def retry_agent_decision(decision):
    validate_agent_decision_retry(decision)

    workflow = decision.workflow
    workflow._processing_run = decision.processing_run
    resume = decision.resume
    _cancel_unfeedbacked_attempts(
        workflow,
        m.AssignmentAttempt.CANCEL_RERUN,
        source=m.AssignmentAttempt.SOURCE_AI,
    )
    rules = school_admission.active_rules()
    admission = school_admission.evaluate(resume.candidate, rules)
    if not admission.passed:
        new_decision = _create_agent_failure_decision(
            workflow,
            resume,
            error_code="guardrail_blocked",
            error_message=admission.failure_detail,
        )
        return new_decision, None

    job, prerequisite_code, prerequisite_detail = _ai_current_volunteer_prerequisite(
        resume
    )
    if prerequisite_detail:
        new_decision = _create_agent_failure_decision(
            workflow,
            resume,
            error_code=prerequisite_code,
            error_message=f"AI 重试时{prerequisite_detail}",
        )
        return new_decision, None

    attempt = _process_ai_recommendation(
        workflow,
        resume,
        matched_rule=admission.matched_rule,
        job=job,
        force=True,
    )
    new_decision = (
        attempt.agent_decision
        if attempt
        else workflow.agent_decisions.order_by("-created_at", "-id").first()
    )
    return new_decision, attempt
