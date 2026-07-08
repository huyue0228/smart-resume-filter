from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile
from urllib.parse import quote

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
import pandas as pd
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

    def test_admin_config_api_excludes_ai_connection_settings(self):
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/configs/")

        self.assertEqual(response.status_code, 200)
        keys = {item["key"] for item in response.data}
        self.assertIn("ai_dispatch_threshold", keys)
        self.assertNotIn("AI_MODEL_NAME", keys)
        self.assertNotIn("AI_API_KEY_ENV", keys)
        self.assertNotIn("AI_BASE_URL_ENV", keys)
        self.assertFalse(
            {"api_key", "api_key_env", "base_url", "base_url_env"}
            & {field for item in response.data for field in item}
        )

        update_response = self.client.patch(
            "/api/configs/AI_MODEL_NAME/",
            {"value": "gpt-test"},
            format="json",
        )
        self.assertEqual(update_response.status_code, 404)

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


class ListFilteringPaginationApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin-list", password="pass", role=User.ROLE_ADMIN
        )
        self.admin.groups.add(Group.objects.get(name="管理员"))
        self.client.force_authenticate(self.admin)

    def test_page_size_query_param_controls_candidate_page_length(self):
        for index in range(5):
            m.Candidate.objects.create(
                identity_hash=f"candidate-page-{index}",
                name=f"候选人{index}",
                phone=f"1380000000{index}",
            )

        response = self.client.get("/api/candidates/", {"page_size": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(len(response.data["results"]), 2)

    def test_candidate_header_filters_match_current_resume_and_school_tag(self):
        keep = m.Candidate.objects.create(
            identity_hash="candidate-keep",
            name="张三",
            phone="13800000001",
            first_degree_school="南京大学",
            highest_degree_school="南京大学",
            highest_major="计算机",
            highest_degree_platform="平台A",
        )
        drop = m.Candidate.objects.create(
            identity_hash="candidate-drop",
            name="李四",
            phone="13900000002",
            first_degree_school="普通大学",
            highest_degree_school="普通大学",
            highest_major="市场营销",
            highest_degree_platform="平台B",
        )
        keep_resume = m.Resume.objects.create(
            candidate=keep,
            apply_id="A1001",
            entity="GW",
            position_name="后端工程师",
            volunteer_rank=1,
            job_category="技术类",
        )
        drop_resume = m.Resume.objects.create(
            candidate=drop,
            apply_id="B1001",
            entity="YLS",
            position_name="产品经理",
            volunteer_rank=2,
            job_category="产品类",
        )
        m.CandidateWorkflow.objects.create(
            candidate=keep,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=keep_resume,
            current_rank=1,
        )
        m.CandidateWorkflow.objects.create(
            candidate=drop,
            status=m.CandidateWorkflow.STATUS_PENDING,
            current_resume=drop_resume,
            current_rank=2,
        )

        response = self.client.get(
            "/api/candidates/",
            {
                "name": "张",
                "phone": "138",
                "current_rank": 1,
                "current_entity": "GW",
                "current_position_name": "后端",
                "current_job_category": "技术",
                "school_tag": "平台A",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [keep.id])

    def test_job_header_filters_cover_visible_columns(self):
        department = m.Department.objects.create(name="研发中心", level=2)
        m.Job.objects.create(
            entity="GW",
            department=department,
            public_name="后端开发",
            position_name="后端工程师",
            category="技术类",
            job_family="研发",
            location="深圳",
            education="本科",
            headcount=3,
            is_public=True,
        )
        m.Job.objects.create(
            entity="YLS",
            public_name="产品运营",
            position_name="产品经理",
            category="产品类",
            job_family="产品",
            location="上海",
            education="硕士",
            headcount=1,
            is_public=False,
        )

        response = self.client.get(
            "/api/jobs/",
            {
                "entity": "GW",
                "department_name": "研发",
                "position_name": "工程师",
                "job_family": "研发",
                "location": "深圳",
                "education": "本科",
                "headcount": 3,
                "is_public": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["public_name"], "后端开发")

    def test_school_header_filters_cover_visible_columns(self):
        m.School.objects.create(name="南京大学", platform="平台A", region="南")
        m.School.objects.create(name="北京大学", platform="平台B", region="北")

        response = self.client.get("/api/schools/", {"region": "南"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "南京大学")

    def test_contact_header_filters_cover_visible_columns(self):
        department = m.Department.objects.create(name="研发二部", level=2, entity="GW")
        m.Contact.objects.create(
            name="王五",
            employee_no="E1001",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            can_delegate=True,
            is_active=True,
        )
        m.Contact.objects.create(
            name="赵六",
            employee_no="E2001",
            department=m.Department.objects.create(name="产品二部", level=2, entity="YLS"),
            contact_level=m.Contact.LEVEL_TERTIARY,
            can_delegate=False,
            is_active=False,
        )

        response = self.client.get(
            "/api/contacts/",
            {
                "department_level": 2,
                "can_delegate": "true",
                "entity": "GW",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "王五")


class CandidateExportApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.hr = User.objects.create_user(
            username="hr-export", password="pass", role=User.ROLE_HR
        )
        self.hr.groups.add(Group.objects.get(name="HR"))
        self.client.force_authenticate(self.hr)

    def test_candidate_export_returns_zip_for_selected_candidates(self):
        with TemporaryDirectory() as media_root:
            resume_dir = Path(media_root) / "resumes"
            resume_dir.mkdir()
            (resume_dir / "张三（A1001）.txt").write_text("resume body", encoding="utf-8")
            candidate = m.Candidate.objects.create(
                identity_hash="candidate-export",
                name="张三",
                phone="13800000000",
            )
            m.Resume.objects.create(
                candidate=candidate,
                apply_id="A1001",
                position_name="后端工程师",
                resume_file="张三（A1001）.txt",
            )

            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.get(
                    "/api/candidates/export/", {"ids": str(candidate.id)}
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertEqual(response["X-Export-Count"], "1")
        self.assertEqual(response["X-Export-Missing"], "0")
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            self.assertEqual(zf.namelist(), ["张三（A1001）.txt"])
            self.assertEqual(zf.read("张三（A1001）.txt").decode("utf-8"), "resume body")


class ResumePreviewApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.hr = User.objects.create_user(
            username="hr-preview", password="pass", role=User.ROLE_HR
        )
        self.hr.groups.add(Group.objects.get(name="HR"))
        self.client.force_authenticate(self.hr)

    def test_resume_preview_returns_inline_file_content(self):
        with TemporaryDirectory() as media_root:
            resume_dir = Path(media_root) / "resumes"
            resume_dir.mkdir()
            (resume_dir / "张三（A1001）.txt").write_text("resume body", encoding="utf-8")
            candidate = m.Candidate.objects.create(
                identity_hash="candidate-preview",
                name="张三",
                phone="13800000000",
            )
            resume = m.Resume.objects.create(
                candidate=candidate,
                apply_id="A1001",
                position_name="后端工程师",
                resume_file="张三（A1001）.txt",
            )

            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.get(f"/api/resumes/{resume.id}/preview/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode("utf-8"), "resume body")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertEqual(response["X-Resume-Filename"], quote("张三（A1001）.txt"))

    def test_resume_preview_returns_404_when_file_is_missing(self):
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-preview-missing",
            name="李四",
            phone="13900000000",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="A1002",
            position_name="产品经理",
        )

        response = self.client.get(f"/api/resumes/{resume.id}/preview/")

        self.assertEqual(response.status_code, 404)

    def test_attempt_resume_preview_uses_attempt_scope(self):
        department = m.Department.objects.create(name="技术二部", level=2)
        contact = m.Contact.objects.create(
            name="技术二级接口人",
            employee_no="S-A",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        user = User.objects.create_user(
            username="secondary-preview",
            password="pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=contact,
        )
        user.groups.add(Group.objects.get(name="二级接口人"))

        with TemporaryDirectory() as media_root:
            resume_dir = Path(media_root) / "resumes"
            resume_dir.mkdir()
            (resume_dir / "王五（A1003）.txt").write_text("attempt body", encoding="utf-8")
            candidate = m.Candidate.objects.create(
                identity_hash="candidate-attempt-preview",
                name="王五",
                phone="13700000000",
            )
            resume = m.Resume.objects.create(
                candidate=candidate,
                apply_id="A1003",
                position_name="测试工程师",
                resume_file="王五（A1003）.txt",
            )
            workflow = m.CandidateWorkflow.objects.create(
                candidate=candidate,
                status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
                current_resume=resume,
                current_rank=1,
            )
            attempt = m.AssignmentAttempt.objects.create(
                workflow=workflow,
                resume=resume,
                attempt_no=1,
                source=m.AssignmentAttempt.SOURCE_RULE,
                status=m.AssignmentAttempt.STATUS_DISPATCHED_L2,
                department=department,
                contact=contact,
            )

            self.client.force_authenticate(user)
            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.get(
                    f"/api/workflow-attempts/{attempt.id}/resume-preview/"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode("utf-8"), "attempt body")
        self.assertIn("inline", response["Content-Disposition"])

    def test_attempt_resume_preview_hides_unscoped_attempt(self):
        own_department = m.Department.objects.create(name="技术二部", level=2)
        other_department = m.Department.objects.create(name="产品二部", level=2)
        own_contact = m.Contact.objects.create(
            name="技术二级接口人",
            employee_no="S-A",
            department=own_department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        other_contact = m.Contact.objects.create(
            name="产品二级接口人",
            employee_no="S-B",
            department=other_department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        user = User.objects.create_user(
            username="secondary-unscoped-preview",
            password="pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=own_contact,
        )
        user.groups.add(Group.objects.get(name="二级接口人"))
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-attempt-unscoped",
            name="赵六",
            phone="13600000000",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="A1004",
            position_name="产品经理",
            resume_file="赵六（A1004）.txt",
        )
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=resume,
            current_rank=1,
        )
        attempt = m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_DISPATCHED_L2,
            department=other_department,
            contact=other_contact,
        )

        self.client.force_authenticate(user)
        response = self.client.get(
            f"/api/workflow-attempts/{attempt.id}/resume-preview/"
        )

        self.assertEqual(response.status_code, 404)


class ImportApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.hr = User.objects.create_user(
            username="hr-import", password="pass", role=User.ROLE_HR
        )
        self.hr.groups.add(Group.objects.get(name="HR"))
        self.client.force_authenticate(self.hr)

    def test_replace_contacts_import_keeps_existing_resume_pool(self):
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-import",
            name="张三",
            phone="13800000000",
        )
        m.Resume.objects.create(
            candidate=candidate,
            apply_id="A1001",
            position_name="后端工程师",
        )
        old_department = m.Department.objects.create(name="旧部门", level=2)
        old_contact = m.Contact.objects.create(
            name="旧接口人",
            employee_no="OLD001",
            department=old_department,
        )
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=m.Resume.objects.get(apply_id="A1001"),
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
            department=old_department,
            contact=old_contact,
        )
        buf = BytesIO()
        pd.DataFrame(
            [
                {
                    "工号": "NEW001",
                    "姓名": "新接口人",
                    "一层部门": "技术中心",
                    "二层部门": "后端组",
                    "接口人层级": "二级接口人",
                }
            ]
        ).to_excel(buf, index=False)
        buf.seek(0)

        response = self.client.post(
            "/api/import/",
            {
                "mode": "replace",
                "contacts": SimpleUploadedFile(
                    "部门接口人信息.xlsx",
                    buf.getvalue(),
                    content_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                ),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(m.Candidate.objects.count(), 1)
        self.assertEqual(m.Resume.objects.count(), 1)
        self.assertEqual(m.AssignmentAttempt.objects.count(), 1)
        self.assertFalse(m.Contact.objects.get(employee_no="OLD001").is_active)
        self.assertTrue(m.Contact.objects.get(employee_no="NEW001").is_active)
