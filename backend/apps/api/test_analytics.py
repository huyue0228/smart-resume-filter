from datetime import datetime, timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.permissions import ensure_rbac_defaults
from apps.core import models as m


class RecruitmentAnalyticsApiTests(TestCase):
    def setUp(self):
        cache.clear()
        ensure_rbac_defaults()
        self.hr = User.objects.create_user(username="analytics-hr", password="pass")
        self.hr.groups.add(self.hr.groups.model.objects.get(name="HR"))
        self.no_access = User.objects.create_user(username="analytics-contact")
        self.no_access.groups.add(
            self.no_access.groups.model.objects.get(name="二级接口人")
        )
        self.client = APIClient()

        self.department = m.Department.objects.create(name="产品研发", level=2)
        self.job = m.Job.objects.create(
            entity="GW",
            department=self.department,
            public_name="软件工程师",
            category="技术",
        )
        self.tag = m.SchoolTag.objects.create(code="TARGET", name="目标院校")
        now = timezone.now()
        imported_at = now - timedelta(days=2)

        candidate_1 = m.Candidate.objects.create(
            identity_hash="analytics-candidate-1",
            name="候选人一",
            phone="13800000001",
            highest_education=m.Candidate.EDUCATION_MASTER,
            highest_degree_tag=self.tag,
        )
        resume_1 = m.Resume.objects.create(
            candidate=candidate_1,
            apply_id="AN-001",
            entity="GW",
            position_name="软件工程师",
            job=self.job,
            job_category="技术",
            volunteer_rank=1,
        )
        m.Resume.objects.filter(pk=resume_1.pk).update(imported_at=imported_at)
        workflow_1 = m.CandidateWorkflow.objects.create(
            candidate=candidate_1,
            current_resume=resume_1,
            status=m.CandidateWorkflow.STATUS_PASSED,
        )
        attempt = m.AssignmentAttempt.objects.create(
            workflow=workflow_1,
            resume=resume_1,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_PASSED,
            department=self.department,
            department_name_snapshot="产品研发（历史快照）",
            dispatched_at=imported_at + timedelta(hours=4),
            feedback_at=imported_at + timedelta(hours=10),
            feedback_result=m.AssignmentAttempt.FEEDBACK_PASSED,
        )
        m.AssignmentAttempt.objects.filter(pk=attempt.pk).update(
            created_at=imported_at + timedelta(hours=2)
        )

        candidate_2 = m.Candidate.objects.create(
            identity_hash="analytics-candidate-2",
            name="候选人二",
            phone="13800000002",
            highest_education=m.Candidate.EDUCATION_BACHELOR,
            highest_degree_tag=self.tag,
        )
        resume_2 = m.Resume.objects.create(
            candidate=candidate_2,
            apply_id="AN-002",
            entity="YLS",
            position_name="产品经理",
            job_category="产品",
            volunteer_rank=1,
        )
        m.Resume.objects.filter(pk=resume_2.pk).update(imported_at=imported_at)
        workflow_2 = m.CandidateWorkflow.objects.create(
            candidate=candidate_2,
            current_resume=resume_2,
            status=m.CandidateWorkflow.STATUS_ARCHIVED,
            archive_reason=m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
        )
        m.AgentDispatchDecision.objects.create(
            workflow=workflow_2,
            resume=resume_2,
            recommendation=m.AgentDispatchDecision.RECOMMEND_REVIEW,
            special_route_applied=True,
        )
        m.AgentDispatchDecision.objects.create(
            workflow=workflow_2,
            resume=resume_2,
            error_code="llm_timeout",
            error_message="模型调用超时",
        )

        old_candidate = m.Candidate.objects.create(
            identity_hash="analytics-old-candidate",
            name="范围外候选人",
            phone="13800000003",
        )
        old_resume = m.Resume.objects.create(
            candidate=old_candidate,
            apply_id="AN-OLD",
            entity="GW",
        )
        m.Resume.objects.filter(pk=old_resume.pk).update(
            imported_at=now - timedelta(days=60)
        )

    def test_requires_analytics_permission(self):
        self.client.force_authenticate(self.no_access)
        response = self.client.get("/api/analytics/recruitment-overview/")
        self.assertEqual(response.status_code, 403)

    def test_returns_cohort_metrics_distributions_and_methodology(self):
        self.client.force_authenticate(self.hr)
        response = self.client.get("/api/analytics/recruitment-overview/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["resume_count"], 2)
        self.assertEqual(payload["summary"]["candidate_count"], 2)
        self.assertEqual(payload["summary"]["classified_count"], 2)
        self.assertEqual(payload["summary"]["allocated_count"], 1)
        self.assertEqual(payload["summary"]["dispatched_count"], 1)
        self.assertEqual(payload["summary"]["feedback_count"], 1)
        self.assertEqual(payload["summary"]["passed_count"], 1)
        self.assertEqual(payload["summary"]["archived_count"], 1)
        self.assertEqual(payload["conversion"]["passed_rate"], 50.0)
        self.assertEqual(payload["average_hours"]["to_allocation"], 2.0)
        self.assertEqual(payload["department_ranking"][0]["label"], "产品研发（历史快照）")
        self.assertEqual(payload["ai_error_distribution"][0]["key"], "llm_timeout")
        self.assertEqual(
            payload["ai_recommendation_distribution"],
            [{"key": "review", "label": "人工复核", "count": 1}],
        )
        self.assertEqual(
            payload["methodology"]["cohort"],
            "Resume.imported_at 落在所选日期范围内的投递记录",
        )

    def test_supports_entity_and_source_filters(self):
        self.client.force_authenticate(self.hr)
        response = self.client.get(
            "/api/analytics/recruitment-overview/",
            {"entity": "GW", "source": "rule"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["candidate_count"], 1)
        self.assertEqual(response.json()["source_distribution"][0]["key"], "rule")

    def test_department_filter_and_ranking_use_latest_non_cancelled_attempt(self):
        candidate = m.Candidate.objects.get(identity_hash="analytics-candidate-1")
        resume = m.Resume.objects.get(apply_id="AN-001")
        workflow = m.CandidateWorkflow.objects.get(candidate=candidate)
        latest_department = m.Department.objects.create(
            name="最新统计归属部门", level=2
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=resume,
            attempt_no=2,
            source=m.AssignmentAttempt.SOURCE_MANUAL,
            status=m.AssignmentAttempt.STATUS_DISPATCHED_L2,
            department=latest_department,
            department_name_snapshot="最新统计归属部门快照",
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=resume,
            attempt_no=3,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_CANCELLED,
            department=self.department,
            department_name_snapshot="取消尝试部门快照",
        )
        self.client.force_authenticate(self.hr)

        old_response = self.client.get(
            "/api/analytics/recruitment-overview/",
            {"department_id": self.department.id},
        )
        latest_response = self.client.get(
            "/api/analytics/recruitment-overview/",
            {"department_id": latest_department.id},
        )

        self.assertEqual(old_response.status_code, 200)
        self.assertEqual(old_response.json()["summary"]["candidate_count"], 0)
        self.assertEqual(latest_response.status_code, 200)
        payload = latest_response.json()
        self.assertEqual(payload["summary"]["candidate_count"], 1)
        self.assertEqual(
            payload["department_ranking"],
            [
                {
                    "key": latest_department.id,
                    "label": "最新统计归属部门快照",
                    "count": 1,
                }
            ],
        )
        self.assertEqual(payload["source_distribution"][0]["key"], "manual")

    def test_job_filter_and_ranking_use_current_effective_resume(self):
        candidate = m.Candidate.objects.get(identity_hash="analytics-candidate-1")
        current_job = m.Job.objects.create(
            entity="GW",
            department=self.department,
            public_name="当前有效岗位",
            category="技术",
        )
        current_resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="AN-CURRENT",
            entity="GW",
            position_name="当前有效岗位",
            job=current_job,
            job_category="技术",
            volunteer_rank=2,
        )
        m.Resume.objects.filter(pk=current_resume.pk).update(
            imported_at=timezone.now() - timedelta(days=60)
        )
        m.CandidateWorkflow.objects.filter(candidate=candidate).update(
            current_resume=current_resume
        )
        self.client.force_authenticate(self.hr)

        response = self.client.get(
            "/api/analytics/recruitment-overview/",
            {"job_id": current_job.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["candidate_count"], 1)
        self.assertEqual(response.json()["job_ranking"][0]["label"], "当前有效岗位")

    def test_school_tag_filter_uses_highest_tag_then_first_tag_fallback(self):
        candidate = m.Candidate.objects.get(identity_hash="analytics-candidate-1")
        candidate.first_degree_tag = self.tag
        candidate.highest_degree_tag = None
        candidate.save(update_fields=["first_degree_tag", "highest_degree_tag"])
        self.client.force_authenticate(self.hr)

        response = self.client.get(
            "/api/analytics/recruitment-overview/",
            {"school_tag_id": self.tag.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["candidate_count"], 2)
        self.assertEqual(response.json()["school_tag_ranking"][0]["count"], 2)

    def test_rejects_invalid_or_overlong_date_range(self):
        self.client.force_authenticate(self.hr)
        response = self.client.get(
            "/api/analytics/recruitment-overview/",
            {"date_from": "2025-01-01", "date_to": "2026-12-31"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("366", response.json()["detail"])

        response = self.client.get(
            "/api/analytics/recruitment-overview/",
            {"date_from": "not-a-date"},
        )
        self.assertEqual(response.status_code, 400)

    def test_response_is_cached_for_identical_filters(self):
        self.client.force_authenticate(self.hr)
        first = self.client.get("/api/analytics/recruitment-overview/")
        self.assertEqual(first.status_code, 200)
        m.Resume.objects.filter(apply_id="AN-002").delete()

        second = self.client.get("/api/analytics/recruitment-overview/")
        self.assertEqual(second.json()["summary"]["resume_count"], 2)
