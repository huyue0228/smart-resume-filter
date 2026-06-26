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


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Candidate
        fields = "__all__"


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

    class Meta:
        model = m.Contact
        fields = ["id", "name", "employee_no", "department", "department_name", "entity"]


class AllocationSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="resume.candidate.name", read_only=True)
    position_name = serializers.CharField(source="resume.position_name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True, default="")
    contact_name = serializers.CharField(source="contact.name", read_only=True, default="")

    class Meta:
        model = m.Allocation
        fields = [
            "id",
            "candidate_name",
            "position_name",
            "department_name",
            "contact_name",
            "reason",
            "status",
        ]


class ProcessingRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.ProcessingRun
        fields = ["id", "step", "mode", "status", "message", "created_at", "finished_at"]
