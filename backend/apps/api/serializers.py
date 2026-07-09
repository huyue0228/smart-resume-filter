from rest_framework import serializers
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.permissions import (
    PERMISSION_TREE,
    permission_code,
    permission_codename,
    user_permission_codes,
    user_role_names,
)
from apps.core import models as m
from apps.core import system_status


class CurrentUserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    contact = serializers.SerializerMethodField()
    data_scope = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "roles",
            "permissions",
            "contact",
            "data_scope",
            "is_superuser",
            "is_staff",
        ]

    def get_roles(self, obj):
        return user_role_names(obj)

    def get_permissions(self, obj):
        return sorted(user_permission_codes(obj))

    def get_contact(self, obj):
        if not obj.contact:
            return None
        return ContactSerializer(obj.contact).data

    def get_data_scope(self, obj):
        permissions = user_permission_codes(obj)
        if "attempt.view_all" in permissions:
            return {"type": "all"}
        if obj.contact and "attempt.view_received" in permissions:
            return {"type": "received", "contact_id": obj.contact_id}
        if obj.contact and "attempt.view_assigned" in permissions:
            return {"type": "assigned", "contact_id": obj.contact_id}
        return {"type": "none"}


class UserSerializer(serializers.ModelSerializer):
    role_ids = serializers.PrimaryKeyRelatedField(
        source="groups",
        queryset=Group.objects.all(),
        many=True,
        required=False,
    )
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    contact_name = serializers.CharField(source="contact.name", read_only=True, default="")

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "role",
            "contact",
            "contact_name",
            "is_active",
            "is_staff",
            "is_superuser",
            "role_ids",
            "roles",
            "permissions",
            "password",
        ]
        read_only_fields = ["is_superuser"]

    def get_roles(self, obj):
        return user_role_names(obj)

    def get_permissions(self, obj):
        return sorted(user_permission_codes(obj))

    def create(self, validated_data):
        groups = validated_data.pop("groups", [])
        password = validated_data.pop("password", "")
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        if groups:
            user.groups.set(groups)
        return user

    def update(self, instance, validated_data):
        groups = validated_data.pop("groups", None)
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        if groups is not None:
            instance.groups.set(groups)
        return instance


class RoleSerializer(serializers.ModelSerializer):
    permission_codes = serializers.ListField(
        child=serializers.CharField(), required=False, write_only=True
    )
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ["id", "name", "permissions", "permission_codes"]

    def get_permissions(self, obj):
        return sorted(
            permission_code(permission.codename)
            for permission in obj.permissions.all()
            if "__" in permission.codename
        )

    def _set_permissions(self, group, codes):
        from django.contrib.auth.models import Permission

        codenames = [permission_codename(code) for code in codes]
        permissions = Permission.objects.filter(codename__in=codenames)
        group.permissions.set(permissions)

    def create(self, validated_data):
        codes = validated_data.pop("permission_codes", None)
        group = super().create(validated_data)
        if codes is not None:
            self._set_permissions(group, codes)
        return group

    def update(self, instance, validated_data):
        codes = validated_data.pop("permission_codes", None)
        group = super().update(instance, validated_data)
        if codes is not None:
            self._set_permissions(group, codes)
        return group


class ConfigSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    value_type = serializers.CharField(read_only=True)
    value = serializers.JSONField()


