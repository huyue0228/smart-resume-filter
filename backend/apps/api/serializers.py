from rest_framework import serializers

from apps.core import models as m


class ResumeListSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="candidate.name", read_only=True)
    phone = serializers.CharField(source="candidate.phone", read_only=True)
    school_tag = serializers.SerializerMethodField()

    class Meta:
        model = m.Resume
        fields = [
            "id",
            "candidate_name",
            "phone",
            "entity",
            "position_name",
            "volunteer_rank",
            "job_category",
            "school_tag",
            "status",
        ]

    def get_school_tag(self, obj):
        c = obj.candidate
        return c.highest_degree_platform or c.first_degree_platform or ""


class ResumeBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Resume
        fields = [
            "id",
            "apply_id",
            "entity",
            "org",
            "position_name",
            "status",
            "apply_date",
            "volunteer_rank",
            "assigned_entity",
            "job_category",
            "category_mode",
            "category_reason",
            "resume_file",
        ]


class CandidateSerializer(serializers.ModelSerializer):
    school_tag = serializers.SerializerMethodField()
    workflow_id = serializers.SerializerMethodField()
    workflow_status = serializers.SerializerMethodField()
    current_resume = serializers.SerializerMethodField()
    current_rank = serializers.SerializerMethodField()
    archive_reason = serializers.SerializerMethodField()
    archive_detail = serializers.SerializerMethodField()
    resumes = serializers.SerializerMethodField()
    attempts = serializers.SerializerMethodField()

    class Meta:
        model = m.Candidate
        fields = [
            "id",
            "identity_hash",
            "name",
            "phone",
            "gender",
            "household_province",
            "first_degree_school",
            "highest_degree_school",
            "highest_major",
            "first_degree_platform",
            "highest_degree_platform",
            "school_tag",
            "workflow_id",
            "workflow_status",
            "current_resume",
            "current_rank",
            "archive_reason",
            "archive_detail",
            "resumes",
            "attempts",
            "imported_at",
            "updated_at",
        ]

    def _workflow(self, obj):
        try:
            return obj.workflow
        except (m.CandidateWorkflow.DoesNotExist, AttributeError):
            return None

    def _current_resume(self, obj):
        workflow = self._workflow(obj)
        if workflow and workflow.current_resume:
            return workflow.current_resume
        resumes = list(obj.resumes.all())
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

    def get_school_tag(self, obj):
        return obj.highest_degree_platform or obj.first_degree_platform or ""

    def get_workflow_id(self, obj):
        workflow = self._workflow(obj)
        return workflow.id if workflow else None

    def get_workflow_status(self, obj):
        workflow = self._workflow(obj)
        return workflow.status if workflow else m.CandidateWorkflow.STATUS_PENDING

    def get_current_resume(self, obj):
        resume = self._current_resume(obj)
        return ResumeBriefSerializer(resume).data if resume else None

    def get_current_rank(self, obj):
        workflow = self._workflow(obj)
        if workflow and workflow.current_rank:
            return workflow.current_rank
        resume = self._current_resume(obj)
        return resume.volunteer_rank if resume else None

    def get_archive_reason(self, obj):
        workflow = self._workflow(obj)
        return workflow.archive_reason if workflow else ""

    def get_archive_detail(self, obj):
        workflow = self._workflow(obj)
        return workflow.archive_detail if workflow else ""

    def get_resumes(self, obj):
        resumes = sorted(
            obj.resumes.all(),
            key=lambda resume: (
                resume.volunteer_rank if resume.volunteer_rank is not None else 999,
                resume.apply_date.toordinal() if resume.apply_date else 0,
                resume.id,
            ),
        )
        return ResumeBriefSerializer(resumes, many=True).data

    def get_attempts(self, obj):
        workflow = self._workflow(obj)
        if not workflow:
            return []
        attempts = workflow.attempts.select_related(
            "resume", "contact", "department", "sub_contact", "sub_department"
        ).order_by("attempt_no")
        return [
            {
                "id": attempt.id,
                "attempt_no": attempt.attempt_no,
                "source": attempt.source,
                "status": attempt.status,
                "resume": attempt.resume_id,
                "apply_id": attempt.resume.apply_id,
                "position_name": attempt.position_name_snapshot
                or attempt.resume.position_name,
                "department_name": attempt.department_name_snapshot
                or (attempt.department.name if attempt.department else ""),
                "contact_name": attempt.contact_name_snapshot
                or (attempt.contact.name if attempt.contact else ""),
                "sub_department_name": attempt.sub_department_name_snapshot
                or (attempt.sub_department.name if attempt.sub_department else ""),
                "sub_contact_name": attempt.sub_contact_name_snapshot
                or (attempt.sub_contact.name if attempt.sub_contact else ""),
                "feedback_result": attempt.feedback_result,
                "feedback_note": attempt.feedback_note,
                "feedback_at": attempt.feedback_at,
                "created_at": attempt.created_at,
            }
            for attempt in attempts
        ]


class JobSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = m.Job
        fields = [
            "id",
            "entity",
            "department",
            "department_name",
            "category",
            "public_name",
            "is_public",
            "position_name",
            "job_family",
            "location",
            "education",
            "headcount",
        ]


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.School
        fields = "__all__"


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Department
        fields = ["id", "name", "level", "parent", "entity"]


class ContactSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=""
    )
    entity = serializers.CharField(source="department.entity", read_only=True, default="")
    department_level = serializers.IntegerField(source="department.level", read_only=True)
    parent_department = serializers.IntegerField(source="department.parent_id", read_only=True)

    class Meta:
        model = m.Contact
        fields = [
            "id",
            "name",
            "employee_no",
            "department",
            "department_name",
            "department_level",
            "parent_department",
            "entity",
            "contact_level",
            "can_delegate",
            "is_active",
        ]


class SchoolTagRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.SchoolTagRule
        fields = "__all__"


class CandidateWorkflowSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="candidate.name", read_only=True)
    phone = serializers.CharField(source="candidate.phone", read_only=True)
    current_apply_id = serializers.CharField(
        source="current_resume.apply_id", read_only=True, default=""
    )
    current_position_name = serializers.CharField(
        source="current_resume.position_name", read_only=True, default=""
    )

    class Meta:
        model = m.CandidateWorkflow
        fields = [
            "id",
            "candidate",
            "candidate_name",
            "phone",
            "status",
            "current_resume",
            "current_apply_id",
            "current_position_name",
            "current_rank",
            "dispatch_strategy",
            "archive_reason",
            "archive_detail",
            "passed_attempt",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]


class AssignmentAttemptSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(
        source="resume.candidate.name", read_only=True
    )
    apply_id = serializers.CharField(source="resume.apply_id", read_only=True)
    position_name = serializers.CharField(source="resume.position_name", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=""
    )
    contact_name = serializers.CharField(source="contact.name", read_only=True, default="")
    sub_department_name = serializers.CharField(
        source="sub_department.name", read_only=True, default=""
    )
    sub_contact_name = serializers.CharField(
        source="sub_contact.name", read_only=True, default=""
    )
    matched_rule_name = serializers.CharField(
        source="matched_rule.name", read_only=True, default=""
    )
    agent_decision_summary = serializers.SerializerMethodField()

    def get_agent_decision_summary(self, obj):
        decision = obj.agent_decision
        if not decision:
            return None
        return {
            "id": decision.id,
            "recommendation": decision.recommendation,
            "recommended_job": decision.recommended_job_id,
            "matched_job_category": decision.matched_job_category,
            "confidence_score": decision.confidence_score,
            "score_breakdown": decision.score_breakdown,
            "summary": decision.summary,
            "reason": decision.reason,
            "evidence": decision.evidence,
            "risks": decision.risks,
            "risk_flags": decision.risk_flags,
            "error_code": decision.error_code,
            "error_message": decision.error_message,
        }

    class Meta:
        model = m.AssignmentAttempt
        fields = [
            "id",
            "workflow",
            "resume",
            "candidate_name",
            "apply_id",
            "position_name",
            "attempt_no",
            "source",
            "status",
            "department",
            "department_name",
            "contact",
            "contact_name",
            "sub_department",
            "sub_department_name",
            "sub_contact",
            "sub_contact_name",
            "matched_rule",
            "matched_rule_name",
            "agent_decision",
            "agent_decision_summary",
            "confidence_score",
            "review_required",
            "match_mode",
            "match_reason",
            "welink_message_id",
            "dispatched_at",
            "assigned_to_sub_at",
            "feedback_result",
            "feedback_note",
            "feedback_at",
            "cancelled_at",
            "cancel_reason",
            "manual_reason",
            "department_name_snapshot",
            "contact_name_snapshot",
            "contact_employee_no_snapshot",
            "sub_department_name_snapshot",
            "sub_contact_name_snapshot",
            "sub_contact_employee_no_snapshot",
            "resume_apply_id_snapshot",
            "position_name_snapshot",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "attempt_no",
            "status",
            "department",
            "sub_department",
            "sub_contact",
            "matched_rule",
            "agent_decision",
            "confidence_score",
            "review_required",
            "match_mode",
            "match_reason",
            "welink_message_id",
            "dispatched_at",
            "assigned_to_sub_at",
            "feedback_result",
            "feedback_note",
            "feedback_at",
            "cancelled_at",
            "cancel_reason",
            "created_by",
        ]


class ProcessingRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.ProcessingRun
        fields = ["id", "step", "mode", "status", "message", "created_at", "finished_at"]


class AgentDispatchDecisionSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(
        source="resume.candidate.name", read_only=True
    )
    apply_id = serializers.CharField(source="resume.apply_id", read_only=True)
    position_name = serializers.CharField(source="resume.position_name", read_only=True)
    recommended_department_name = serializers.CharField(
        source="recommended_department.name", read_only=True, default=""
    )
    recommended_contact_name = serializers.CharField(
        source="recommended_contact.name", read_only=True, default=""
    )
    evaluated_job_name = serializers.SerializerMethodField()
    recommended_job_name = serializers.SerializerMethodField()

    def _job_name(self, job):
        if not job:
            return ""
        return job.public_name or job.position_name or f"Job#{job.pk}"

    def get_evaluated_job_name(self, obj):
        return self._job_name(obj.evaluated_job)

    def get_recommended_job_name(self, obj):
        return self._job_name(obj.recommended_job)

    class Meta:
        model = m.AgentDispatchDecision
        fields = [
            "id",
            "workflow",
            "resume",
            "processing_run",
            "candidate_name",
            "apply_id",
            "position_name",
            "profile",
            "recommendation",
            "evaluated_job",
            "evaluated_job_name",
            "recommended_job",
            "recommended_job_name",
            "matched_job_category",
            "recommended_department",
            "recommended_department_name",
            "recommended_contact",
            "recommended_contact_name",
            "confidence_score",
            "score_breakdown",
            "summary",
            "reason",
            "evidence",
            "risks",
            "risk_flags",
            "error_code",
            "error_message",
            "model_name",
            "prompt_version",
            "decision_version",
            "created_at",
        ]
