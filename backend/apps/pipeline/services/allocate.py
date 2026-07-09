"""Step2 候选人级简历分类、分配与下发工作流。"""
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core import models as m
from apps.core import system_status
from apps.pipeline import ai_config

from ..strategies import get_strategy
from . import school_admission


UNFEEDBACKED_STATUSES = [
    m.AssignmentAttempt.STATUS_PENDING_REVIEW,
    m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
    m.AssignmentAttempt.STATUS_DISPATCHED_L2,
    m.AssignmentAttempt.STATUS_ASSIGNED_L3,
]


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
    now = timezone.now()
    return qs.update(
        status=m.AssignmentAttempt.STATUS_CANCELLED,
        cancelled_at=now,
        cancel_reason=reason,
        updated_at=now,
    )


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


def _is_scoped_reprocess(scope):
    return bool(system_status.normalize_statuses((scope or {}).get("system_statuses")))


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


def _secondary_department(department):
    if not department:
        return None
    if department.level == 2:
        return department
    if department.level == 3:
        return department.parent
    return None


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
        dispatched_at=now if sub_contact else None,
        assigned_to_sub_at=now if sub_contact else None,
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
    )
    _set_snapshots(attempt)
    attempt.save()

    if sub_contact:
        _create_handoff(
            attempt=attempt,
            action=m.AssignmentHandoff.ACTION_HR_DISPATCH,
            to_contact=contact,
            to_department=attempt.department,
            created_by=created_by,
            note="HR 手动直达三级接口人",
        )
        _create_handoff(
            attempt=attempt,
            action=m.AssignmentHandoff.ACTION_SUB_ASSIGN,
            from_contact=contact,
            to_contact=sub_contact,
            to_department=sub_department,
            created_by=created_by,
            note="HR 手动直达三级接口人",
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


def _ensure_resume_profile(resume):
    profile, _ = m.ResumeProfile.objects.get_or_create(resume=resume)
    profile.parsed_text = "\n".join(
        part
        for part in [
            resume.position_name,
            resume.candidate.highest_major,
            resume.candidate.first_degree_school,
            resume.candidate.highest_degree_school,
        ]
        if part
    )
    profile.major_direction = resume.candidate.highest_major
    profile.parse_status = "parsed_demo"
    profile.parse_error = ""
    profile.parsed_at = timezone.now()
    profile.save(
        update_fields=[
            "parsed_text",
            "major_direction",
            "parse_status",
            "parse_error",
            "parsed_at",
            "updated_at",
        ]
    )
    return profile


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


def _create_agent_decision(workflow, resume, profile, job, contact, reason):
    runtime_config = ai_config.get_ai_runtime_config()
    model_config = ai_config.get_ai_model_config()
    confidence = 0.78 if job and contact else 0.35
    if confidence >= runtime_config.dispatch_threshold:
        recommendation = m.AgentDispatchDecision.RECOMMEND_DISPATCH
    elif confidence >= runtime_config.review_threshold:
        recommendation = m.AgentDispatchDecision.RECOMMEND_REVIEW
    else:
        recommendation = m.AgentDispatchDecision.RECOMMEND_ARCHIVE
    risks = [] if recommendation == m.AgentDispatchDecision.RECOMMEND_DISPATCH else ["岗位或接口人匹配不足"]
    return m.AgentDispatchDecision.objects.create(
        workflow=workflow,
        resume=resume,
        profile=profile,
        processing_run=getattr(workflow, "_processing_run", None),
        recommendation=recommendation,
        evaluated_job=job,
        recommended_job=job,
        matched_job_category=job.category if job else "",
        recommended_department=contact.department if contact else None,
        recommended_contact=contact,
        recommended_contact_name_snapshot=contact.name if contact else "",
        recommended_contact_employee_no_snapshot=(
            contact.employee_no if contact else ""
        ),
        confidence_score=confidence,
        score_breakdown={
            "major_match": 0.75 if resume.candidate.highest_major else 0.45,
            "job_requirement": 0.8 if job else 0.2,
            "department_certainty": 0.8 if contact else 0.2,
            "resume_quality": 0.6 if profile.parsed_text else 0.3,
        },
        summary="AI(demo) 生成候选人当前志愿分流建议",
        reason=reason or "AI(demo)：基于岗位名称、专业方向与需求表生成分流建议",
        evidence=[
            item
            for item in [
                f"投递岗位：{resume.position_name}" if resume.position_name else "",
                f"最高学历专业：{resume.candidate.highest_major}" if resume.candidate.highest_major else "",
            ]
            if item
        ],
        risks=risks,
        risk_flags=risks,
        model_name=model_config.model_name,
        prompt_version=model_config.prompt_version,
        decision_version=model_config.decision_version,
    )


def _create_agent_failure_decision(
    workflow,
    resume,
    *,
    error_code,
    error_message,
    profile=None,
):
    model_config = ai_config.get_ai_model_config()
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
        model_name=model_config.model_name,
        prompt_version=model_config.prompt_version,
        decision_version=model_config.decision_version,
    )


