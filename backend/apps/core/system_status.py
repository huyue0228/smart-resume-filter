"""Derived system resume status for candidate list and scoped reprocessing."""

from django.db.models import Q

from apps.core import candidate_summary
from apps.core import models as m
from apps.core.name_pinyin import name_to_pinyin


RAW = "raw"
CLASSIFIED = "classified"
ALLOCATED = "allocated"
PENDING_SCREENING = "pending_screening"
SCREENING_PASSED = "screening_passed"
SCREENING_REJECTED = "screening_rejected"

LABELS = {
    RAW: "待处理",
    CLASSIFIED: "已分类",
    ALLOCATED: "已分配",
    PENDING_SCREENING: "待筛选",
    SCREENING_PASSED: "通过",
    SCREENING_REJECTED: "不通过",
}

ACTIVE_ATTEMPT_STATUSES = {
    m.AssignmentAttempt.STATUS_PENDING_REVIEW,
    m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
    m.AssignmentAttempt.STATUS_DISPATCHED_L2,
    m.AssignmentAttempt.STATUS_ASSIGNED_L3,
    m.AssignmentAttempt.STATUS_PASSED,
    m.AssignmentAttempt.STATUS_REJECTED,
}


def normalize_statuses(value):
    if not value:
        return []
    if isinstance(value, str):
        values = value.split(",")
    else:
        values = value
    return [item for item in [str(v).strip() for v in values] if item in LABELS]


def normalize_workflow_statuses(value):
    if not value:
        return []
    if isinstance(value, str):
        values = value.split(",")
    else:
        values = value
    allowed = {choice[0] for choice in m.CandidateWorkflow.STATUS_CHOICES}
    return [item for item in [str(v).strip() for v in values] if item in allowed]


def current_resume(candidate, workflow=None):
    workflow = workflow or _workflow(candidate)
    if workflow and workflow.current_resume_id:
        return workflow.current_resume
    resumes = list(candidate.resumes.all())
    if not resumes:
        return None
    return sorted(
        resumes,
        key=lambda resume: (
            resume.volunteer_rank if resume.volunteer_rank is not None else 999,
            resume.apply_date.toordinal() if resume.apply_date else 0,
            resume.id,
        ),
    )[0]


def candidate_system_status(candidate):
    workflow = _workflow(candidate)
    attempt = _latest_effective_attempt(workflow)
    if workflow and workflow.status == m.CandidateWorkflow.STATUS_PASSED:
        return SCREENING_PASSED
    if attempt and attempt.status == m.AssignmentAttempt.STATUS_PASSED:
        return SCREENING_PASSED
    if attempt and attempt.status == m.AssignmentAttempt.STATUS_REJECTED:
        return SCREENING_REJECTED
    if (
        workflow
        and workflow.status == m.CandidateWorkflow.STATUS_ARCHIVED
        and workflow.archive_reason == m.CandidateWorkflow.ARCHIVE_ALL_REJECTED
    ):
        return SCREENING_REJECTED
    if attempt and attempt.status in [
        m.AssignmentAttempt.STATUS_DISPATCHED_L2,
        m.AssignmentAttempt.STATUS_ASSIGNED_L3,
    ]:
        return PENDING_SCREENING
    if attempt and attempt.status in [
        m.AssignmentAttempt.STATUS_PENDING_REVIEW,
        m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
    ]:
        return ALLOCATED
    resume = current_resume(candidate, workflow)
    return CLASSIFIED if _is_classified(candidate, resume) else RAW


def system_status_label(status):
    return LABELS.get(status, status or "")


def filter_queryset_by_system_status(qs, statuses):
    statuses = normalize_statuses(statuses)
    if not statuses:
        return qs
    candidates = (
        qs.select_related("workflow__current_resume")
        .prefetch_related("resumes", "workflow__attempts")
        .distinct()
    )
    ids = [
        candidate.id
        for candidate in candidates
        if candidate_system_status(candidate) in statuses
    ]
    return qs.filter(id__in=ids)


PROCESSING_RESULT_VALUES = {
    "success",
    "failed",
    "review",
    "dispatch",
    "archive",
    "skipped",
    "cancelled",
}


