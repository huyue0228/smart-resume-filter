import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timedelta

from django.core.cache import cache
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPermissionCode
from apps.core import models as m


CACHE_SECONDS = 300
MAX_RANGE_DAYS = 366
TOP_N = 10


class AnalyticsQueryError(ValueError):
    pass


def _parse_date(value, field_name):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryError(f"{field_name} 必须是 YYYY-MM-DD") from exc


def _parse_int(value, field_name):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryError(f"{field_name} 必须是正整数") from exc
    if parsed <= 0:
        raise AnalyticsQueryError(f"{field_name} 必须是正整数")
    return parsed


def normalize_filters(params):
    today = timezone.localdate()
    date_to = _parse_date(params.get("date_to"), "date_to") or today
    date_from = _parse_date(params.get("date_from"), "date_from") or (
        date_to - timedelta(days=29)
    )
    if date_from > date_to:
        raise AnalyticsQueryError("date_from 不能晚于 date_to")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise AnalyticsQueryError(f"日期范围不能超过 {MAX_RANGE_DAYS} 天")

    education = str(params.get("education") or "").strip()
    allowed_educations = {item[0] for item in m.Candidate.HIGHEST_EDUCATION_CHOICES}
    if education and education not in allowed_educations:
        raise AnalyticsQueryError("education 不是有效学历代码")
    source = str(params.get("source") or "").strip()
    allowed_sources = {item[0] for item in m.AssignmentAttempt.SOURCE_CHOICES}
    if source and source not in allowed_sources:
        raise AnalyticsQueryError("source 不是有效分配来源")

    return {
        "date_from": date_from,
        "date_to": date_to,
        "entity": str(params.get("entity") or "").strip(),
        "job_id": _parse_int(params.get("job_id"), "job_id"),
        "department_id": _parse_int(
            params.get("department_id"), "department_id"
        ),
        "school_tag_id": _parse_int(
            params.get("school_tag_id"), "school_tag_id"
        ),
        "education": education,
        "source": source,
    }