def _process_ai_recommendation(
    workflow,
    resume,
    *,
    matched_rule,
    job,
    contact,
    classify_reason="",
):
    _touch_workflow(workflow, resume, "ai")
    if not resume.resume_file:
        _create_agent_failure_decision(
            workflow,
            resume,
            error_code="pdf_missing",
            error_message="缺少 PDF 简历文件，AI 无法读取简历正文",
        )
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
            "AI 缺少 PDF 简历文件，建议归档或人工处理",
        )
        return None

    profile = _ensure_resume_profile(resume)
    decision = _create_agent_decision(
        workflow, resume, profile, job, contact, classify_reason
    )
    if decision.recommendation == m.AgentDispatchDecision.RECOMMEND_ARCHIVE:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
            "AI(demo) 低于复核置信度，建议归档或人工处理",
        )
        return None
    if decision.recommendation == m.AgentDispatchDecision.RECOMMEND_REVIEW:
        return _create_attempt(
            workflow=workflow,
            resume=resume,
            contact=contact,
            source=m.AssignmentAttempt.SOURCE_AI,
            mode="ai",
            matched_rule=matched_rule,
            agent_decision=decision,
            confidence_score=decision.confidence_score,
            match_reason=decision.reason,
            review_required=True,
            status=m.AssignmentAttempt.STATUS_PENDING_REVIEW,
        )
    return _create_attempt(
        workflow=workflow,
        resume=resume,
        contact=contact,
        source=m.AssignmentAttempt.SOURCE_AI,
        mode="ai",
        matched_rule=matched_rule,
        agent_decision=decision,
        confidence_score=decision.confidence_score,
        match_reason=decision.reason,
    )