class PermissionTreeSerializer(serializers.Serializer):
    @staticmethod
    def tree():
        return PERMISSION_TREE


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
        return (
            getattr(c.highest_degree_tag, "name", "")
            or getattr(c.first_degree_tag, "name", "")
            or c.highest_degree_platform
            or c.first_degree_platform
            or ""
        )


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
    system_status = serializers.SerializerMethodField()
    system_status_label = serializers.SerializerMethodField()
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
            "first_degree_tag",
            "highest_degree_tag",
            "first_degree_platform",
            "highest_degree_platform",
            "school_tag",
            "system_status",
            "system_status_label",
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
        return (
            getattr(obj.highest_degree_tag, "name", "")
            or getattr(obj.first_degree_tag, "name", "")
            or obj.highest_degree_platform
            or obj.first_degree_platform
            or ""
        )

    def get_system_status(self, obj):
        return system_status.candidate_system_status(obj)

    def get_system_status_label(self, obj):
        return system_status.system_status_label(self.get_system_status(obj))

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
    majors = serializers.SerializerMethodField()
    major_names = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        write_only=True,
        required=False,
    )

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
            "is_active",
            "majors",
            "major_names",
        ]

    def get_majors(self, obj):
        return list(obj.majors.order_by("id").values_list("major", flat=True))

    def validate_department(self, department):
        if department and department.level != 2:
            raise serializers.ValidationError("岗位必须绑定二级部门")
        return department

    def _clean_major_names(self, values):
        seen = set()
        result = []
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def _replace_majors(self, job, major_names):
        m.JobMajor.objects.filter(job=job).delete()
        m.JobMajor.objects.bulk_create(
            [m.JobMajor(job=job, major=major) for major in major_names]
        )

    def create(self, validated_data):
        major_names = self._clean_major_names(validated_data.pop("major_names", []))
        job = super().create(validated_data)
        self._replace_majors(job, major_names)
        return job

    def update(self, instance, validated_data):
        has_major_names = "major_names" in validated_data
        major_names = self._clean_major_names(validated_data.pop("major_names", []))
        job = super().update(instance, validated_data)
        if has_major_names:
            self._replace_majors(job, major_names)
        return job


class SchoolSerializer(serializers.ModelSerializer):
    school_tag_name = serializers.CharField(
        source="school_tag.name", read_only=True, default=""
    )

    class Meta:
        model = m.School
        fields = [
            "id",
            "name",
            "platform",
            "region",
            "province",
            "school_tag",
            "school_tag_name",
        ]


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


class SchoolTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.SchoolTag
        fields = ["id", "code", "name", "is_default", "is_active"]