def filter_queryset_by_processing_result(qs, params):
    """按处理中心某次 AI 运行的候选人级结果筛选。

    ``success`` / ``failed`` / ``skipped`` / ``cancelled`` 与 ScopeItem 的终态
    一一对应；待复核、待下发和建议归档则与该运行产生的 AI 决策对应。后者是
    成功处理的业务细分，因此允许和 ``success`` 结果重叠，和处理中心计数保持
    同一语义。
    """
    raw_run_id = _value(params, "processing_run_id")
    if not raw_run_id:
        return qs
    try:
        run_id = int(raw_run_id)
    except (TypeError, ValueError):
        return qs.none()

    result = _value(params, "processing_result")
    if not result:
        return qs.filter(processing_scope_items__run_id=run_id).distinct()
    if result not in PROCESSING_RESULT_VALUES:
        return qs.none()

    scope_statuses = {
        "success": "success",
        "failed": "failed",
        "skipped": "skipped_manual_change",
        "cancelled": "cancelled",
    }
    if result in scope_statuses:
        return qs.filter(
            processing_scope_items__run_id=run_id,
            processing_scope_items__status=scope_statuses[result],
        ).distinct()

    recommendation = {
        "review": m.AgentDispatchDecision.RECOMMEND_REVIEW,
        "dispatch": m.AgentDispatchDecision.RECOMMEND_DISPATCH,
        "archive": m.AgentDispatchDecision.RECOMMEND_ARCHIVE,
    }[result]
    return qs.filter(
        workflow__agent_decisions__processing_run_id=run_id,
        workflow__agent_decisions__recommendation=recommendation,
    ).distinct()