def _create_next_auto_attempt(workflow, rules, mode="rule", processing_run=None):
    """为候选人创建下一条自动分配尝试。

    这是 Rule/AI 共用的自动分配入口。共同硬规则先于策略执行：
    1. 院校准入不通过则直接归档，不进入岗位/专业匹配。
    2. 按当前 workflow.current_rank 后续志愿顺序逐条尝试。
    3. 当前志愿必须能匹配岗位、二级部门和启用的二级接口人，才生成尝试。

    AI 目前仍复用同一条硬规则链路；本轮只加固 Rule 策略，不扩展 AI 能力。
    """
    workflow._processing_run = processing_run
    candidate = workflow.candidate
    admission = school_admission.evaluate(candidate, rules)
    if not admission.passed:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_SCHOOL_RULE_NOT_MATCHED,
            "候选人第一学历标签和最高学历标签未命中任何启用规则",
        )
        return None

    strategy = get_strategy(mode)
    jobs = list(
        m.Job.objects.select_related("department")
        .prefetch_related("majors")
        .filter(is_active=True)
    )
    had_resume = False
    # 下面三个 gap 标记用于在所有后续志愿都失败时给出更接近真实原因的归档说明。
    saw_job_gap = False
    saw_department_gap = False
    saw_contact_gap = False
    after_rank = workflow.current_rank if workflow.current_rank else None
    for resume in _candidate_resumes(candidate, after_rank=after_rank):
        had_resume = True
        _touch_workflow(workflow, resume, mode)
        # strategy.classify 内部负责 Rule/AI 的岗位选择口径；Rule 会校验主体、
        # 岗位名优先级和需求专业，AI 当前仍是 demo 占位策略。
        job, _category, classify_reason = _classify_resume(resume, strategy, jobs, mode)
        if not job:
            saw_job_gap = True
            continue
        department = _secondary_department(job.department)
        if not department:
            saw_department_gap = True
            continue
        contact = _first_secondary_contact(department)
        if not contact:
            # 岗位与二级部门已经明确命中时，缺二级接口人属于数据维护阻塞，
            # 不能跳过当前志愿尝试下一志愿，否则会破坏候选人的志愿优先级。
            _block_current_volunteer(
                workflow,
                m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND,
                f"当前第{resume.volunteer_rank}志愿已匹配二级部门{department.name}，但没有启用的二级接口人",
            )
            saw_contact_gap = True
            return None

        # AI 分支保留既有接口和状态机，避免 Rule 加固时改变 AI 的失败边界。
        if mode == "ai":
            return _process_ai_recommendation(
                workflow,
                resume,
                matched_rule=admission.matched_rule,
                job=job,
                contact=contact,
                classify_reason=classify_reason,
            )

        return _create_attempt(
            workflow=workflow,
            resume=resume,
            contact=contact,
            source=m.AssignmentAttempt.SOURCE_RULE,
            mode=mode,
            matched_rule=admission.matched_rule,
            match_reason=_rule_match_reason(
                admission, resume, job, contact, classify_reason
            ),
        )

    if not had_resume:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME,
            "没有下一条可尝试志愿",
        )
    elif saw_job_gap:
        _archive(workflow, m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED, "后续志愿未匹配岗位")
    elif saw_department_gap:
        _archive(workflow, m.CandidateWorkflow.ARCHIVE_DEPARTMENT_NOT_FOUND, "后续志愿未找到二级部门")
    elif saw_contact_gap:
        _archive(workflow, m.CandidateWorkflow.ARCHIVE_CONTACT_NOT_FOUND, "后续志愿未找到可用二级接口人")
    else:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME,
            "没有下一条可尝试志愿",
        )
    return None


@transaction.atomic
def run(scope=None, mode="rule", processing_run=None):
    scope = scope or {}
    rules = school_admission.active_rules()

    cancelled = 0
    created = 0
    scoped_reprocess = _is_scoped_reprocess(scope)
    archived_before = m.CandidateWorkflow.objects.filter(
        status=m.CandidateWorkflow.STATUS_ARCHIVED
    ).count()

    for candidate in _candidate_queryset(scope):
        workflow, _ = m.CandidateWorkflow.objects.get_or_create(candidate=candidate)
        if not scoped_reprocess and workflow.status in [
            m.CandidateWorkflow.STATUS_PASSED,
            m.CandidateWorkflow.STATUS_ARCHIVED,
        ]:
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
            source=None
            if scoped_reprocess
            else (
                m.AssignmentAttempt.SOURCE_AI
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
            workflow, rules, mode=mode, processing_run=processing_run
        ):
            created += 1

    return (
        f"已生成 {created} 条候选人分配尝试，取消 {cancelled} 条未反馈自动尝试，"
        f"保留 {archived_before} 个已归档流程（策略：{mode}）"
    )


def _manual_target(contact):
    if contact.contact_level == m.Contact.LEVEL_SECONDARY:
        if not contact.department or contact.department.level != 2:
            raise ValueError("二级接口人必须绑定二级部门")
        return contact, None
    if contact.contact_level == m.Contact.LEVEL_TERTIARY:
        if not contact.department or contact.department.level != 3 or not contact.department.parent:
            raise ValueError("三级接口人必须绑定三级部门")
        secondary_contact = _first_secondary_contact(contact.department.parent)
        if not secondary_contact:
            raise ValueError("三级接口人所属二级部门没有可用二级接口人")
        return secondary_contact, contact
    raise ValueError("目标接口人层级无效")


