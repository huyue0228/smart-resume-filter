"""Step2 候选人级简历分类、分配与下发工作流。"""
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core import models as m

from ..strategies import get_strategy


UNFEEDBACKED_STATUSES = [
    m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
    m.AssignmentAttempt.STATUS_DISPATCHED_L2,
    m.AssignmentAttempt.STATUS_ASSIGNED_L3,
]


def _active_rules():
    return list(m.SchoolTagRule.objects.filter(is_active=True).order_by("priority", "id"))


def _matches_rule(candidate, rule):
    return (
        candidate.first_degree_platform in (rule.first_degree_tags or [])
        and candidate.highest_degree_platform in (rule.highest_degree_tags or [])
    )


def _matched_rule(candidate, rules):
    for rule in rules:
        if _matches_rule(candidate, rule):
            return rule
    return None


def _archive(workflow, reason, detail):
    workflow.status = m.CandidateWorkflow.STATUS_ARCHIVED
    workflow.archive_reason = reason
    workflow.archive_detail = detail
    workflow.completed_at = timezone.now()
    workflow.save(
        update_fields=[
            "status",
            "archive_reason",
            "archive_detail",
            "completed_at",
            "updated_at",
        ]
    )


def _cancel_unfeedbacked_attempts(workflow, reason, source=None):
    qs = workflow.attempts.filter(status__in=UNFEEDBACKED_STATUSES)
    if source:
        qs = qs.filter(source=source)
    now = timezone.now()
    return qs.update(
        status=m.AssignmentAttempt.STATUS_CANCELLED,
        cancelled_at=now,
        cancel_reason=reason,
        updated_at=now,
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
    return m.AssignmentHandoff.objects.create(
        attempt=attempt,
        action=action,
        from_contact=from_contact,
        to_department=to_department or to_contact.department,
        to_contact=to_contact,
        note=note,
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
    )


def _touch_workflow(workflow, resume, mode):
    workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
    workflow.current_resume = resume
    workflow.current_rank = resume.volunteer_rank
    workflow.dispatch_strategy = mode
    workflow.archive_reason = ""
    workflow.archive_detail = ""
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
):
    now = timezone.now()
    sub_department = sub_contact.department if sub_contact else None
    attempt = m.AssignmentAttempt(
        workflow=workflow,
        resume=resume,
        attempt_no=_next_attempt_no(workflow),
        source=source,
        status=(
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
    qs = candidate.resumes.filter(volunteer_rank__isnull=False).select_related(
        "job__department"
    ).order_by("volunteer_rank", "apply_date", "id")
    if after_rank is not None:
        qs = qs.filter(volunteer_rank__gt=after_rank)
    return qs


def _classify_resume(resume, strategy, jobs, mode):
    job, category, reason = strategy.classify(resume, jobs)
    resume.job = job
    resume.job_category = category
    resume.category_mode = mode
    resume.category_reason = reason
    resume.save(
        update_fields=["job", "job_category", "category_mode", "category_reason"]
    )
    return job, category, reason


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


def _create_agent_decision(workflow, resume, profile, job, contact, reason):
    confidence = 0.78 if job and contact else 0.35
    recommendation = (
        m.AgentDispatchDecision.RECOMMEND_DISPATCH
        if confidence >= 0.65
        else m.AgentDispatchDecision.RECOMMEND_REVIEW
    )
    risks = [] if recommendation == m.AgentDispatchDecision.RECOMMEND_DISPATCH else ["岗位或接口人匹配不足"]
    return m.AgentDispatchDecision.objects.create(
        workflow=workflow,
        resume=resume,
        profile=profile,
        recommendation=recommendation,
        recommended_department=contact.department if contact else None,
        recommended_contact=contact,
        confidence_score=confidence,
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
        model_name="demo-agent",
        prompt_version="demo-v1",
    )


def _create_next_auto_attempt(workflow, rules, mode="rule"):
    candidate = workflow.candidate
    matched_rule = _matched_rule(candidate, rules)
    if not matched_rule:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_SCHOOL_RULE_NOT_MATCHED,
            "候选人第一学历标签和最高学历标签未命中任何启用规则",
        )
        return None

    strategy = get_strategy(mode)
    jobs = list(m.Job.objects.select_related("department").all())
    had_resume = False
    saw_job_gap = False
    saw_department_gap = False
    saw_contact_gap = False
    after_rank = workflow.current_rank if workflow.current_rank else None
    for resume in _candidate_resumes(candidate, after_rank=after_rank):
        had_resume = True
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
            saw_contact_gap = True
            continue

        if mode == "ai":
            profile = _ensure_resume_profile(resume)
            decision = _create_agent_decision(
                workflow, resume, profile, job, contact, classify_reason
            )
            if decision.recommendation != m.AgentDispatchDecision.RECOMMEND_DISPATCH:
                _archive(
                    workflow,
                    m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
                    "AI(demo) 未达到自动下发置信度，需要 HR 人工复核",
                )
                return None
            return _create_attempt(
                workflow=workflow,
                resume=resume,
                contact=contact,
                source=m.AssignmentAttempt.SOURCE_AI,
                mode=mode,
                matched_rule=matched_rule,
                agent_decision=decision,
                confidence_score=decision.confidence_score,
                match_reason=decision.reason,
            )

        return _create_attempt(
            workflow=workflow,
            resume=resume,
            contact=contact,
            source=m.AssignmentAttempt.SOURCE_RULE,
            mode=mode,
            matched_rule=matched_rule,
            match_reason=f"命中院校规则：{matched_rule.name}",
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
def run(scope=None, mode="rule"):
    rules = _active_rules()
    if not rules:
        raise ValueError("请先配置并启用院校标签准入规则")

    cancelled = 0
    created = 0
    archived_before = m.CandidateWorkflow.objects.filter(
        status=m.CandidateWorkflow.STATUS_ARCHIVED
    ).count()

    for candidate in m.Candidate.objects.prefetch_related("resumes"):
        workflow, _ = m.CandidateWorkflow.objects.get_or_create(candidate=candidate)
        if workflow.status in [
            m.CandidateWorkflow.STATUS_PASSED,
            m.CandidateWorkflow.STATUS_ARCHIVED,
        ]:
            continue
        cancelled += _cancel_unfeedbacked_attempts(
            workflow,
            m.AssignmentAttempt.CANCEL_RERUN,
            source=(
                m.AssignmentAttempt.SOURCE_AI
                if mode == "ai"
                else m.AssignmentAttempt.SOURCE_RULE
            ),
        )
        workflow.current_rank = None
        workflow.current_resume = None
        workflow.dispatch_strategy = mode
        workflow.save(
            update_fields=[
                "current_rank",
                "current_resume",
                "dispatch_strategy",
                "updated_at",
            ]
        )
        if _create_next_auto_attempt(workflow, rules, mode=mode):
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
        workflow.completed_at = now
        workflow.save(
            update_fields=["status", "passed_attempt", "completed_at", "updated_at"]
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
    rules = _active_rules()
    if not rules:
        _archive(
            workflow,
            m.CandidateWorkflow.ARCHIVE_NO_ACTIVE_SCHOOL_RULE,
            "反馈未通过后续分配时没有启用院校标签准入规则",
        )
        return attempt
    created = _create_next_auto_attempt(
        workflow, rules, mode=workflow.dispatch_strategy or attempt.match_mode or "rule"
    )
    if not created and workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_NO_NEXT_RESUME:
        workflow.archive_reason = m.CandidateWorkflow.ARCHIVE_ALL_REJECTED
        workflow.archive_detail = "全部可尝试志愿均已反馈未通过"
        workflow.save(update_fields=["archive_reason", "archive_detail", "updated_at"])
    return attempt
