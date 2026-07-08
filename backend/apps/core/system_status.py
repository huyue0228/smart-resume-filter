"""Derived system resume status for candidate list and scoped reprocessing."""

from django.db.models import Q

from apps.core import models as m


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
    SCREENING_PASSED: "筛选通过",
    SCREENING_REJECTED: "筛选不通过",
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
    if _value(params, "highest_major"):
        qs = qs.filter(highest_major__icontains=_value(params, "highest_major"))
    if _value(params, "current_rank"):
        qs = qs.filter(
            Q(workflow__current_rank=_value(params, "current_rank"))
            | Q(
                workflow__isnull=True,
                resumes__volunteer_rank=_value(params, "current_rank"),
            )
        )
    if _value(params, "current_entity"):
        qs = qs.filter(
            Q(workflow__current_resume__entity__icontains=_value(params, "current_entity"))
            | Q(
                workflow__isnull=True,
                resumes__entity__icontains=_value(params, "current_entity"),
            )
        )
    if _value(params, "current_position_name"):
        qs = qs.filter(
            Q(
                workflow__current_resume__position_name__icontains=_value(
                    params, "current_position_name"
                )
            )
            | Q(
                workflow__isnull=True,
                resumes__position_name__icontains=_value(
                    params, "current_position_name"
                ),
            )
        )
    if _value(params, "current_job_category"):
        qs = qs.filter(
            Q(
                workflow__current_resume__job_category__icontains=_value(
                    params, "current_job_category"
                )
            )
            | Q(
                workflow__isnull=True,
                resumes__job_category__icontains=_value(params, "current_job_category"),
            )
        )
    if _value(params, "school_tag"):
        school_tag = _value(params, "school_tag")
        qs = qs.filter(
            Q(highest_degree_tag__name__icontains=school_tag)
            | Q(highest_degree_tag__code__icontains=school_tag)
            | Q(first_degree_tag__name__icontains=school_tag)
            | Q(first_degree_tag__code__icontains=school_tag)
            | Q(highest_degree_platform__icontains=school_tag)
            | Q(first_degree_platform__icontains=school_tag)
        )
    workflow_status = _value(params, "status")
    if workflow_status:
        if workflow_status == m.CandidateWorkflow.STATUS_PENDING:
            qs = qs.filter(
                Q(workflow__status=m.CandidateWorkflow.STATUS_PENDING)
                | Q(workflow__isnull=True)
            )
        else:
            qs = qs.filter(workflow__status=workflow_status)
    if _value(params, "imported_after"):
        qs = qs.filter(imported_at__date__gte=_value(params, "imported_after"))
    if _value(params, "imported_before"):
        qs = qs.filter(imported_at__date__lte=_value(params, "imported_before"))
    system_statuses = (
        _list_value(params, "system_statuses") or _list_value(params, "system_status")
    )
    return filter_queryset_by_system_status(qs, system_statuses).distinct()


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
            return values
    value = _value(params, key)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return str(value).split(",")