@transaction.atomic
def manual_assign(resume, contact, user=None, manual_reason=""):
    workflow, _ = m.CandidateWorkflow.objects.get_or_create(candidate=resume.candidate)
    if workflow.status == m.CandidateWorkflow.STATUS_PASSED:
        raise ValueError("已通过候选人不可再强制分配")
    if not contact.is_active:
        raise ValueError("目标接口人未启用")

    secondary_contact, sub_contact = _manual_target(contact)
    _cancel_unfeedbacked_attempts(workflow, m.AssignmentAttempt.CANCEL_MANUAL_REPLACED)
    return _create_attempt(
        workflow=workflow,
        resume=resume,
        contact=secondary_contact,
        sub_contact=sub_contact,
        source=m.AssignmentAttempt.SOURCE_MANUAL,
        mode="manual",
        match_reason="HR 手动强制分配",
        manual_reason=manual_reason,
        created_by=user,
    )


@transaction.atomic
def dispatch_attempt(attempt, user=None):
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
def submit_feedback(attempt, result, note=""):
    if attempt.feedback_at:
        raise ValueError("反馈已提交，不允许重复修改")
    if attempt.status != m.AssignmentAttempt.STATUS_ASSIGNED_L3:
        raise ValueError("仅已转派三级的尝试可以反馈")
    if result not in [
        m.AssignmentAttempt.FEEDBACK_PASSED,
        m.AssignmentAttempt.FEEDBACK_REJECTED,
    ]:
        raise ValueError("反馈结果必须是 passed 或 rejected")

    now = timezone.now()
    attempt.feedback_result = result
    attempt.feedback_note = note
    attempt.feedback_at = now

    workflow = attempt.workflow
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
    created = _create_next_auto_attempt(
        workflow, rules, mode=workflow.dispatch_strategy or attempt.match_mode or "rule"
    )
    if not created and workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME:
        workflow.archive_reason = m.CandidateWorkflow.ARCHIVE_ALL_REJECTED
        workflow.archive_detail = "全部可尝试志愿均已反馈未通过"
        workflow.save(update_fields=["archive_reason", "archive_detail", "updated_at"])
    return attempt


@transaction.atomic
def confirm_review(attempt):
    if attempt.status != m.AssignmentAttempt.STATUS_PENDING_REVIEW:
        raise ValueError("仅待 HR 复核的 AI 尝试可以确认下发")
    attempt.status = m.AssignmentAttempt.STATUS_PENDING_DISPATCH
    attempt.review_required = False
    attempt.save(update_fields=["status", "review_required", "updated_at"])
    return attempt


@transaction.atomic
def retry_agent_decision(decision):
    if not _retry_allowed(decision):
        raise ValueError("仅失败、建议归档或低于自动下发阈值的 AI 决策可以重试")

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
            error_message="候选人第一学历标签和最高学历标签未命中任何启用规则",
        )
        return new_decision, None

    strategy = get_strategy("ai")
    jobs = list(
        m.Job.objects.select_related("department")
        .prefetch_related("majors")
        .filter(is_active=True)
    )
    job, _category, classify_reason = _classify_resume(resume, strategy, jobs, "ai")
    if not job:
        new_decision = _create_agent_failure_decision(
            workflow,
            resume,
            error_code="reference_not_found",
            error_message="AI 重试时未找到可匹配岗位",
        )
        return new_decision, None
    department = _secondary_department(job.department)
    if not department:
        new_decision = _create_agent_failure_decision(
            workflow,
            resume,
            error_code="reference_not_found",
            error_message="AI 重试时未找到可用二级部门",
        )
        return new_decision, None
    contact = _first_secondary_contact(department)
    if not contact:
        new_decision = _create_agent_failure_decision(
            workflow,
            resume,
            error_code="reference_not_found",
            error_message="AI 重试时未找到可用二级接口人",
        )
        return new_decision, None

    attempt = _process_ai_recommendation(
        workflow,
        resume,
        matched_rule=admission.matched_rule,
        job=job,
        contact=contact,
        classify_reason=classify_reason,
    )
    new_decision = (
        attempt.agent_decision
        if attempt
        else workflow.agent_decisions.order_by("-created_at", "-id").first()
    )
    return new_decision, attempt
