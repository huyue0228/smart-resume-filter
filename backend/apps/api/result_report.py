"""按应聘 ID 生成简历处理结果 Excel 报表。"""

from collections import OrderedDict
from io import BytesIO

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from apps.core import models as m
from apps.core import system_status


SUMMARY_HEADERS = [
    "二级部门",
    "导入简历数",
    "分配简历数",
    "待处理",
    "已分类",
    "已分配",
    "待筛选",
    "通过",
    "不通过",
]
DETAIL_HEADERS = [
    "导入时间",
    "姓名",
    "应聘ID",
    "招聘主体",
    "岗位",
    "志愿",
    "最高学历",
    "二级部门",
    "二级接口人",
    "三级部门",
    "三级接口人",
    "分配来源",
    "简历状态",
    "反馈结果",
    "反馈时间",
]
STATUS_ORDER = [
    system_status.RAW,
    system_status.CLASSIFIED,
    system_status.ALLOCATED,
    system_status.PENDING_SCREENING,
    system_status.SCREENING_PASSED,
    system_status.SCREENING_REJECTED,
]


def safe_excel_text(value):
    """阻止外部文本被 Excel 当成公式执行。"""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def latest_effective_attempt(resume):
    attempts = getattr(resume, "report_attempts", None)
    if attempts is None:
        attempts = list(
            resume.assignment_attempts.exclude(
                status=m.AssignmentAttempt.STATUS_CANCELLED
            ).order_by("attempt_no", "id")
        )
    return attempts[-1] if attempts else None


def resume_report_status(resume, attempt):
    if attempt:
        if attempt.status == m.AssignmentAttempt.STATUS_PASSED:
            return system_status.SCREENING_PASSED
        if attempt.status == m.AssignmentAttempt.STATUS_REJECTED:
            return system_status.SCREENING_REJECTED
        if attempt.status in {
            m.AssignmentAttempt.STATUS_DISPATCHED_L2,
            m.AssignmentAttempt.STATUS_ASSIGNED_L3,
        }:
            return system_status.PENDING_SCREENING
        if attempt.status in {
            m.AssignmentAttempt.STATUS_PENDING_REVIEW,
            m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
        }:
            return system_status.ALLOCATED
    candidate = resume.candidate
    classified = bool(
        resume.job_category
        and (
            candidate.first_degree_tag_id
            or candidate.highest_degree_tag_id
            or candidate.first_degree_platform
            or candidate.highest_degree_platform
        )
    )
    return system_status.CLASSIFIED if classified else system_status.RAW


def _attempt_text(attempt, snapshot_field, related_field):
    if not attempt:
        return ""
    snapshot = getattr(attempt, snapshot_field, "")
    related = getattr(attempt, related_field, None)
    return snapshot or (related.name if related else "")


def _summary_bucket():
    return {
        "imported": 0,
        "allocated": 0,
        **{status: 0 for status in STATUS_ORDER},
    }


def build_result_report(resumes):
    rows = []
    summaries = OrderedDict()
    total = _summary_bucket()
    education_labels = dict(m.Candidate.HIGHEST_EDUCATION_CHOICES)
    source_labels = dict(m.AssignmentAttempt.SOURCE_CHOICES)

    for resume in resumes:
        attempt = latest_effective_attempt(resume)
        status_code = resume_report_status(resume, attempt)
        department_name = _attempt_text(
            attempt, "department_name_snapshot", "department"
        )
        group_name = department_name or "未分配"
        bucket = summaries.setdefault(group_name, _summary_bucket())
        for target in (bucket, total):
            target["imported"] += 1
            target[status_code] += 1
            if attempt:
                target["allocated"] += 1

        imported_at = timezone.localtime(resume.imported_at).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        feedback_result = (
            dict(m.AssignmentAttempt.FEEDBACK_CHOICES).get(
                attempt.feedback_result, attempt.feedback_result
            )
            if attempt
            else ""
        )
        feedback_at = (
            timezone.localtime(attempt.feedback_at).strftime("%Y-%m-%d %H:%M:%S")
            if attempt and attempt.feedback_at
            else ""
        )
        rows.append(
            [
                imported_at,
                resume.candidate.name,
                resume.apply_id,
                resume.entity,
                resume.position_name,
                resume.volunteer_rank or "",
                education_labels.get(
                    resume.candidate.highest_education,
                    resume.candidate.highest_education,
                ),
                department_name,
                _attempt_text(attempt, "contact_name_snapshot", "contact"),
                _attempt_text(
                    attempt, "sub_department_name_snapshot", "sub_department"
                ),
                _attempt_text(attempt, "sub_contact_name_snapshot", "sub_contact"),
                source_labels.get(attempt.source, attempt.source) if attempt else "",
                system_status.system_status_label(status_code),
                feedback_result,
                feedback_at,
            ]
        )

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "部门汇总"
    detail_sheet = workbook.create_sheet("简历明细")
    summary_sheet.append(SUMMARY_HEADERS)
    ordered_names = sorted(name for name in summaries if name != "未分配")
    if "未分配" in summaries:
        ordered_names.append("未分配")
    for name in ordered_names:
        bucket = summaries[name]
        summary_sheet.append(
            [safe_excel_text(name), bucket["imported"], bucket["allocated"]]
            + [bucket[status] for status in STATUS_ORDER]
        )
    summary_sheet.append(
        ["合计", total["imported"], total["allocated"]]
        + [total[status] for status in STATUS_ORDER]
    )

    detail_sheet.append(DETAIL_HEADERS)
    for row in rows:
        detail_sheet.append([safe_excel_text(value) for value in row])

    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for sheet in (summary_sheet, detail_sheet):
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
        for column_cells in sheet.columns:
            width = min(
                36,
                max(10, max(len(str(cell.value or "")) for cell in column_cells) + 2),
            )
            sheet.column_dimensions[column_cells[0].column_letter].width = width

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