def _cache_key(filters):
    serializable = {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in filters.items()
    }
    digest = hashlib.sha256(
        json.dumps(serializable, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return f"recruitment-analytics:v1:{digest}"


def _percentage(value, total):
    return round(value * 100 / total, 2) if total else 0


def _average_hours(attempts, end_field):
    queryset = attempts.exclude(**{f"{end_field}__isnull": True})
    durations = (
        queryset.values("workflow__candidate_id")
        .annotate(
            imported_at=Min("resume__imported_at"),
            event_at=Min(end_field),
        )
        .annotate(
            duration=ExpressionWrapper(
                F("event_at") - F("imported_at"), output_field=DurationField()
            )
        )
        .aggregate(value=Avg("duration"))["value"]
    )
    return round(durations.total_seconds() / 3600, 2) if durations else None


def _choice_distribution(queryset, field, candidate_field, labels):
    rows = (
        queryset.exclude(
            Q(**{field: ""}) | Q(**{f"{field}__isnull": True})
        )
        .values(field)
        .annotate(count=Count(candidate_field, distinct=True))
        .order_by("-count", field)
    )
    return [
        {
            "key": row[field],
            "label": labels.get(row[field], row[field] or "未填写"),
            "count": row["count"],
        }
        for row in rows
    ]


def _named_ranking(queryset, *, value_field, label_field, candidate_field):
    rows = (
        queryset.values(value_field, label_field)
        .annotate(count=Count(candidate_field, distinct=True))
        .order_by("-count", label_field)[:TOP_N]
    )
    return [
        {
            "key": row[value_field] or row[label_field] or "unknown",
            "label": row[label_field] or "未填写",
            "count": row["count"],
        }
        for row in rows
    ]


def _department_ranking(attempts):
    grouped_candidates = {}
    for row in attempts.values(
        "workflow__candidate_id",
        "department_id",
        "department_name_snapshot",
        "department__name",
    ):
        label = row["department_name_snapshot"] or row["department__name"] or "未分配"
        key = row["department_id"] or f"text:{label}"
        grouped_candidates.setdefault((key, label), set()).add(
            row["workflow__candidate_id"]
        )
    return [
        {"key": key, "label": label, "count": len(candidate_ids)}
        for (key, label), candidate_ids in sorted(
            grouped_candidates.items(), key=lambda item: (-len(item[1]), item[0][1])
        )[:TOP_N]
    ]


def _effective_resume_ids(candidate_ids, base_resumes):
    current = dict(
        m.CandidateWorkflow.objects.filter(
            candidate_id__in=candidate_ids, current_resume_id__isnull=False
        ).values_list("candidate_id", "current_resume_id")
    )
    fallback = {}
    for candidate_id, resume_id in base_resumes.order_by(
        "candidate_id", "volunteer_rank", "apply_date", "id"
    ).values_list("candidate_id", "id"):
        fallback.setdefault(candidate_id, resume_id)
    return [current.get(candidate_id) or fallback.get(candidate_id) for candidate_id in candidate_ids]


def _job_ranking(candidate_ids, base_resumes):
    resume_ids = [item for item in _effective_resume_ids(candidate_ids, base_resumes) if item]
    rows = m.Resume.objects.filter(id__in=resume_ids).values(
        "candidate_id",
        "job_id",
        "job__public_name",
        "job__position_name",
        "position_name",
    )
    counter = Counter()
    for row in rows:
        label = (
            row["job__public_name"]
            or row["job__position_name"]
            or row["position_name"]
            or "未分类"
        )
        counter[(row["job_id"] or f"text:{label}", label)] += 1
    return [
        {"key": key, "label": label, "count": count}
        for (key, label), count in sorted(
            counter.items(), key=lambda item: (-item[1], item[0][1])
        )[:TOP_N]
    ]


def _school_tag_ranking(candidate_ids):
    counter = Counter()
    rows = m.Candidate.objects.filter(id__in=candidate_ids).values(
        "highest_degree_tag_id",
        "highest_degree_tag__name",
        "first_degree_tag_id",
        "first_degree_tag__name",
    )
    for row in rows:
        tag_id = row["highest_degree_tag_id"] or row["first_degree_tag_id"]
        label = (
            row["highest_degree_tag__name"]
            or row["first_degree_tag__name"]
            or "未填写"
        )
        counter[(tag_id or f"text:{label}", label)] += 1
    return [
        {"key": key, "label": label, "count": count}
        for (key, label), count in sorted(
            counter.items(), key=lambda item: (-item[1], item[0][1])
        )[:TOP_N]
    ]


def _trend_rows(base_resumes, attempts, start_date, end_date):
    dates = []
    cursor = start_date
    while cursor <= end_date:
        dates.append(cursor)
        cursor += timedelta(days=1)
    trend = {
        item: {
            "date": item.isoformat(),
            "resumes": 0,
            "allocated": 0,
            "dispatched": 0,
            "feedback": 0,
            "passed": 0,
        }
        for item in dates
    }

    imports = (
        base_resumes.annotate(day=TruncDate("imported_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in imports:
        if row["day"] in trend:
            trend[row["day"]]["resumes"] = row["count"]

    event_fields = {
        "allocated": "created_at",
        "dispatched": "dispatched_at",
        "feedback": "feedback_at",
    }
    for key, field in event_fields.items():
        rows = (
            attempts.exclude(**{f"{field}__isnull": True})
            .annotate(day=TruncDate(field))
            .filter(day__gte=start_date, day__lte=end_date)
            .values("day")
            .annotate(count=Count("workflow__candidate_id", distinct=True))
        )
        for row in rows:
            if row["day"] in trend:
                trend[row["day"]][key] = row["count"]

    passed = (
        attempts.filter(feedback_result=m.AssignmentAttempt.FEEDBACK_PASSED)
        .exclude(feedback_at__isnull=True)
        .annotate(day=TruncDate("feedback_at"))
        .filter(day__gte=start_date, day__lte=end_date)
        .values("day")
        .annotate(count=Count("workflow__candidate_id", distinct=True))
    )
    for row in passed:
        if row["day"] in trend:
            trend[row["day"]]["passed"] = row["count"]
    return list(trend.values())


def _filter_options():
    return {
        "entities": list(
            m.Resume.objects.exclude(entity="")
            .order_by("entity")
            .values_list("entity", flat=True)
            .distinct()
        ),
        "jobs": [
            {"value": item.id, "label": str(item)}
            for item in m.Job.objects.filter(is_active=True).order_by(
                "public_name", "position_name", "id"
            )
        ],
        "departments": [
            {"value": item.id, "label": item.name}
            for item in m.Department.objects.filter(level=2).order_by("name", "id")
        ],
        "school_tags": [
            {"value": item.id, "label": item.name}
            for item in m.SchoolTag.objects.filter(is_active=True).order_by("name", "id")
        ],
        "educations": [
            {"value": value, "label": label}
            for value, label in m.Candidate.HIGHEST_EDUCATION_CHOICES
        ],
        "sources": [
            {"value": value, "label": label}
            for value, label in m.AssignmentAttempt.SOURCE_CHOICES
        ],
    }


def build_recruitment_overview(filters):
    current_timezone = timezone.get_current_timezone()
    start_at = timezone.make_aware(
        datetime.combine(filters["date_from"], time.min), current_timezone
    )
    end_at = timezone.make_aware(
        datetime.combine(filters["date_to"] + timedelta(days=1), time.min),
        current_timezone,
    )
    resumes = m.Resume.objects.filter(imported_at__gte=start_at, imported_at__lt=end_at)
    if filters["entity"]:
        resumes = resumes.filter(entity=filters["entity"])
    if filters["job_id"]:
        resumes = resumes.filter(
            Q(candidate__workflow__current_resume__job_id=filters["job_id"])
            | Q(
                candidate__workflow__current_resume__isnull=True,
                job_id=filters["job_id"],
            )
        )
    if filters["school_tag_id"]:
        resumes = resumes.filter(
            Q(candidate__highest_degree_tag_id=filters["school_tag_id"])
            | Q(
                candidate__highest_degree_tag__isnull=True,
                candidate__first_degree_tag_id=filters["school_tag_id"],
            )
        )
    if filters["education"]:
        resumes = resumes.filter(candidate__highest_education=filters["education"])
    selected_attempt_filters = {}
    if filters["department_id"]:
        selected_attempt_filters["department_id"] = filters["department_id"]
    if filters["source"]:
        selected_attempt_filters["source"] = filters["source"]
    if selected_attempt_filters:
        matching_resume_ids = m.AssignmentAttempt.objects.filter(
            resume_id__in=resumes.values("id"),
            **selected_attempt_filters,
        ).values("resume_id")
        resumes = resumes.filter(id__in=matching_resume_ids)
    resumes = resumes.distinct()

    resume_ids = resumes.values("id")
    candidate_ids = list(
        resumes.order_by().values_list("candidate_id", flat=True).distinct()
    )
    attempts = m.AssignmentAttempt.objects.filter(
        resume_id__in=resume_ids,
        **selected_attempt_filters,
    )
    decisions = m.AgentDispatchDecision.objects.filter(resume_id__in=resume_ids)
    workflows = m.CandidateWorkflow.objects.filter(candidate_id__in=candidate_ids)

    resume_count = resumes.count()
    candidate_count = len(candidate_ids)
    classified_count = (
        resumes.exclude(job_category="")
        .filter(
            Q(candidate__first_degree_tag_id__isnull=False)
            | Q(candidate__highest_degree_tag_id__isnull=False)
            | ~Q(candidate__first_degree_platform="")
            | ~Q(candidate__highest_degree_platform="")
        )
        .values("candidate_id")
        .distinct()
        .count()
    )
    allocated_count = attempts.values("workflow__candidate_id").distinct().count()
    dispatched_count = (
        attempts.exclude(dispatched_at__isnull=True)
        .values("workflow__candidate_id")
        .distinct()
        .count()
    )
    feedback_count = (
        attempts.exclude(feedback_at__isnull=True)
        .values("workflow__candidate_id")
        .distinct()
        .count()
    )
    passed_count = (
        attempts.filter(feedback_result=m.AssignmentAttempt.FEEDBACK_PASSED)
        .values("workflow__candidate_id")
        .distinct()
        .count()
    )
    archived_count = workflows.filter(
        status=m.CandidateWorkflow.STATUS_ARCHIVED
    ).count()

    summary = {
        "resume_count": resume_count,
        "candidate_count": candidate_count,
        "classified_count": classified_count,
        "allocated_count": allocated_count,
        "dispatched_count": dispatched_count,
        "feedback_count": feedback_count,
        "passed_count": passed_count,
        "archived_count": archived_count,
    }
    conversion = {
        "allocated_rate": _percentage(allocated_count, candidate_count),
        "dispatched_rate": _percentage(dispatched_count, candidate_count),
        "feedback_rate": _percentage(feedback_count, candidate_count),
        "passed_rate": _percentage(passed_count, candidate_count),
    }
    average_hours = {
        "to_allocation": _average_hours(attempts, "created_at"),
        "to_dispatch": _average_hours(attempts, "dispatched_at"),
        "to_feedback": _average_hours(attempts, "feedback_at"),
    }

    source_distribution = _choice_distribution(
        attempts,
        "source",
        "workflow__candidate_id",
        dict(m.AssignmentAttempt.SOURCE_CHOICES),
    )
    recommendation_distribution = _choice_distribution(
        decisions.filter(special_route_applied=False),
        "recommendation",
        "workflow__candidate_id",
        dict(m.AgentDispatchDecision.RECOMMEND_CHOICES),
    )
    special_route_count = (
        decisions.filter(special_route_applied=True)
        .values("workflow__candidate_id")
        .distinct()
        .count()
    )
    if special_route_count:
        recommendation_distribution.append(
            {
                "key": "ai_special_route",
                "label": "AI 专项强制分配",
                "count": special_route_count,
            }
        )
    ai_error_distribution = _choice_distribution(
        decisions,
        "error_code",
        "workflow__candidate_id",
        {},
    )
    department_ranking = _department_ranking(attempts)
    school_tag_ranking = _school_tag_ranking(candidate_ids)
    education_distribution = _choice_distribution(
        m.Candidate.objects.filter(id__in=candidate_ids),
        "highest_education",
        "id",
        dict(m.Candidate.HIGHEST_EDUCATION_CHOICES),
    )
    archive_reason_distribution = _choice_distribution(
        workflows.filter(status=m.CandidateWorkflow.STATUS_ARCHIVED),
        "archive_reason",
        "candidate_id",
        dict(m.CandidateWorkflow.ARCHIVE_REASON_CHOICES),
    )
    rejection_rows = (
        attempts.filter(status=m.AssignmentAttempt.STATUS_REJECTED)
        .values("feedback_note")
        .annotate(count=Count("workflow__candidate_id", distinct=True))
        .order_by("-count", "feedback_note")[:TOP_N]
    )
    rejection_reason_distribution = [
        {
            "key": row["feedback_note"] or "empty",
            "label": (row["feedback_note"] or "未填写原因")[:80],
            "count": row["count"],
        }
        for row in rejection_rows
    ]

    return {
        "data_as_of": timezone.localtime().isoformat(),
        "filters": {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in filters.items()
        },
        "methodology": {
            "cohort": "Resume.imported_at 落在所选日期范围内的投递记录",
            "candidate_scope": "候选人数及各阶段按 Candidate 去重",
            "job_scope": "岗位排行优先使用 CandidateWorkflow.current_resume",
            "department_scope": "部门排行优先使用 AssignmentAttempt.department_name_snapshot",
            "conversion_denominator": "所选 cohort 去重候选人数",
        },
        "summary": summary,
        "conversion": conversion,
        "average_hours": average_hours,
        "trend": _trend_rows(
            resumes, attempts, filters["date_from"], filters["date_to"]
        ),
        "source_distribution": source_distribution,
        "ai_recommendation_distribution": recommendation_distribution,
        "ai_error_distribution": ai_error_distribution,
        "job_ranking": _job_ranking(candidate_ids, resumes),
        "department_ranking": department_ranking,
        "school_tag_ranking": school_tag_ranking,
        "education_distribution": education_distribution,
        "archive_reason_distribution": archive_reason_distribution,
        "rejection_reason_distribution": rejection_reason_distribution,
        "filter_options": _filter_options(),
    }


class RecruitmentOverviewView(APIView):
    permission_classes = [HasPermissionCode]
    permission_code = "analytics.view"

    def get(self, request):
        try:
            filters = normalize_filters(request.query_params)
        except AnalyticsQueryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        key = _cache_key(filters)
        payload = cache.get(key)
        if payload is None:
            payload = build_recruitment_overview(filters)
            cache.set(key, payload, CACHE_SECONDS)
        return Response(payload)
