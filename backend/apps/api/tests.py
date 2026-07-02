from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.permissions import ensure_rbac_defaults
from apps.core import models as m


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.TokenAuthentication"
        ],
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": 20,
    }
)
class AgentDispatchDecisionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        ensure_rbac_defaults()
        self.user = User.objects.create_user(
            username="hr", password="pass", role=User.ROLE_HR
        )
        self.user.groups.add(Group.objects.get(name="HR"))
        self.client.force_authenticate(self.user)
        department = m.Department.objects.create(name="技术部", level=2)
        m.Contact.objects.create(
            name="二级接口人",
            employee_no="L2001",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        self.candidate = m.Candidate.objects.create(
            identity_hash="candidate-1",
            name="张三",
            phone="13800000000",
            first_degree_platform="平台A",
            highest_degree_platform="平台A",
        )
        self.resume = m.Resume.objects.create(
            candidate=self.candidate,
            apply_id="A1001",
            position_name="后端工程师",
            volunteer_rank=1,
        )
        m.Job.objects.create(
            department=department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )
        self.workflow = m.CandidateWorkflow.objects.create(
            candidate=self.candidate,
            status=m.CandidateWorkflow.STATUS_ARCHIVED,
            current_resume=self.resume,
            current_rank=1,
            dispatch_strategy="ai",
            archive_reason=m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
        )
        self.decision = m.AgentDispatchDecision.objects.create(
            workflow=self.workflow,
            resume=self.resume,
            recommendation=None,
            confidence_score=None,
            error_code="pdf_missing",
            error_message="缺少 PDF 简历文件",
            prompt_version="demo-v1",
            decision_version="demo-v1",
        )

    def test_retry_records_new_failed_decision_when_pdf_is_still_missing(self):
        response = self.client.post(f"/api/agent-decisions/{self.decision.id}/retry/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(m.AssignmentAttempt.objects.exists())
        self.assertEqual(m.AgentDispatchDecision.objects.count(), 2)
        new_decision = m.AgentDispatchDecision.objects.order_by("-id").first()
        self.assertNotEqual(new_decision.id, self.decision.id)
        self.assertIsNone(new_decision.recommendation)
        self.assertIsNone(new_decision.confidence_score)
        self.assertEqual(new_decision.error_code, "pdf_missing")
        self.assertEqual(response.data["decision"]["id"], new_decision.id)

    def test_retry_rejects_high_confidence_dispatch_decision(self):
        self.decision.recommendation = m.AgentDispatchDecision.RECOMMEND_DISPATCH
        self.decision.confidence_score = 0.88
        self.decision.error_code = ""
        self.decision.error_message = ""
        self.decision.save(
            update_fields=[
                "recommendation",
                "confidence_score",
                "error_code",
                "error_message",
            ]
        )

        response = self.client.post(f"/api/agent-decisions/{self.decision.id}/retry/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(m.AgentDispatchDecision.objects.count(), 1)

    def test_retry_cancels_old_active_ai_attempt_before_creating_new_one(self):
        self.resume.resume_file = "张三（A1001）.pdf"
        self.resume.save(update_fields=["resume_file"])
        old_attempt = m.AssignmentAttempt.objects.create(
            workflow=self.workflow,
            resume=self.resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_AI,
            status=m.AssignmentAttempt.STATUS_PENDING_REVIEW,
            contact=m.Contact.objects.get(employee_no="L2001"),
            department=m.Department.objects.get(name="技术部"),
            agent_decision=self.decision,
            confidence_score=0.55,
            review_required=True,
            match_mode="ai",
        )

        response = self.client.post(f"/api/agent-decisions/{self.decision.id}/retry/")

        self.assertEqual(response.status_code, 200)
        old_attempt.refresh_from_db()
        self.assertEqual(old_attempt.status, m.AssignmentAttempt.STATUS_CANCELLED)
        self.assertEqual(old_attempt.cancel_reason, m.AssignmentAttempt.CANCEL_RERUN)
        self.assertEqual(
            m.AssignmentAttempt.objects.filter(
                status__in=[
                    m.AssignmentAttempt.STATUS_PENDING_REVIEW,
                    m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
                ]
            ).count(),
            1,
        )


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.TokenAuthentication"
        ],
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": 20,
    }
)
class RbacApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.hr = User.objects.create_user(
            username="hr", password="pass", role=User.ROLE_HR
        )
        self.hr.groups.add(Group.objects.get(name="HR"))
        self.admin = User.objects.create_user(
            username="admin", password="pass", role=User.ROLE_ADMIN
        )
        self.admin.groups.add(Group.objects.get(name="管理员"))

        self.dept_a = m.Department.objects.create(name="技术二部", level=2)
        self.dept_b = m.Department.objects.create(name="产品二部", level=2)
        self.secondary_a = m.Contact.objects.create(
            name="技术二级接口人",
            employee_no="S-A",
            department=self.dept_a,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        self.secondary_b = m.Contact.objects.create(
            name="产品二级接口人",
            employee_no="S-B",
            department=self.dept_b,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        self.tertiary_a = m.Contact.objects.create(
            name="技术三级接口人",
            employee_no="T-A",
            department=m.Department.objects.create(
                name="技术三级组", level=3, parent=self.dept_a
            ),
            contact_level=m.Contact.LEVEL_TERTIARY,
        )
        self.secondary_user = User.objects.create_user(
            username="secondary-a",
            password="pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=self.secondary_a,
        )
        self.secondary_user.groups.add(Group.objects.get(name="二级接口人"))
        self.tertiary_user = User.objects.create_user(
            username="tertiary-a",
            password="pass",
            role=User.ROLE_TERTIARY_CONTACT,
            contact=self.tertiary_a,
        )
        self.tertiary_user.groups.add(Group.objects.get(name="三级接口人"))

        self.attempt_a = self._attempt(
            "candidate-a", "张三", "A1001", self.dept_a, self.secondary_a
        )
        self.attempt_b = self._attempt(
            "candidate-b", "李四", "B1001", self.dept_b, self.secondary_b
        )
        self.attempt_a.sub_contact = self.tertiary_a
        self.attempt_a.sub_department = self.tertiary_a.department
        self.attempt_a.status = m.AssignmentAttempt.STATUS_ASSIGNED_L3
        self.attempt_a.save(update_fields=["sub_contact", "sub_department", "status"])

    def _attempt(self, identity, name, apply_id, department, contact):
        candidate = m.Candidate.objects.create(
            identity_hash=identity,
            name=name,
            phone="13800000000",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id=apply_id,
            position_name="后端工程师",
            volunteer_rank=1,
        )
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=resume,
            current_rank=1,
        )
        return m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_DISPATCHED_L2,
            department=department,
            contact=contact,
        )

    def test_login_returns_token_and_me_returns_permissions(self):
        response = self.client.post(
            "/api/auth/login/", {"username": "hr", "password": "pass"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.data)
        self.assertIn("resume.view", response.data["user"]["permissions"])
        self.assertIn("HR", response.data["user"]["roles"])

    def test_secondary_contact_only_sees_own_received_attempts(self):
        self.client.force_authenticate(self.secondary_user)

        response = self.client.get("/api/workflow-attempts/")

        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(ids, [self.attempt_a.id])

    def test_tertiary_contact_only_sees_assigned_attempts(self):
        self.client.force_authenticate(self.tertiary_user)

        response = self.client.get("/api/workflow-attempts/")

        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(ids, [self.attempt_a.id])

    def test_contact_cannot_access_settings(self):
        self.client.force_authenticate(self.secondary_user)

        response = self.client.get("/api/configs/")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_known_config_value(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            "/api/configs/ai_dispatch_threshold/",
            {"value": 0.82},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["key"], "ai_dispatch_threshold")
        self.assertEqual(response.data["value"], 0.82)
        self.assertEqual(m.Config.objects.get(key="ai_dispatch_threshold").value, 0.82)

    def test_permissions_endpoint_returns_tree_for_admin(self):
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data)
        codes = [
            permission["code"]
            for module in response.data
            for permission in module["children"]
        ]
        self.assertIn("settings.manage_permissions", codes)