def apply_candidate_filters(qs, params):
    search = _value(params, "search")
    if search:
        normalized_search = search.strip().lower()
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(name_pinyin__icontains=normalized_search)
            | Q(name_pinyin_initials__icontains=normalized_search)
            | Q(phone__icontains=search)
            | Q(resumes__apply_id__icontains=search)
            | Q(resumes__position_name__icontains=search)
        )
    name = _value(params, "name")
    if name:
        name_search = name.strip().lower()
        qs = qs.filter(
            Q(name__icontains=name)
            | Q(name_pinyin__icontains=name_search)
            | Q(name_pinyin_initials__icontains=name_search)
        )
    if _value(params, "phone"):
        qs = qs.filter(phone__icontains=_value(params, "phone"))
    if _value(params, "first_degree_school"):
        qs = qs.filter(
            first_degree_school__icontains=_value(params, "first_degree_school")
        )
    if _value(params, "highest_degree_school"):
        qs = qs.filter(
            highest_degree_school__icontains=_value(params, "highest_degree_school")
        )
    highest_major_values = _list_value(params, "highest_major_in")
    if highest_major_values:
        qs = qs.filter(highest_major__in=highest_major_values)
    elif _value(params, "highest_major"):
        qs = qs.filter(highest_major__icontains=_value(params, "highest_major"))
    current_rank_values = _list_value(params, "current_rank_in")
    if current_rank_values:
        qs = _filter_by_candidate_summary_values(
            qs,
            current_rank_values,
            lambda candidate: candidate_summary.current_rank(candidate),
        )
    elif _value(params, "current_rank"):
        rank = _value(params, "current_rank")
        qs = _filter_by_candidate_summary(
            qs,
            lambda candidate: str(candidate_summary.current_rank(candidate) or "")
            == rank,
        )
    if _value(params, "current_apply_id"):
        apply_id = _value(params, "current_apply_id")
        qs = _filter_by_candidate_summary(
            qs,
            lambda candidate: apply_id.lower()
            in candidate_summary.current_apply_id(candidate).lower(),
        )
    current_entity_values = _list_value(params, "current_entity_in")
    if current_entity_values:
        qs = _filter_by_candidate_summary_values(
            qs,
            current_entity_values,
            lambda candidate: _current_resume_text(candidate, "entity"),
        )
    elif _value(params, "current_entity"):
        entity = _value(params, "current_entity")
        qs = _filter_by_candidate_summary(
            qs,
            lambda candidate: entity.lower()
            in _current_resume_text(candidate, "entity").lower(),
        )
    position_name_values = _list_value(params, "current_position_name_in")
    if position_name_values:
        qs = _filter_by_candidate_summary_values(
            qs,
            position_name_values,
            lambda candidate: _current_resume_text(candidate, "position_name"),
        )
    elif _value(params, "current_position_name"):
        position_name = _value(params, "current_position_name")
        qs = _filter_by_candidate_summary(
            qs,
            lambda candidate: position_name.lower()
            in _current_resume_text(candidate, "position_name").lower(),
        )
    job_category_values = _list_value(params, "current_job_category_in")
    if job_category_values:
        qs = _filter_by_candidate_summary_values(
            qs,
            job_category_values,
            lambda candidate: _current_resume_text(candidate, "job_category"),
        )
    elif _value(params, "current_job_category"):
        job_category = _value(params, "current_job_category")
        qs = _filter_by_candidate_summary(
            qs,
            lambda candidate: job_category.lower()
            in _current_resume_text(candidate, "job_category").lower(),
        )
    department_name_values = _list_value(params, "job_department_name_in")
    if department_name_values:
        qs = _filter_by_candidate_summary_values(
            qs,
            department_name_values,
            candidate_summary.job_department_name,
        )
    elif _value(params, "job_department_name"):
        department_name = _value(params, "job_department_name")
        qs = _filter_by_candidate_summary(
            qs,
            lambda candidate: department_name.lower()
            in candidate_summary.job_department_name(candidate).lower(),
        )
    school_tag_values = _list_value(params, "school_tag_in")
    if school_tag_values:
        qs = _filter_by_candidate_summary_values(
            qs, school_tag_values, candidate_school_tag
        )
    elif _value(params, "school_tag"):
        school_tag = _value(params, "school_tag")
        qs = qs.filter(
            Q(highest_degree_tag__name__icontains=school_tag)
            | Q(highest_degree_tag__code__icontains=school_tag)
            | Q(first_degree_tag__name__icontains=school_tag)
            | Q(first_degree_tag__code__icontains=school_tag)
            | Q(highest_degree_platform__icontains=school_tag)
            | Q(first_degree_platform__icontains=school_tag)
        )
    workflow_statuses = (
        normalize_workflow_statuses(_list_value(params, "workflow_status"))
        or normalize_workflow_statuses(_list_value(params, "status"))
    )
    if workflow_statuses:
        status_filter = Q()
        if m.CandidateWorkflow.STATUS_PENDING in workflow_statuses:
            status_filter |= Q(workflow__status=m.CandidateWorkflow.STATUS_PENDING) | Q(
                workflow__isnull=True
            )
        explicit_statuses = [
            status
            for status in workflow_statuses
            if status != m.CandidateWorkflow.STATUS_PENDING
        ]
        if explicit_statuses:
            status_filter |= Q(workflow__status__in=explicit_statuses)
        qs = qs.filter(status_filter)
    reason_type = _value(params, "reason_type")
    if reason_type:
        expected_reason = "" if reason_type == "none" else reason_type
        qs = _filter_by_candidate_summary(
            qs,
            lambda candidate: candidate_summary.reason(candidate)[0] == expected_reason,
        )
    if _value(params, "imported_after"):
        qs = qs.filter(imported_at__date__gte=_value(params, "imported_after"))
    if _value(params, "imported_before"):
        qs = qs.filter(imported_at__date__lte=_value(params, "imported_before"))
    system_statuses = (
        _list_value(params, "system_statuses") or _list_value(params, "system_status")
    )
    qs = filter_queryset_by_system_status(qs, system_statuses)
    return filter_queryset_by_processing_result(qs, params).distinct()