class SchoolTagRuleSerializer(serializers.ModelSerializer):
    first_degree_tags = serializers.SerializerMethodField()
    highest_degree_tags = serializers.SerializerMethodField()
    first_degree_tag_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    highest_degree_tag_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = m.SchoolTagRule
        fields = [
            "id",
            "name",
            "first_degree_tags",
            "highest_degree_tags",
            "first_degree_tag_ids",
            "highest_degree_tag_ids",
            "is_active",
            "priority",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def _tag_payload(self, obj, degree_type):
        links = sorted(
            [
                link
                for link in obj.tag_links.all()
                if link.degree_type == degree_type
            ],
            key=lambda link: (link.school_tag.code, link.school_tag_id),
        )
        return [
            {
                "id": link.school_tag_id,
                "code": link.school_tag.code,
                "name": link.school_tag.name,
            }
            for link in links
        ]

    def get_first_degree_tags(self, obj):
        return self._tag_payload(obj, m.SchoolTagRuleTag.DEGREE_FIRST)

    def get_highest_degree_tags(self, obj):
        return self._tag_payload(obj, m.SchoolTagRuleTag.DEGREE_HIGHEST)

    def _tags_for_ids(self, tag_ids, field_name):
        unique_ids = list(dict.fromkeys(tag_ids or []))
        tags_by_id = {
            tag.id: tag for tag in m.SchoolTag.objects.filter(id__in=unique_ids)
        }
        tags = [tags_by_id[tag_id] for tag_id in unique_ids if tag_id in tags_by_id]
        found_ids = {tag.id for tag in tags}
        missing = set(unique_ids) - found_ids
        if missing:
            raise serializers.ValidationError({field_name: "存在无效院校标签"})
        return tags

    def validate(self, attrs):
        attrs = super().validate(attrs)
        is_active = attrs.get(
            "is_active",
            self.instance.is_active if self.instance else True,
        )
        if not is_active:
            return attrs

        first_ids = attrs.get("first_degree_tag_ids")
        highest_ids = attrs.get("highest_degree_tag_ids")
        if self.instance:
            if first_ids is None:
                first_ids = list(
                    self.instance.tag_links.filter(
                        degree_type=m.SchoolTagRuleTag.DEGREE_FIRST
                    ).values_list("school_tag_id", flat=True)
                )
            if highest_ids is None:
                highest_ids = list(
                    self.instance.tag_links.filter(
                        degree_type=m.SchoolTagRuleTag.DEGREE_HIGHEST
                    ).values_list("school_tag_id", flat=True)
                )

        errors = {}
        if not first_ids:
            errors["first_degree_tag_ids"] = "启用规则至少需要一个第一学历标签"
        if not highest_ids:
            errors["highest_degree_tag_ids"] = "启用规则至少需要一个最高学历标签"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def _sync_tag_links(self, rule, degree_type, tags):
        if tags is None:
            return
        rule.tag_links.filter(degree_type=degree_type).delete()
        m.SchoolTagRuleTag.objects.bulk_create(
            [
                m.SchoolTagRuleTag(
                    rule=rule,
                    school_tag=tag,
                    degree_type=degree_type,
                )
                for tag in tags
            ]
        )

    def create(self, validated_data):
        first_ids = validated_data.pop("first_degree_tag_ids", [])
        highest_ids = validated_data.pop("highest_degree_tag_ids", [])
        first_tags = self._tags_for_ids(first_ids, "first_degree_tag_ids")
        highest_tags = self._tags_for_ids(highest_ids, "highest_degree_tag_ids")
        rule = super().create(validated_data)
        self._sync_tag_links(rule, m.SchoolTagRuleTag.DEGREE_FIRST, first_tags)
        self._sync_tag_links(rule, m.SchoolTagRuleTag.DEGREE_HIGHEST, highest_tags)
        return rule

    def update(self, instance, validated_data):
        first_ids = validated_data.pop("first_degree_tag_ids", None)
        highest_ids = validated_data.pop("highest_degree_tag_ids", None)
        first_tags = (
            self._tags_for_ids(first_ids, "first_degree_tag_ids")
            if first_ids is not None
            else None
        )
        highest_tags = (
            self._tags_for_ids(highest_ids, "highest_degree_tag_ids")
            if highest_ids is not None
            else None
        )
        rule = super().update(instance, validated_data)
        self._sync_tag_links(rule, m.SchoolTagRuleTag.DEGREE_FIRST, first_tags)
        self._sync_tag_links(rule, m.SchoolTagRuleTag.DEGREE_HIGHEST, highest_tags)
        return rule


class CandidateWorkflowSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="candidate.name", read_only=True)
    phone = serializers.CharField(source="candidate.phone", read_only=True)
    current_resume = serializers.SerializerMethodField()
    current_apply_id = serializers.SerializerMethodField()
    current_position_name = serializers.SerializerMethodField()
    current_rank = serializers.SerializerMethodField()

    def _display_resume(self, obj):
        if hasattr(obj, "_display_resume_cache"):
            return obj._display_resume_cache
        if obj.current_resume_id:
            resume = obj.current_resume
        elif obj.passed_attempt_id and obj.passed_attempt:
            resume = obj.passed_attempt.resume
        else:
            latest_attempt = (
                obj.attempts.select_related("resume")
                .order_by("-attempt_no", "-created_at", "-id")
                .first()
            )
            resume = latest_attempt.resume if latest_attempt else None
        obj._display_resume_cache = resume
        return resume

    def get_current_resume(self, obj):
        resume = self._display_resume(obj)
        return resume.id if resume else None

    def get_current_apply_id(self, obj):
        resume = self._display_resume(obj)
        return resume.apply_id if resume else ""

    def get_current_position_name(self, obj):
        resume = self._display_resume(obj)
        return resume.position_name if resume else ""

    def get_current_rank(self, obj):
        if obj.current_rank:
            return obj.current_rank
        resume = self._display_resume(obj)
        return resume.volunteer_rank if resume else None

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
    volunteer_rank = serializers.IntegerField(
        source="resume.volunteer_rank", read_only=True
    )
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
            "volunteer_rank",
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
            "created_by_username_snapshot",
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
            "created_by_username_snapshot",
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
            "recommended_contact_name_snapshot",
            "recommended_contact_employee_no_snapshot",
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
