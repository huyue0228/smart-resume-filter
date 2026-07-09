"""候选人主列表合并展示字段。

简历库现在承担候选人工作流与归档候选人的主入口职责。本模块把“当前
志愿、岗位部门、原因”这些跨 Resume / Workflow / AssignmentAttempt 的
展示规则集中起来，供 API 序列化和候选人筛选复用，避免两边各解释一套口径。
"""

from apps.core import models as m


REASON_ASSIGNMENT = "assignment"
REASON_ARCHIVE = "archive"
REASON_BLOCK = "block"
REASON_CLASSIFICATION = "classification"
REASON_NONE = ""


def workflow_or_none(candidate):
    try:
        return candidate.workflow
    except (m.CandidateWorkflow.DoesNotExist, AttributeError):
        return None


def current_resume(candidate):
    workflow = workflow_or_none(candidate)
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


def latest_effective_attempt(workflow, resume_id=None):
    if not workflow:
        return None
    attempts = [
        attempt
        for attempt in workflow.attempts.all()
        if attempt.status != m.AssignmentAttempt.STATUS_CANCELLED
        and (resume_id is None or attempt.resume_id == resume_id)
    ]
    if not attempts:
        return None
    return sorted(attempts, key=lambda attempt: (attempt.attempt_no, attempt.id))[-1]


def current_apply_id(candidate):
    resume = current_resume(candidate)
    return resume.apply_id if resume else ""


def current_rank(candidate):
    workflow = workflow_or_none(candidate)
    if workflow and workflow.current_rank:
        return workflow.current_rank
    resume = current_resume(candidate)
    return resume.volunteer_rank if resume else None


def job_department_name(candidate):
    workflow = workflow_or_none(candidate)
    resume = current_resume(candidate)
    attempt = latest_effective_attempt(
        workflow, resume_id=resume.id if resume else None
    )
    if attempt:
        return (
            attempt.department_name_snapshot
            or (attempt.department.name if attempt.department else "")
        )

    department = resume.job.department if resume and resume.job_id else None
    if not department:
        return ""
    if department.level == 3 and department.parent:
        return department.parent.name
    return department.name


def reason(candidate):
    workflow = workflow_or_none(candidate)
    if workflow and workflow.status == m.CandidateWorkflow.STATUS_ARCHIVED:
        return REASON_ARCHIVE, workflow.archive_detail or workflow.archive_reason
    if workflow and workflow.block_reason:
        return REASON_BLOCK, workflow.block_detail or workflow.block_reason

    resume = current_resume(candidate)
    attempt = latest_effective_attempt(
        workflow, resume_id=resume.id if resume else None
    )
    if attempt:
        return (
            REASON_ASSIGNMENT,
            attempt.manual_reason or attempt.match_reason or attempt.feedback_note,
        )

    if resume and resume.category_reason:
        return REASON_CLASSIFICATION, resume.category_reason
    return REASON_NONE, ""