def candidate_filter_options(qs):
    """汇总简历库主表当前展示字段的可选值，供前端下拉筛选复用。"""
    values = {
        "highest_major": set(),
        "current_rank": set(),
        "current_entity": set(),
        "current_position_name": set(),
        "job_department_name": set(),
        "current_job_category": set(),
        "school_tag": set(),
    }
    for candidate in qs:
        resume = candidate_summary.current_resume(candidate)
        _add_option(values["highest_major"], candidate.highest_major)
        _add_option(values["current_rank"], candidate_summary.current_rank(candidate))
        _add_option(values["current_entity"], getattr(resume, "entity", ""))
        _add_option(
            values["current_position_name"], getattr(resume, "position_name", "")
        )
        _add_option(values["job_department_name"], candidate_summary.job_department_name(candidate))
        _add_option(values["current_job_category"], getattr(resume, "job_category", ""))
        _add_option(values["school_tag"], candidate_school_tag(candidate))

    raw_options = {
        **{
            key: sorted(items, key=str.casefold)
            for key, items in values.items()
            if key != "current_rank"
        },
        "current_rank": sorted(values["current_rank"], key=lambda value: int(value)),
    }
    return {
        key: [_filter_option(value) for value in options]
        for key, options in raw_options.items()
    }


def _filter_option(value):
    label = str(value)
    full_pinyin, initials = name_to_pinyin(label)
    return {
        "label": label,
        "value": label,
        "search_text": " ".join(
            item for item in [label.casefold(), full_pinyin, initials] if item
        ),
    }


def _filter_by_candidate_summary(qs, predicate):
    candidates = (
        qs.select_related(
            "workflow",
            "workflow__current_resume",
            "workflow__current_resume__job",
            "workflow__current_resume__job__department",
            "workflow__current_resume__job__department__parent",
        )
        .prefetch_related(
            "resumes",
            "resumes__job__department__parent",
            "workflow__attempts__resume",
            "workflow__attempts__department",
            "workflow__attempts__contact",
            "workflow__attempts__sub_department",
            "workflow__attempts__sub_contact",
        )
        .distinct()
    )
    ids = [candidate.id for candidate in candidates if predicate(candidate)]
    return qs.filter(id__in=ids)


def _filter_by_candidate_summary_values(qs, values, accessor):
    normalized_values = {str(value).strip().casefold() for value in values if str(value).strip()}
    return _filter_by_candidate_summary(
        qs,
        lambda candidate: str(accessor(candidate) or "").strip().casefold()
        in normalized_values,
    )


def _current_resume_text(candidate, attr):
    resume = candidate_summary.current_resume(candidate)
    return str(getattr(resume, attr, "") or "") if resume else ""


def candidate_school_tag(candidate):
    return (
        getattr(candidate.highest_degree_tag, "name", "")
        or getattr(candidate.first_degree_tag, "name", "")
        or candidate.highest_degree_platform
        or candidate.first_degree_platform
        or ""
    )


def _add_option(values, value):
    text = str(value or "").strip()
    if text:
        values.add(text)


def _workflow(candidate):
    try:
        return candidate.workflow
    except (m.CandidateWorkflow.DoesNotExist, AttributeError):
        return None


def _latest_effective_attempt(workflow):
    if not workflow:
        return None
    attempts = [
        attempt
        for attempt in workflow.attempts.all()
        if attempt.status in ACTIVE_ATTEMPT_STATUSES
    ]
    if not attempts:
        return None
    return sorted(attempts, key=lambda attempt: (attempt.attempt_no, attempt.id))[-1]


def _is_classified(candidate, resume):
    if not resume or not resume.job_category:
        return False
    return bool(
        candidate.first_degree_tag_id
        or candidate.highest_degree_tag_id
        or candidate.first_degree_platform
        or candidate.highest_degree_platform
    )


def _value(params, key):
    if hasattr(params, "get"):
        value = params.get(key)
    else:
        value = None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _list_value(params, key):
    if hasattr(params, "getlist"):
        values = params.getlist(key)
        if values:
            return [
                item.strip()
                for value in values
                for item in str(value).split(",")
                if item.strip()
            ]
    value = _value(params, key)
    if value is None:
        return []
    if isinstance(value, list):
        return [
            item.strip()
            for entry in value
            for item in str(entry).split(",")
            if item.strip()
        ]
    return str(value).split(",")
