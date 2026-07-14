from datetime import timedelta
from io import BytesIO
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
import zipfile
from urllib.parse import quote

from django.contrib.auth.models import Group, Permission
from django.apps import apps as django_apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
import pandas as pd
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.permissions import ensure_rbac_defaults, permission_codename
from apps.core import models as m
from apps.pipeline import ai_config
from apps.pipeline.ai.service import AIServiceError
from apps.pipeline.services import classify_school


def rest_framework_test_settings():
    return {
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.TokenAuthentication"
        ],
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": 20,
    }


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
        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "gpt-test",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
        ai_config.mark_ai_connection_tested()
        m.Config.objects.update_or_create(key="ai_enabled", defaults={"value": True})
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

        self.assertEqual(response.status_code, 202)
        self.assertFalse(m.AssignmentAttempt.objects.exists())
        self.assertEqual(m.AgentDispatchDecision.objects.count(), 2)
        new_decision = m.AgentDispatchDecision.objects.order_by("-id").first()
        self.assertNotEqual(new_decision.id, self.decision.id)
        self.assertIsNone(new_decision.recommendation)
        self.assertIsNone(new_decision.confidence_score)
        self.assertEqual(new_decision.error_code, "pdf_missing")
        run = m.ProcessingRun.objects.get()
        self.assertEqual(response.data["run"]["id"], run.id)
        self.assertEqual(run.mode, "ai")
        self.assertEqual(run.scope["source"], "ai_retry")
        self.assertEqual(run.scope["retry_decision_id"], self.decision.id)
        self.assertEqual(new_decision.processing_run_id, run.id)

    def test_retry_is_disabled_when_global_ai_switch_is_off(self):
        m.Config.objects.update_or_create(key="ai_enabled", defaults={"value": False})

        response = self.client.post(f"/api/agent-decisions/{self.decision.id}/retry/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("AI 分配当前未开启", response.data["detail"])
        self.assertEqual(m.AgentDispatchDecision.objects.count(), 1)

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

    def test_retry_task_keeps_the_original_decision_resume(self):
        m.Resume.objects.create(
            candidate=self.candidate,
            apply_id="A0000",
            position_name="后端工程师",
            volunteer_rank=0,
        )

        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            side_effect=AIServiceError("pdf_missing", "缺少 PDF 简历文件"),
        ) as screen_resume:
            response = self.client.post(
                f"/api/agent-decisions/{self.decision.id}/retry/"
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(screen_resume.call_args.args[0].id, self.resume.id)

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

        profile = m.ResumeProfile.objects.create(
            resume=self.resume, parse_status="parsed", raw_text="简历正文"
        )
        job = m.Job.objects.get()
        contact = m.Contact.objects.get(employee_no="L2001")
        decision_output = SimpleNamespace(
            recommendation="dispatch",
            summary="结构化 AI 建议",
            reason="证据充分",
            evidence=["项目经历"],
            risks=[],
        )
        result = SimpleNamespace(
            profile=profile,
            output=SimpleNamespace(
                decision=decision_output,
                profile=SimpleNamespace(risk_flags=[]),
            ),
            job=job,
            department=contact.department,
            contact=contact,
            confidence=0.78,
            score_breakdown={"major_match": 0.78},
        )
        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=result,
        ):
            response = self.client.post(f"/api/agent-decisions/{self.decision.id}/retry/")

        self.assertEqual(response.status_code, 202)
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


@override_settings(REST_FRAMEWORK=rest_framework_test_settings())
class PipelineRunApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="hr-pipeline", password="pass", role=User.ROLE_HR
        )
        self.user.groups.add(Group.objects.get(name="HR"))
        self.client.force_authenticate(self.user)

    def test_pipeline_run_forwards_scope_to_runner(self):
        run = m.ProcessingRun.objects.create(
            step="step2",
            mode="rule",
            status="success",
            message="ok",
        )
        scope = {
            "system_statuses": ["screening_passed", "screening_rejected"],
            "candidate_filters": {"system_status": "screening_passed,screening_rejected"},
        }

        with patch("apps.api.views.runner.create_configured_run", return_value=run) as mock_create, patch(
            "apps.api.views.execute_runs_sequence_task.delay",
            return_value=SimpleNamespace(id="task-123"),
        ):
            response = self.client.post(
                "/api/pipeline/run/",
                {"step": "step2", "scope": scope},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        mock_create.assert_called_once_with("step2", scope=scope, created_by=self.user)
        self.assertEqual(response.data["processing_runs"][0]["message"], "ok")

    def test_pipeline_run_rejects_caller_mode_override(self):
        response = self.client.post(
            "/api/pipeline/run/",
            {"step": "step2", "modes": ["rule", "ai"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("系统参数", response.data["detail"])

    def test_pipeline_run_rejects_ai_when_connection_is_not_enabled(self):
        with patch(
            "apps.pipeline.runner.ai_config.allocation_mode",
            side_effect=ValueError("AI 分配已开启，但当前模型连接尚未测试成功"),
        ):
            response = self.client.post(
                "/api/pipeline/run/",
                {"step": "step2"},
                format="json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("尚未测试成功", response.data["detail"])

    def test_pipeline_run_rejects_explicit_empty_modes(self):
        response = self.client.post(
            "/api/pipeline/run/",
            {"step": "step2", "modes": []},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("系统参数", response.data["detail"])

    def test_pipeline_run_rejects_reserved_ai_retry_scope(self):
        response = self.client.post(
            "/api/pipeline/run/",
            {
                "step": "step2",
                "scope": {
                    "source": "ai_retry",
                    "retry_decision_id": 1,
                    "retry_resume_id": 1,
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("简历详情", response.data["detail"])
        self.assertFalse(m.ProcessingRun.objects.exists())

    def test_processing_run_list_includes_elapsed_seconds(self):
        now = timezone.now()
        running = m.ProcessingRun.objects.create(
            step="step2", mode="rule", status="running"
        )
        finished = m.ProcessingRun.objects.create(
            step="step2", mode="ai", status="success"
        )
        m.ProcessingRun.objects.filter(pk=running.pk).update(
            created_at=now - timedelta(seconds=75)
        )
        m.ProcessingRun.objects.filter(pk=finished.pk).update(
            created_at=now - timedelta(seconds=130),
            finished_at=now - timedelta(seconds=65),
        )

        with patch("apps.api.serializers.timezone.now", return_value=now):
            response = self.client.get("/api/pipeline/runs/")

        self.assertEqual(response.status_code, 200)
        runs = {item["id"]: item for item in response.data["results"]}
        self.assertEqual(runs[running.id]["elapsed_seconds"], 75)
        self.assertEqual(runs[finished.id]["elapsed_seconds"], 65)

    def test_pending_processing_run_can_be_cancelled(self):
        run = m.ProcessingRun.objects.create(step="step2", mode="ai", status="pending")
        stage = m.ProcessingRunStage.objects.create(
            run=run, sequence=1, step="step2", label="简历分类、分配与下发"
        )

        response = self.client.post(f"/api/pipeline/runs/{run.id}/cancel/")

        self.assertEqual(response.status_code, 200)
        run.refresh_from_db()
        stage.refresh_from_db()
        self.assertEqual(run.status, "cancelled")
        self.assertEqual(run.cancelled_by, self.user)
        self.assertTrue(run.cancel_requested_at)
        self.assertTrue(run.cancelled_at)
        self.assertTrue(run.finished_at)
        self.assertEqual(stage.status, "cancelled")

    def test_finished_processing_run_cannot_be_cancelled(self):
        run = m.ProcessingRun.objects.create(
            step="step2", mode="rule", status="success"
        )

        response = self.client.post(f"/api/pipeline/runs/{run.id}/cancel/")

        self.assertEqual(response.status_code, 409)
        run.refresh_from_db()
        self.assertEqual(run.status, "success")


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
        self.assertEqual(response.data["results"][0]["volunteer_rank"], 1)
        self.assertEqual(response.data["results"][0]["apply_id"], "A1001")
        self.assertEqual(response.data["results"][0]["position_name"], "后端工程师")

    def test_secondary_contact_does_not_see_hr_pending_attempts(self):
        pending_candidate = m.Candidate.objects.create(
            identity_hash="candidate-pending",
            name="王五",
            phone="13700000000",
        )
        pending_resume = m.Resume.objects.create(
            candidate=pending_candidate,
            apply_id="P1001",
            position_name="算法工程师",
            volunteer_rank=1,
        )
        pending_workflow = m.CandidateWorkflow.objects.create(
            candidate=pending_candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=pending_resume,
            current_rank=1,
        )
        m.AssignmentAttempt.objects.create(
            workflow=pending_workflow,
            resume=pending_resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_AI,
            status=m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
            department=self.dept_a,
            contact=self.secondary_a,
        )
        m.AssignmentAttempt.objects.create(
            workflow=pending_workflow,
            resume=pending_resume,
            attempt_no=2,
            source=m.AssignmentAttempt.SOURCE_AI,
            status=m.AssignmentAttempt.STATUS_PENDING_REVIEW,
            department=self.dept_a,
            contact=self.secondary_a,
        )
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

    def test_secondary_contact_uses_resume_library_with_scoped_safe_fields(self):
        self.client.force_authenticate(self.secondary_user)

        response = self.client.get("/api/candidates/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.attempt_a.workflow.candidate_id])
        row = response.data["results"][0]
        self.assertEqual(row["phone"], "")
        self.assertIsNone(row["preview_resume"])
        self.assertEqual([item["id"] for item in row["resumes"]], [self.attempt_a.resume_id])
        self.assertEqual([item["id"] for item in row["attempts"]], [self.attempt_a.id])
        self.assertEqual(row["current_attempt"]["id"], self.attempt_a.id)
        self.assertNotIn("agent_decision", row["attempts"][0])
        self.assertNotIn("agent_decision_summary", row["current_attempt"])

    def test_tertiary_contact_uses_resume_library_with_only_own_assignment(self):
        self.client.force_authenticate(self.tertiary_user)

        response = self.client.get("/api/candidates/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.attempt_a.workflow.candidate_id])
        row = response.data["results"][0]
        self.assertEqual(row["phone"], "")
        self.assertEqual(row["current_attempt"]["sub_contact"], self.tertiary_a.id)
        self.assertEqual(len(row["resumes"]), 1)
        self.assertEqual(len(row["attempts"]), 1)

    def test_hr_bulk_dispatches_pending_attempt_from_resume_library(self):
        attempt = self._attempt(
            "candidate-pending-dispatch",
            "王五",
            "C1001",
            self.dept_a,
            self.secondary_a,
        )
        attempt.status = m.AssignmentAttempt.STATUS_PENDING_DISPATCH
        attempt.save(update_fields=["status"])
        self.client.force_authenticate(self.hr)

        response = self.client.post(
            "/api/candidates/bulk-dispatch/",
            {"candidate_ids": [attempt.workflow.candidate_id]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dispatched"], 1)
        self.assertEqual(response.data["skipped"], 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, m.AssignmentAttempt.STATUS_DISPATCHED_L2)

    def test_secondary_contact_loads_only_eligible_sub_contacts_for_own_attempt(self):
        other_tertiary = m.Contact.objects.create(
            name="产品三级接口人",
            employee_no="T-B",
            department=m.Department.objects.create(
                name="产品三级组", level=3, parent=self.dept_b
            ),
            contact_level=m.Contact.LEVEL_TERTIARY,
        )
        self.client.force_authenticate(self.secondary_user)

        response = self.client.get(
            f"/api/workflow-attempts/{self.attempt_a.id}/eligible-sub-contacts/"
        )
        forbidden_response = self.client.get(
            f"/api/workflow-attempts/{self.attempt_b.id}/eligible-sub-contacts/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [self.tertiary_a.id])
        self.assertNotIn(other_tertiary.id, [item["id"] for item in response.data])
        self.assertEqual(forbidden_response.status_code, 404)

    def test_rule_and_ai_attempt_lists_return_assignment_reason(self):
        self.attempt_a.match_reason = "规则：院校准入、专业匹配"
        self.attempt_a.save(update_fields=["match_reason"])
        self.attempt_b.source = m.AssignmentAttempt.SOURCE_AI
        self.attempt_b.match_reason = "AI：简历能力与岗位要求匹配"
        self.attempt_b.save(update_fields=["source", "match_reason"])
        self.client.force_authenticate(self.hr)

        rule_response = self.client.get("/api/workflow-attempts/", {"source": "rule"})
        ai_response = self.client.get("/api/workflow-attempts/", {"source": "ai"})

        self.assertEqual(rule_response.status_code, 200)
        self.assertEqual(ai_response.status_code, 200)
        self.assertEqual(rule_response.data["results"][0]["match_reason"], "规则：院校准入、专业匹配")
        self.assertEqual(ai_response.data["results"][0]["match_reason"], "AI：简历能力与岗位要求匹配")

    def test_workflow_and_attempt_header_filters_match_visible_columns(self):
        self.attempt_a.match_reason = "院校准入且专业匹配"
        self.attempt_a.save(update_fields=["match_reason"])
        workflow = self.attempt_a.workflow
        workflow.dispatch_strategy = "rule"
        workflow.save(update_fields=["dispatch_strategy"])
        self.client.force_authenticate(self.hr)

        workflow_response = self.client.get(
            "/api/workflows/",
            {
                "candidate_name": "张",
                "current_rank": "1",
                "current_apply_id": "A1001",
                "current_position_name": "后端",
                "dispatch_strategy": "rule",
            },
        )
        attempt_response = self.client.get(
            "/api/workflow-attempts/",
            {
                "candidate_name": "张",
                "volunteer_rank": "1",
                "apply_id": "A1001",
                "position_name": "后端",
                "department_name": "技术",
                "contact_name": "技术二级",
                "sub_contact_name": "技术三级",
                "match_reason": "专业匹配",
            },
        )

        self.assertEqual(workflow_response.status_code, 200)
        self.assertEqual([item["id"] for item in workflow_response.data["results"]], [workflow.id])
        self.assertEqual(attempt_response.status_code, 200)
        self.assertEqual([item["id"] for item in attempt_response.data["results"]], [self.attempt_a.id])

    def test_user_and_role_header_filters(self):
        self.client.force_authenticate(self.admin)

        user_response = self.client.get(
            "/api/users/", {"username": "hr", "roles": "HR", "is_active": "true"}
        )
        role_response = self.client.get("/api/roles/", {"name": "管理"})

        self.assertEqual(user_response.status_code, 200)
        self.assertEqual([item["username"] for item in user_response.data["results"]], ["hr"])
        self.assertEqual(role_response.status_code, 200)
        self.assertEqual([item["name"] for item in role_response.data["results"]], ["管理员"])

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

    def test_ai_switch_requires_current_successful_connection_test(self):
        self.client.force_authenticate(self.admin)

        blocked_response = self.client.patch(
            "/api/configs/ai_enabled/", {"value": True}, format="json"
        )

        self.assertEqual(blocked_response.status_code, 400)
        self.assertIn("尚未测试成功", blocked_response.data["detail"])

        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "gpt-test",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
        with patch(
            "apps.api.views.ai_service.test_model_connection",
            return_value={
                "model_name": "gpt-test",
                "api_style": "responses",
                "base_url": "https://model.internal/v1",
            },
        ):
            test_response = self.client.post("/api/ai-connection/test/")
        enabled_response = self.client.patch(
            "/api/configs/ai_enabled/", {"value": True}, format="json"
        )
        mode_response = self.client.get("/api/allocation-mode/")

        self.assertEqual(test_response.status_code, 200)
        self.assertTrue(test_response.data["ok"])
        self.assertEqual(enabled_response.status_code, 200)
        self.assertTrue(enabled_response.data["value"])
        self.assertEqual(
            mode_response.data,
            {"mode": "ai", "ai_enabled": True, "ai_ready": True},
        )

    def test_saving_ai_connection_invalidates_test_and_disables_ai(self):
        self.client.force_authenticate(self.admin)
        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "gpt-test",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
        ai_config.mark_ai_connection_tested()
        m.Config.objects.update_or_create(key="ai_enabled", defaults={"value": True})

        response = self.client.patch(
            "/api/ai-connection/",
            {"model_name": "gpt-test-v2"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["test_passed"])
        self.assertFalse(m.Config.objects.get(key="ai_enabled").value)
        self.assertEqual(ai_config.allocation_mode(), "rule")

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

    def test_only_users_with_ai_connection_permission_can_save_and_view_redacted_connection(self):
        self.client.force_authenticate(self.hr)
        self.assertEqual(self.client.get("/api/ai-connection/").status_code, 403)

        self.client.force_authenticate(self.admin)
        payload = {
            "api_style": "chat_json",
            "model_name": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-test-secret",
        }
        response = self.client.patch("/api/ai-connection/", payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["api_key_configured"])
        self.assertNotIn("api_key", response.data)
        self.assertNotIn("profile", response.data)
        self.assertNotIn("profiles", response.data)
        self.assertNotIn("sk-test-secret", str(response.data))
        stored = m.Config.objects.get(key="ai_connection_api_key").value
        self.assertNotEqual(stored, "sk-test-secret")
        model_config = ai_config.get_ai_model_config()
        self.assertEqual(model_config.model_name, "deepseek-v4-pro")
        self.assertEqual(model_config.api_key, "sk-test-secret")

    def test_admin_can_discover_models_and_hr_cannot(self):
        self.client.force_authenticate(self.hr)
        denied = self.client.post(
            "/api/ai-connection/models/",
            {"base_url": "https://model.internal/v1"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

        self.client.force_authenticate(self.admin)
        with patch(
            "apps.api.views.ai_service.list_available_models",
            return_value=["deepseek-v4", "glm-4.7"],
        ) as discover:
            response = self.client.post(
                "/api/ai-connection/models/",
                {
                    "base_url": "https://model.internal/v1",
                    "api_key": "temporary-token",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["models"], ["deepseek-v4", "glm-4.7"])
        discover.assert_called_once_with(
            base_url="https://model.internal/v1", api_key="temporary-token"
        )
        self.assertNotIn("temporary-token", str(response.data))

    def test_ai_connection_allows_empty_access_token(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            "/api/ai-connection/",
            {
                "api_style": "chat_json",
                "model_name": "glm-4.7",
                "base_url": "https://model.internal/v1",
                "clear_api_key": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["api_key_configured"])
        self.assertEqual(ai_config.get_ai_model_config().api_key, "")

    def test_changing_base_url_without_new_token_clears_saved_token(self):
        self.client.force_authenticate(self.admin)
        first = self.client.patch(
            "/api/ai-connection/",
            {
                "api_style": "chat_json",
                "model_name": "deepseek-v4",
                "base_url": "https://model.internal/v1",
                "api_key": "bound-secret",
            },
            format="json",
        )

        changed = self.client.patch(
            "/api/ai-connection/",
            {
                "base_url": "https://another-model.internal/v1",
                "api_key": "",
            },
            format="json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.data["api_key_configured"])
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.data["api_key_configured"])
        self.assertFalse(
            m.Config.objects.filter(key="ai_connection_api_key").exists()
        )

    def test_role_granted_ai_connection_permission_can_manage_connection(self):
        permission = Permission.objects.get(
            codename=permission_codename("settings.manage_ai_connection")
        )
        ai_operator = Group.objects.create(name="AI 模型管理员")
        ai_operator.permissions.add(permission)
        user = User.objects.create_user(
            username="ai-operator", password="pass", role=User.ROLE_HR
        )
        user.groups.add(ai_operator)
        self.client.force_authenticate(user)

        response = self.client.get("/api/ai-connection/")

        self.assertEqual(response.status_code, 200)
        update_response = self.client.patch(
            "/api/ai-connection/",
            {
                "api_style": "chat_json",
                "model_name": "delegated-model",
                "base_url": "https://model.internal/v1",
                "api_key": "delegated-test-key",
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, 200)
        with patch(
            "apps.api.views.ai_service.test_model_connection",
            return_value={
                "model_name": "delegated-model",
                "api_style": "chat_json",
                "base_url": "https://api.deepseek.com",
            },
        ):
            test_response = self.client.post("/api/ai-connection/test/")

        self.assertEqual(test_response.status_code, 200)
        self.assertTrue(test_response.data["ok"])

    def test_admin_can_test_ai_connection(self):
        self.client.force_authenticate(self.admin)
        config_response = self.client.patch(
            "/api/ai-connection/",
            {
                "api_style": "responses",
                "model_name": "gpt-test",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            },
            format="json",
        )
        self.assertEqual(config_response.status_code, 200)
        with patch(
            "apps.api.views.ai_service.test_model_connection",
            return_value={
                "model_name": "deepseek-v4-pro",
                "api_style": "chat_json",
                "base_url": "https://api.deepseek.com",
            },
        ):
            response = self.client.post("/api/ai-connection/test/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertNotIn("api_key", response.data)

    def test_environment_key_never_enables_ai_connection(self):
        self.client.force_authenticate(self.admin)
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "env-secret"}, clear=False):
            response = self.client.get("/api/ai-connection/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["api_key_configured"])
        self.assertFalse(ai_config.is_ai_enabled())

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
        self.assertIn("settings.manage_ai_connection", codes)


class SchoolRuleConfigApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin-school-rule", password="pass", role=User.ROLE_ADMIN
        )
        self.admin.groups.add(Group.objects.get(name="管理员"))
        self.client.force_authenticate(self.admin)

    def test_school_tag_crud_endpoint_creates_tag_dictionary_item(self):
        response = self.client.post(
            "/api/school-tags/",
            {
                "code": "A",
                "name": "平台A",
                "is_default": False,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "A")
        self.assertEqual(response.data["name"], "平台A")
        self.assertTrue(m.SchoolTag.objects.filter(code="A", name="平台A").exists())

    def test_school_tag_rule_accepts_first_and_highest_tag_ids(self):
        first_tag = m.SchoolTag.objects.create(code="A", name="平台A")
        highest_tag = m.SchoolTag.objects.create(code="B", name="平台B")

        response = self.client.post(
            "/api/school-tag-rules/",
            {
                "name": "重点院校组合",
                "priority": 10,
                "is_active": True,
                "first_degree_tag_ids": [first_tag.id],
                "highest_degree_tag_ids": [highest_tag.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["first_degree_tags"][0]["id"], first_tag.id)
        self.assertEqual(response.data["highest_degree_tags"][0]["id"], highest_tag.id)
        self.assertTrue(
            m.SchoolTagRuleTag.objects.filter(
                rule_id=response.data["id"],
                school_tag=first_tag,
                degree_type=m.SchoolTagRuleTag.DEGREE_FIRST,
            ).exists()
        )

    def test_active_school_tag_rule_requires_first_and_highest_tags(self):
        first_tag = m.SchoolTag.objects.create(code="A", name="平台A")

        response = self.client.post(
            "/api/school-tag-rules/",
            {
                "name": "缺少最高学历标签",
                "priority": 10,
                "is_active": True,
                "first_degree_tag_ids": [first_tag.id],
                "highest_degree_tag_ids": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("highest_degree_tag_ids", response.data)

    def test_school_tag_rule_model_no_longer_keeps_legacy_json_fields(self):
        field_names = {field.name for field in m.SchoolTagRule._meta.get_fields()}

        self.assertNotIn("first_degree_tags", field_names)
        self.assertNotIn("highest_degree_tags", field_names)

    def test_school_tag_and_rule_header_filters(self):
        default_tag = m.SchoolTag.objects.create(
            code="NON_TARGET", name="非目标院校", is_default=True, is_active=True
        )
        other_tag = m.SchoolTag.objects.create(
            code="TARGET", name="目标院校", is_default=False, is_active=True
        )
        rule = m.SchoolTagRule.objects.create(name="默认准入规则", priority=8, is_active=True)
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=default_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_FIRST,
        )
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=other_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_HIGHEST,
        )

        tag_response = self.client.get(
            "/api/school-tags/", {"code": "NON", "is_default": "true"}
        )
        rule_response = self.client.get(
            "/api/school-tag-rules/", {"name": "默认", "priority": "8", "is_active": "true"}
        )

        self.assertEqual(tag_response.status_code, 200)
        self.assertEqual([item["id"] for item in tag_response.data["results"]], [default_tag.id])
        self.assertEqual(rule_response.status_code, 200)
        self.assertEqual([item["id"] for item in rule_response.data["results"]], [rule.id])


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
                "highest_major": "计算机",
                "current_rank": 1,
                "current_entity": "GW",
                "current_position_name": "后端",
                "current_job_category": "技术",
                "school_tag": "平台A",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [keep.id])
        self.assertEqual(response.data["results"][0]["highest_major"], "计算机")

    def test_candidate_selector_filters_and_options_use_current_display_values(self):
        school_tag = m.SchoolTag.objects.create(code="TARGET", name="目标院校")
        department = m.Department.objects.create(name="研发中心", level=2)
        job = m.Job.objects.create(
            department=department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )
        keep = m.Candidate.objects.create(
            identity_hash="candidate-selector-keep",
            name="选择器候选人",
            phone="13830000901",
            highest_major="计算机科学与技术",
            highest_degree_tag=school_tag,
        )
        keep_resume = m.Resume.objects.create(
            candidate=keep,
            apply_id="SELECT001",
            entity="GW",
            position_name="后端工程师",
            volunteer_rank=2,
            job_category="技术类",
            job=job,
        )
        m.CandidateWorkflow.objects.create(
            candidate=keep,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=keep_resume,
            current_rank=2,
        )
        drop = m.Candidate.objects.create(
            identity_hash="candidate-selector-drop",
            name="其他选择器候选人",
            phone="13830000902",
            highest_major="市场营销",
        )
        drop_resume = m.Resume.objects.create(
            candidate=drop,
            apply_id="SELECT002",
            entity="YLS",
            position_name="产品经理",
            volunteer_rank=1,
            job_category="产品类",
        )
        m.CandidateWorkflow.objects.create(
            candidate=drop,
            status=m.CandidateWorkflow.STATUS_PENDING,
            current_resume=drop_resume,
            current_rank=1,
        )

        options_response = self.client.get("/api/candidates/filter-options/")
        filter_response = self.client.get(
            "/api/candidates/",
            {
                "highest_major_in": "计算机科学与技术",
                "current_rank_in": "2",
                "current_entity_in": "GW",
                "current_position_name_in": "后端工程师",
                "job_department_name_in": "研发中心",
                "current_job_category_in": "技术类",
                "school_tag_in": "目标院校",
            },
        )

        self.assertEqual(options_response.status_code, 200)
        option_values = {
            key: [item["value"] for item in items]
            for key, items in options_response.data.items()
        }
        self.assertEqual(option_values["highest_major"], ["市场营销", "计算机科学与技术"])
        self.assertEqual(option_values["current_rank"], ["1", "2"])
        self.assertIn("GW", option_values["current_entity"])
        self.assertIn("后端工程师", option_values["current_position_name"])
        self.assertIn("研发中心", option_values["job_department_name"])
        self.assertIn("技术类", option_values["current_job_category"])
        self.assertIn("目标院校", option_values["school_tag"])
        self.assertEqual(filter_response.status_code, 200)
        self.assertEqual([item["id"] for item in filter_response.data["results"]], [keep.id])

    def test_candidate_school_tag_filter_matches_manual_non_target_tag(self):
        non_target_tag = m.SchoolTag.objects.create(
            code="NON_TARGET",
            name="非目标院校",
            is_default=False,
            is_active=True,
        )
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-manual-non-target",
            name="未知院校候选人",
            phone="13830000100",
            first_degree_school="未收录大学",
            highest_degree_school="未收录大学",
        )
        m.Resume.objects.create(
            candidate=candidate,
            apply_id="UNKNOWN-SCHOOL",
            position_name="后端工程师",
            volunteer_rank=1,
        )

        classify_school.run()
        candidate.refresh_from_db()
        response = self.client.get("/api/candidates/", {"school_tag": "非目标院校"})

        self.assertEqual(candidate.first_degree_tag, non_target_tag)
        self.assertEqual(candidate.highest_degree_tag, non_target_tag)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [candidate.id])
        self.assertEqual(response.data["results"][0]["school_tag"], "非目标院校")

    def test_candidate_list_exposes_workflow_merge_fields_and_assignment_reason(self):
        department = m.Department.objects.create(name="研发中心", level=2)
        contact = m.Contact.objects.create(
            name="二级接口人",
            employee_no="L2200",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-merge-assignment",
            name="分配候选人",
            phone="13830000001",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="MERGE001",
            position_name="后端工程师",
            volunteer_rank=1,
            job_category="技术类",
            category_reason="岗位名命中",
        )
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=resume,
            current_rank=1,
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
            department=department,
            contact=contact,
            match_reason="院校准入；分配至研发中心/二级接口人",
        )

        response = self.client.get("/api/candidates/", {"current_apply_id": "MERGE001"})

        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertEqual(row["current_apply_id"], "MERGE001")
        self.assertEqual(row["job_department_name"], "研发中心")
        self.assertEqual(row["workflow_status"], m.CandidateWorkflow.STATUS_IN_PROGRESS)
        self.assertEqual(row["reason_type"], "assignment")
        self.assertEqual(row["reason_text"], "院校准入；分配至研发中心/二级接口人")
        self.assertEqual(row["attempts"][0]["match_reason"], "院校准入；分配至研发中心/二级接口人")

    def test_candidate_list_exposes_preview_resume_with_file_fallback(self):
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-preview-fallback",
            name="预览候选人",
            phone="13830000002",
        )
        current_resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="NOFILE",
            position_name="当前无文件岗位",
            volunteer_rank=1,
        )
        file_resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="HASFILE",
            position_name="有文件岗位",
            volunteer_rank=2,
            resume_file="预览候选人（HASFILE）.pdf",
        )
        m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=current_resume,
            current_rank=1,
        )

        response = self.client.get("/api/candidates/", {"name": "预览候选人"})

        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertEqual(row["current_resume"]["id"], current_resume.id)
        self.assertEqual(row["preview_resume"]["id"], file_resume.id)
        self.assertEqual(row["preview_resume"]["resume_file"], "预览候选人（HASFILE）.pdf")

    def test_candidate_list_filters_by_blocked_workflow_merge_fields(self):
        department = m.Department.objects.create(name="研发中心", level=2)
        keep = m.Candidate.objects.create(
            identity_hash="candidate-merge-blocked",
            name="阻塞候选人",
            phone="13830000002",
        )
        keep_resume = m.Resume.objects.create(
            candidate=keep,
            apply_id="BLOCK001",
            position_name="后端工程师",
            volunteer_rank=1,
        )
        job = m.Job.objects.create(
            department=department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )
        keep_resume.job = job
        keep_resume.save(update_fields=["job"])
        m.CandidateWorkflow.objects.create(
            candidate=keep,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=keep_resume,
            current_rank=1,
            block_reason=m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND,
            block_detail="二级部门研发中心缺少启用接口人",
        )
        drop = m.Candidate.objects.create(
            identity_hash="candidate-merge-drop",
            name="其他候选人",
            phone="13830000003",
        )
        drop_resume = m.Resume.objects.create(
            candidate=drop,
            apply_id="DROP001",
            position_name="产品经理",
            volunteer_rank=1,
        )
        m.CandidateWorkflow.objects.create(
            candidate=drop,
            status=m.CandidateWorkflow.STATUS_ARCHIVED,
            current_resume=drop_resume,
            current_rank=1,
            archive_reason=m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED,
            archive_detail="未匹配岗位",
        )

        response = self.client.get(
            "/api/candidates/",
            {
                "current_apply_id": "BLOCK",
                "job_department_name": "研发",
                "workflow_status": m.CandidateWorkflow.STATUS_IN_PROGRESS,
                "reason_type": "block",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], keep.id)
        self.assertEqual(row["reason_type"], "block")
        self.assertIn("研发中心", row["reason_text"])

    def test_candidate_list_filters_by_multiple_workflow_statuses(self):
        pending = m.Candidate.objects.create(
            identity_hash="candidate-workflow-pending",
            name="待处理候选人",
            phone="13830000004",
        )
        archived = m.Candidate.objects.create(
            identity_hash="candidate-workflow-archived",
            name="归档候选人",
            phone="13830000005",
        )
        passed = m.Candidate.objects.create(
            identity_hash="candidate-workflow-passed",
            name="通过候选人",
            phone="13830000006",
        )
        m.CandidateWorkflow.objects.create(
            candidate=archived,
            status=m.CandidateWorkflow.STATUS_ARCHIVED,
        )
        m.CandidateWorkflow.objects.create(
            candidate=passed,
            status=m.CandidateWorkflow.STATUS_PASSED,
        )

        response = self.client.get(
            "/api/candidates/",
            {
                "workflow_status": ",".join(
                    [
                        m.CandidateWorkflow.STATUS_PENDING,
                        m.CandidateWorkflow.STATUS_ARCHIVED,
                    ]
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        result_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(result_ids, {pending.id, archived.id})

    def test_candidate_list_uses_current_resume_department_when_history_attempt_exists(self):
        old_department = m.Department.objects.create(name="旧部门", level=2)
        new_department = m.Department.objects.create(name="新部门", level=2)
        old_contact = m.Contact.objects.create(
            name="旧接口人",
            employee_no="L2300",
            department=old_department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-current-department",
            name="当前志愿候选人",
            phone="13830000004",
        )
        old_resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="OLD001",
            position_name="测试工程师",
            volunteer_rank=1,
        )
        current_resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="CUR001",
            position_name="后端工程师",
            volunteer_rank=2,
        )
        current_job = m.Job.objects.create(
            department=new_department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )
        current_resume.job = current_job
        current_resume.save(update_fields=["job"])
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=current_resume,
            current_rank=2,
            block_reason=m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND,
            block_detail="当前志愿缺少新部门接口人",
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=old_resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_REJECTED,
            department=old_department,
            contact=old_contact,
            match_reason="历史分配至旧部门",
        )

        response = self.client.get("/api/candidates/", {"current_apply_id": "CUR001"})

        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertEqual(row["current_apply_id"], "CUR001")
        self.assertEqual(row["job_department_name"], "新部门")
        self.assertEqual(row["reason_type"], "block")
        self.assertIn("新部门", row["reason_text"])

    def test_candidate_list_filters_follow_current_summary_not_history_attempts(self):
        old_department = m.Department.objects.create(name="旧部门", level=2)
        new_department = m.Department.objects.create(name="新部门", level=2)
        old_contact = m.Contact.objects.create(
            name="旧接口人",
            employee_no="L2301",
            department=old_department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-current-filter-summary",
            name="当前筛选候选人",
            phone="13830000005",
        )
        old_resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="OLD002",
            position_name="测试工程师",
            volunteer_rank=1,
            category_reason="历史分类原因",
        )
        current_resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="CUR002",
            position_name="后端工程师",
            volunteer_rank=2,
        )
        current_job = m.Job.objects.create(
            department=new_department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )
        current_resume.job = current_job
        current_resume.save(update_fields=["job"])
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=current_resume,
            current_rank=2,
            block_reason=m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND,
            block_detail="当前志愿缺少新部门接口人",
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=old_resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_REJECTED,
            department=old_department,
            contact=old_contact,
            match_reason="历史分配至旧部门",
        )

        old_department_response = self.client.get(
            "/api/candidates/", {"job_department_name": "旧部门"}
        )
        assignment_response = self.client.get(
            "/api/candidates/", {"reason_type": "assignment"}
        )
        classification_response = self.client.get(
            "/api/candidates/", {"reason_type": "classification"}
        )
        current_response = self.client.get(
            "/api/candidates/",
            {"job_department_name": "新部门", "reason_type": "block"},
        )

        self.assertEqual(old_department_response.status_code, 200)
        self.assertEqual(old_department_response.data["count"], 0)
        self.assertEqual(assignment_response.data["count"], 0)
        self.assertEqual(classification_response.data["count"], 0)
        self.assertEqual(current_response.data["count"], 1)
        self.assertEqual(current_response.data["results"][0]["id"], candidate.id)

    def test_candidate_list_current_filters_fallback_to_first_resume_when_workflow_has_no_current_resume(self):
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-current-filter-fallback",
            name="当前字段回退候选人",
            phone="13830000006",
        )
        m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_PENDING,
        )
        m.Resume.objects.create(
            candidate=candidate,
            apply_id="FALL001",
            entity="GW",
            position_name="后端工程师",
            volunteer_rank=1,
            job_category="技术类",
        )
        m.Resume.objects.create(
            candidate=candidate,
            apply_id="FALL002",
            entity="YLS",
            position_name="产品经理",
            volunteer_rank=2,
            job_category="产品类",
        )

        response = self.client.get(
            "/api/candidates/",
            {
                "current_apply_id": "FALL001",
                "current_entity": "GW",
                "current_position_name": "后端",
                "current_job_category": "技术",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], candidate.id)
        self.assertEqual(row["current_apply_id"], "FALL001")
        self.assertEqual(row["current_resume"]["position_name"], "后端工程师")

    def test_candidate_list_filters_by_system_resume_status(self):
        tag = m.SchoolTag.objects.create(code="TARGET", name="目标院校")
        raw = m.Candidate.objects.create(
            identity_hash="candidate-system-raw",
            name="原始候选人",
            phone="13810000000",
        )
        m.Resume.objects.create(candidate=raw, apply_id="RAW001", position_name="后端")
        allocated = m.Candidate.objects.create(
            identity_hash="candidate-system-allocated",
            name="已分配候选人",
            phone="13810000001",
            first_degree_tag=tag,
            highest_degree_tag=tag,
        )
        allocated_resume = m.Resume.objects.create(
            candidate=allocated,
            apply_id="ALLOC001",
            position_name="后端",
            volunteer_rank=1,
            job_category="技术类",
        )
        department = m.Department.objects.create(name="研发中心", level=2)
        contact = m.Contact.objects.create(
            name="二级接口人",
            employee_no="L2100",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        workflow = m.CandidateWorkflow.objects.create(
            candidate=allocated,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=allocated_resume,
            current_rank=1,
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=allocated_resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
            department=department,
            contact=contact,
        )

        response = self.client.get(
            "/api/candidates/", {"system_status": "allocated"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], allocated.id)
        self.assertEqual(response.data["results"][0]["system_status"], "allocated")
        self.assertEqual(
            response.data["results"][0]["system_status_label"], "已分配"
        )

        workflow.status = m.CandidateWorkflow.STATUS_PASSED
        workflow.save(update_fields=["status", "updated_at"])
        attempt = workflow.attempts.get()
        attempt.status = m.AssignmentAttempt.STATUS_PASSED
        attempt.save(update_fields=["status", "updated_at"])
        passed_response = self.client.get(
            "/api/candidates/", {"system_status": "screening_passed"}
        )
        self.assertEqual(
            passed_response.data["results"][0]["system_status_label"], "通过"
        )

        workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
        workflow.save(update_fields=["status", "updated_at"])
        attempt.status = m.AssignmentAttempt.STATUS_REJECTED
        attempt.save(update_fields=["status", "updated_at"])
        rejected_response = self.client.get(
            "/api/candidates/", {"system_status": "screening_rejected"}
        )
        self.assertEqual(
            rejected_response.data["results"][0]["system_status_label"], "不通过"
        )

    def test_workflow_list_filters_by_status_search_and_current_position(self):
        keep_candidate = m.Candidate.objects.create(
            identity_hash="candidate-workflow-keep",
            name="归档候选人",
            phone="13820000000",
        )
        keep_resume = m.Resume.objects.create(
            candidate=keep_candidate,
            apply_id="WF001",
            position_name="后端工程师",
            volunteer_rank=1,
        )
        keep = m.CandidateWorkflow.objects.create(
            candidate=keep_candidate,
            status=m.CandidateWorkflow.STATUS_ARCHIVED,
            current_resume=keep_resume,
            current_rank=1,
            archive_reason=m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED,
            archive_detail="未匹配岗位",
        )
        drop_candidate = m.Candidate.objects.create(
            identity_hash="candidate-workflow-drop",
            name="进行中候选人",
            phone="13920000000",
        )
        drop_resume = m.Resume.objects.create(
            candidate=drop_candidate,
            apply_id="WF002",
            position_name="产品经理",
            volunteer_rank=1,
        )
        m.CandidateWorkflow.objects.create(
            candidate=drop_candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=drop_resume,
            current_rank=1,
        )
        archived_drop_candidate = m.Candidate.objects.create(
            identity_hash="candidate-workflow-archived-drop",
            name="归档候选人二",
            phone="13720000000",
        )
        archived_drop_resume = m.Resume.objects.create(
            candidate=archived_drop_candidate,
            apply_id="WF003",
            position_name="产品经理",
            volunteer_rank=1,
        )
        m.CandidateWorkflow.objects.create(
            candidate=archived_drop_candidate,
            status=m.CandidateWorkflow.STATUS_ARCHIVED,
            current_resume=archived_drop_resume,
            current_rank=1,
            archive_reason=m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED,
            archive_detail="未匹配岗位",
        )

        response = self.client.get(
            "/api/workflows/",
            {
                "status": m.CandidateWorkflow.STATUS_ARCHIVED,
                "search": "归档",
                "current_position_name": "后端",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], keep.id)
        self.assertEqual(response.data["results"][0]["current_position_name"], "后端工程师")

    def test_workflow_list_falls_back_to_latest_attempt_resume(self):
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-workflow-fallback",
            name="历史候选人",
            phone="13820000003",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="WF004",
            position_name="算法工程师",
            volunteer_rank=2,
        )
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_ARCHIVED,
            archive_reason=m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED,
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_CANCELLED,
        )

        response = self.client.get("/api/workflows/", {"status": "archived"})

        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertEqual(row["current_resume"], resume.id)
        self.assertEqual(row["current_rank"], 2)
        self.assertEqual(row["current_apply_id"], "WF004")
        self.assertEqual(row["current_position_name"], "算法工程师")

    def test_candidate_search_matches_name_full_pinyin_and_initials(self):
        keep = m.Candidate.objects.create(
            identity_hash="candidate-pinyin-keep",
            name="张三",
            phone="13800000001",
        )
        m.Candidate.objects.create(
            identity_hash="candidate-pinyin-drop",
            name="李四",
            phone="13900000002",
        )

        full_response = self.client.get("/api/candidates/", {"search": "zhangsan"})
        initials_response = self.client.get("/api/candidates/", {"search": "zs"})

        self.assertEqual(full_response.status_code, 200)
        self.assertEqual(initials_response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in full_response.data["results"]],
            [keep.id],
        )
        self.assertEqual(
            [item["id"] for item in initials_response.data["results"]],
            [keep.id],
        )

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

    def test_job_selector_options_and_exact_multi_value_filters(self):
        department = m.Department.objects.create(name="研发中心", level=2)
        keep = m.Job.objects.create(
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

        options_response = self.client.get("/api/jobs/filter-options/")
        filter_response = self.client.get(
            "/api/jobs/",
            {
                "entity_in": "GW,YLS",
                "category_in": "技术类",
                "job_family_in": "研发",
                "department_name_in": "研发中心",
                "location_in": "深圳",
                "education_in": "本科",
            },
        )

        self.assertEqual(options_response.status_code, 200)
        self.assertEqual(filter_response.status_code, 200)
        category_options = {
            item["value"]: item for item in options_response.data["category"]
        }
        department_options = {
            item["value"]: item
            for item in options_response.data["department_name"]
        }
        self.assertIn("jishulei", category_options["技术类"]["search_text"])
        self.assertIn("jsl", category_options["技术类"]["search_text"])
        self.assertIn("yanfazhongxin", department_options["研发中心"]["search_text"])
        self.assertEqual(
            [item["id"] for item in filter_response.data["results"]], [keep.id]
        )

    def test_job_name_filters_support_full_pinyin_and_initials(self):
        keep = m.Job.objects.create(
            entity="GW",
            public_name="后端开发",
            position_name="后端工程师",
            category="技术类",
            is_active=True,
        )
        m.Job.objects.create(
            entity="YLS",
            public_name="产品运营",
            position_name="产品经理",
            category="产品类",
            is_active=True,
        )

        full_response = self.client.get(
            "/api/jobs/", {"public_name": "houduankaifa"}
        )
        initials_response = self.client.get(
            "/api/jobs/", {"position_name": "hdgcs"}
        )

        self.assertEqual(full_response.status_code, 200)
        self.assertEqual(initials_response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in full_response.data["results"]], [keep.id]
        )
        self.assertEqual(
            [item["id"] for item in initials_response.data["results"]], [keep.id]
        )

    def test_job_create_and_update_maintains_demand_majors(self):
        department = m.Department.objects.create(name="研发中心", level=2)

        create_response = self.client.post(
            "/api/jobs/",
            {
                "entity": "GW",
                "department": department.id,
                "public_name": "后端开发",
                "position_name": "后端工程师",
                "category": "技术类",
                "major_names": ["计算机", "软件工程"],
                "headcount": 3,
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data["majors"], ["计算机", "软件工程"])
        job_id = create_response.data["id"]
        self.assertEqual(
            list(
                m.JobMajor.objects.filter(job_id=job_id).values_list(
                    "major", flat=True
                )
            ),
            ["计算机", "软件工程"],
        )

        update_response = self.client.patch(
            f"/api/jobs/{job_id}/",
            {"major_names": ["数学"]},
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.data["majors"], ["数学"])
        self.assertEqual(
            list(
                m.JobMajor.objects.filter(job_id=job_id).values_list(
                    "major", flat=True
                )
            ),
            ["数学"],
        )

    def test_job_rejects_non_secondary_department(self):
        root_department = m.Department.objects.create(name="集团总部", level=1)

        response = self.client.post(
            "/api/jobs/",
            {
                "entity": "GW",
                "department": root_department.id,
                "public_name": "后端开发",
                "position_name": "后端工程师",
                "category": "技术类",
                "major_names": ["计算机"],
                "headcount": 3,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("department", response.data)

    def test_delete_job_deactivates_instead_of_removing_record(self):
        department = m.Department.objects.create(name="研发中心", level=2)
        job = m.Job.objects.create(
            entity="GW",
            department=department,
            public_name="后端开发",
            position_name="后端工程师",
            category="技术类",
            headcount=3,
            is_active=True,
        )

        response = self.client.delete(f"/api/jobs/{job.id}/")

        self.assertEqual(response.status_code, 204)
        job.refresh_from_db()
        self.assertFalse(job.is_active)

    def test_job_list_defaults_to_active_and_can_filter_inactive(self):
        m.Job.objects.create(
            entity="GW",
            public_name="启用岗位",
            position_name="后端工程师",
            category="技术类",
            is_active=True,
        )
        inactive = m.Job.objects.create(
            entity="GW",
            public_name="停用岗位",
            position_name="旧岗位",
            category="技术类",
            is_active=False,
        )

        active_response = self.client.get("/api/jobs/")
        inactive_response = self.client.get("/api/jobs/", {"is_active": "false"})

        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(inactive_response.status_code, 200)
        self.assertEqual(active_response.data["count"], 1)
        self.assertEqual(inactive_response.data["count"], 1)
        self.assertEqual(inactive_response.data["results"][0]["id"], inactive.id)

    def test_school_header_filters_cover_visible_columns(self):
        m.School.objects.create(name="南京大学", platform="平台A", province="江苏")
        m.School.objects.create(name="北京大学", platform="平台B", province="北京")

        response = self.client.get("/api/schools/", {"province": "江苏"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "南京大学")

    def test_school_name_pinyin_search_and_platform_selector(self):
        keep = m.School.objects.create(
            name="南京大学", platform="双一流", province="江苏"
        )
        m.School.objects.create(name="北京大学", platform="985", province="北京")

        full_response = self.client.get("/api/schools/", {"name": "nanjingdaxue"})
        initials_response = self.client.get("/api/schools/", {"name": "njdx"})
        selector_response = self.client.get(
            "/api/schools/", {"platform_in": "双一流"}
        )
        options_response = self.client.get("/api/schools/filter-options/")

        self.assertEqual(full_response.status_code, 200)
        self.assertEqual(initials_response.status_code, 200)
        self.assertEqual(selector_response.status_code, 200)
        self.assertEqual(options_response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in full_response.data["results"]], [keep.id]
        )
        self.assertEqual(
            [item["id"] for item in initials_response.data["results"]], [keep.id]
        )
        self.assertEqual(
            [item["id"] for item in selector_response.data["results"]], [keep.id]
        )
        options = {item["value"]: item for item in options_response.data["platform"]}
        self.assertIn("shuangyiliu", options["双一流"]["search_text"])
        keep.refresh_from_db()
        self.assertEqual(keep.name_pinyin, "nanjingdaxue")
        self.assertEqual(keep.name_pinyin_initials, "njdx")

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

    def test_contact_department_selector_options_and_multi_filter(self):
        research = m.Department.objects.create(name="研发二部", level=2)
        product = m.Department.objects.create(name="产品二部", level=2)
        keep = m.Contact.objects.create(
            name="王五",
            employee_no="E1001",
            department=research,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        m.Contact.objects.create(
            name="赵六",
            employee_no="E2001",
            department=product,
            contact_level=m.Contact.LEVEL_TERTIARY,
            is_active=True,
        )

        options_response = self.client.get("/api/contacts/filter-options/")
        filter_response = self.client.get(
            "/api/contacts/", {"department_in": f"{research.id},999999"}
        )

        self.assertEqual(options_response.status_code, 200)
        self.assertEqual(filter_response.status_code, 200)
        options = {
            item["value"]: item for item in options_response.data["department"]
        }
        self.assertIn(research.id, options)
        self.assertIn("yanfaerbu", options[research.id]["search_text"])
        self.assertEqual(
            [item["id"] for item in filter_response.data["results"]], [keep.id]
        )

    def test_contact_name_and_bound_user_support_full_pinyin_and_initials(self):
        department = m.Department.objects.create(name="研发二部", level=2)
        contact = m.Contact.objects.create(
            name="王五",
            employee_no="PINYIN001",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        user = User.objects.create_user(
            username="PINYIN001",
            password="pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=contact,
        )

        full_response = self.client.get("/api/contacts/", {"name": "wangwu"})
        initials_response = self.client.get("/api/contacts/", {"name": "ww"})
        user_response = self.client.get("/api/users/", {"contact_name": "wangwu"})

        self.assertEqual([item["id"] for item in full_response.data["results"]], [contact.id])
        self.assertEqual([item["id"] for item in initials_response.data["results"]], [contact.id])
        self.assertEqual([item["id"] for item in user_response.data["results"]], [user.id])
        contact.refresh_from_db()
        self.assertEqual(contact.name_pinyin, "wangwu")
        self.assertEqual(contact.name_pinyin_initials, "ww")

    def test_candidate_contact_filter_supports_contact_name_pinyin(self):
        department = m.Department.objects.create(name="技术二部", level=2)
        contact = m.Contact.objects.create(
            name="王五",
            employee_no="PINYIN002",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-contact-pinyin",
            name="候选人甲",
            phone="13812340000",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="PINYIN-APPLY",
            position_name="后端工程师",
            volunteer_rank=1,
        )
        workflow = m.CandidateWorkflow.objects.create(
            candidate=candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=resume,
            current_rank=1,
        )
        m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=resume,
            attempt_no=1,
            source=m.AssignmentAttempt.SOURCE_RULE,
            status=m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
            department=department,
            contact=contact,
        )

        response = self.client.get("/api/candidates/", {"contact_name": "ww"})

        self.assertEqual([item["id"] for item in response.data["results"]], [candidate.id])

    def test_candidate_filter_options_respect_contact_rbac_scope(self):
        department = m.Department.objects.create(name="范围二部", level=2)
        own_contact = m.Contact.objects.create(
            name="本人接口人",
            employee_no="SCOPE001",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        other_contact = m.Contact.objects.create(
            name="其他接口人",
            employee_no="SCOPE002",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        contact_user = User.objects.create_user(
            username="SCOPE001",
            password="pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=own_contact,
        )
        contact_user.groups.add(Group.objects.get(name="二级接口人"))
        for index, (contact, position) in enumerate(
            [(own_contact, "可见岗位"), (other_contact, "不可见岗位")], start=1
        ):
            candidate = m.Candidate.objects.create(
                identity_hash=f"candidate-option-scope-{index}",
                name=f"范围候选人{index}",
                phone=f"1385555000{index}",
            )
            resume = m.Resume.objects.create(
                candidate=candidate,
                apply_id=f"SCOPE-APPLY-{index}",
                position_name=position,
                volunteer_rank=1,
            )
            workflow = m.CandidateWorkflow.objects.create(
                candidate=candidate,
                status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
                current_resume=resume,
                current_rank=1,
            )
            m.AssignmentAttempt.objects.create(
                workflow=workflow,
                resume=resume,
                attempt_no=1,
                source=m.AssignmentAttempt.SOURCE_RULE,
                status=m.AssignmentAttempt.STATUS_DISPATCHED_L2,
                department=department,
                contact=contact,
            )

        self.client.force_authenticate(contact_user)
        response = self.client.get("/api/candidates/filter-options/")

        values = [item["value"] for item in response.data["current_position_name"]]
        self.assertEqual(values, ["可见岗位"])

    def test_contact_and_school_pinyin_data_migration_populates_existing_rows(self):
        contact = m.Contact.objects.create(name="赵六", employee_no="MIGRATION001")
        school = m.School.objects.create(name="北京大学")
        m.Contact.objects.filter(pk=contact.pk).update(
            name_pinyin="", name_pinyin_initials=""
        )
        m.School.objects.filter(pk=school.pk).update(
            name_pinyin="", name_pinyin_initials=""
        )
        migration = importlib.import_module(
            "apps.core.migrations.0023_contact_school_name_pinyin"
        )

        migration.populate_name_pinyin(django_apps, None)

        contact.refresh_from_db()
        school.refresh_from_db()
        self.assertEqual((contact.name_pinyin, contact.name_pinyin_initials), ("zhaoliu", "zl"))
        self.assertEqual((school.name_pinyin, school.name_pinyin_initials), ("beijingdaxue", "bjdx"))


class CandidateExportApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.hr = User.objects.create_user(
            username="hr-export", password="pass", role=User.ROLE_HR
        )
        self.hr.groups.add(Group.objects.get(name="HR"))
        self.client.force_authenticate(self.hr)

    def test_candidate_export_returns_original_file_for_single_available_resume(self):
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
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(response["X-Export-Count"], "1")
        self.assertEqual(response["X-Export-Missing"], "0")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response.content.decode("utf-8"), "resume body")

    def test_candidate_export_returns_zip_when_any_resume_is_missing(self):
        with TemporaryDirectory() as media_root:
            resume_dir = Path(media_root) / "resumes"
            resume_dir.mkdir()
            (resume_dir / "张三（A1001）.txt").write_text("resume body", encoding="utf-8")
            candidate = m.Candidate.objects.create(
                identity_hash="candidate-export-missing",
                name="张三",
                phone="13800000000",
            )
            m.Resume.objects.create(
                candidate=candidate,
                apply_id="A1001",
                position_name="后端工程师",
                resume_file="张三（A1001）.txt",
            )
            m.Resume.objects.create(
                candidate=candidate,
                apply_id="A1002",
                position_name="算法工程师",
                resume_file="",
            )

            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.get(
                    "/api/candidates/export/", {"ids": str(candidate.id)}
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertEqual(response["X-Export-Count"], "1")
        self.assertEqual(response["X-Export-Missing"], "1")
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            self.assertIn("张三（A1001）.txt", zf.namelist())
            self.assertIn("缺失简历文件清单.txt", zf.namelist())

    def test_attempt_export_returns_original_file_for_single_available_resume(self):
        department = m.Department.objects.create(name="研发中心", level=2)
        contact = m.Contact.objects.create(
            name="二级接口人",
            employee_no="S9001",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        with TemporaryDirectory() as media_root:
            resume_dir = Path(media_root) / "resumes"
            resume_dir.mkdir()
            (resume_dir / "李四（B1001）.txt").write_text("attempt resume", encoding="utf-8")
            candidate = m.Candidate.objects.create(
                identity_hash="attempt-export",
                name="李四",
                phone="13900000000",
            )
            resume = m.Resume.objects.create(
                candidate=candidate,
                apply_id="B1001",
                position_name="产品经理",
                resume_file="李四（B1001）.txt",
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

            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.get(
                    "/api/workflow-attempts/export/", {"ids": str(attempt.id)}
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(response["X-Export-Count"], "1")
        self.assertEqual(response["X-Export-Missing"], "0")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response.content.decode("utf-8"), "attempt resume")


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

    def test_resume_preview_returns_pdf_type_and_inline_filename(self):
        with TemporaryDirectory() as media_root:
            resume_dir = Path(media_root) / "resumes"
            resume_dir.mkdir()
            (resume_dir / "张三（A1001）.pdf").write_bytes(b"%PDF-1.4\n%test\n")
            candidate = m.Candidate.objects.create(
                identity_hash="candidate-preview-pdf",
                name="张三",
                phone="13800000000",
            )
            resume = m.Resume.objects.create(
                candidate=candidate,
                apply_id="A1001",
                position_name="后端工程师",
                resume_file="张三（A1001）.pdf",
            )

            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.get(f"/api/resumes/{resume.id}/preview/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertIn(
            f"filename*=UTF-8''{quote('张三（A1001）.pdf')}",
            response["Content-Disposition"],
        )
        self.assertTrue(response.content.startswith(b"%PDF"))

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

    @patch("apps.api.views.execute_runs_sequence_task.delay")
    @patch("apps.api.views.runner.create_configured_run")
    @patch("apps.api.views.snapshot.take_snapshot")
    @patch("apps.api.views.import_files")
    def test_resume_upload_starts_one_run_with_configured_mode(
        self,
        mock_import_files,
        mock_take_snapshot,
        mock_create_run,
        mock_execute,
    ):
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-upload-modes", name="上传候选人", phone="13800000001"
        )
        ai_run = m.ProcessingRun.objects.create(step="resume_process", mode="ai")
        mock_import_files.return_value = {
            "candidates_created": 1,
            "candidates_updated": 0,
            "resumes_created": 1,
            "resumes_updated": 0,
            "_candidate_ids": [candidate.id],
        }
        mock_create_run.return_value = ai_run
        mock_execute.return_value = SimpleNamespace(id="upload-modes")

        response = self.client.post(
            "/api/import/",
            {"resume_package": SimpleUploadedFile("简历包.zip", b"zip")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202)
        mock_create_run.assert_called_once_with(
            "resume_process",
            scope={"candidate_ids": [candidate.id], "source": "resume_import"},
            created_by=self.hr,
        )
        mock_execute.assert_called_once_with([ai_run.id])
        self.assertEqual([item["mode"] for item in response.data["processing_runs"]], ["ai"])

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

    def test_replace_contacts_import_deactivates_old_contacts_and_users(self):
        old_department = m.Department.objects.create(name="旧部门", level=2)
        old_contact = m.Contact.objects.create(
            name="旧接口人",
            employee_no="OLD002",
            department=old_department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        old_user = User.objects.create_user(
            username="OLD002",
            password="pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=old_contact,
        )
        old_user.groups.add(Group.objects.get(name="二级接口人"))
        buf = BytesIO()
        pd.DataFrame(
            [
                {
                    "工号": "NEW002",
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
        old_contact.refresh_from_db()
        self.assertFalse(old_contact.is_active)
        old_user.refresh_from_db()
        self.assertFalse(old_user.is_active)
        self.assertEqual(old_user.contact_id, old_contact.id)

    @patch("apps.api.views.import_files")
    @patch("apps.api.views.snapshot.take_snapshot")
    def test_large_resume_package_reaches_import_service(
        self, mock_take_snapshot, mock_import_files
    ):
        mock_import_files.return_value = {
            "candidates_created": 0,
            "candidates_updated": 0,
            "resumes_created": 0,
            "resumes_updated": 0,
        }
        large_package = SimpleUploadedFile(
            "简历包.zip",
            b"x" * (4 * 1024 * 1024),
            content_type="application/zip",
        )

        response = self.client.post(
            "/api/import/",
            {"mode": "incremental", "resume_package": large_package},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        mock_take_snapshot.assert_called_once_with(label="上传简历前")
        mock_import_files.assert_called_once()


class ContactDeleteApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin-contact-delete", password="pass", role=User.ROLE_ADMIN
        )
        self.admin.groups.add(Group.objects.get(name="管理员"))
        self.client.force_authenticate(self.admin)

    def test_delete_contact_removes_contact_and_bound_user(self):
        department = m.Department.objects.create(name="技术二部", level=2)
        contact = m.Contact.objects.create(
            name="待删除接口人",
            employee_no="DEL001",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        user = User.objects.create_user(
            username="DEL001",
            password="pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=contact,
        )
        user.groups.add(Group.objects.get(name="二级接口人"))

        response = self.client.delete(f"/api/contacts/{contact.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(m.Contact.objects.filter(id=contact.id).exists())
        self.assertFalse(User.objects.filter(id=user.id).exists())

    def test_delete_contact_keeps_history_and_clears_contact_references(self):
        department = m.Department.objects.create(name="技术二部", level=2)
        contact = m.Contact.objects.create(
            name="有历史接口人",
            employee_no="DEL002",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        candidate = m.Candidate.objects.create(
            identity_hash="contact-delete-history",
            name="张三",
            phone="13800000000",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="A1001",
            position_name="后端工程师",
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
            contact_name_snapshot=contact.name,
            contact_employee_no_snapshot=contact.employee_no,
            created_by=self.admin,
        )
        handoff = m.AssignmentHandoff.objects.create(
            attempt=attempt,
            action=m.AssignmentHandoff.ACTION_HR_DISPATCH,
            to_department=department,
            to_contact=contact,
            to_department_name_snapshot=department.name,
            to_contact_name_snapshot=contact.name,
            to_contact_employee_no_snapshot=contact.employee_no,
            created_by_username_snapshot=self.admin.username,
            created_by=self.admin,
        )
        decision = m.AgentDispatchDecision.objects.create(
            workflow=workflow,
            resume=resume,
            recommendation=m.AgentDispatchDecision.RECOMMEND_DISPATCH,
            recommended_contact=contact,
            recommended_contact_name_snapshot=contact.name,
            recommended_contact_employee_no_snapshot=contact.employee_no,
        )

        response = self.client.delete(f"/api/contacts/{contact.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(m.Contact.objects.filter(id=contact.id).exists())
        attempt.refresh_from_db()
        handoff.refresh_from_db()
        decision.refresh_from_db()
        self.assertIsNone(attempt.contact_id)
        self.assertEqual(attempt.contact_name_snapshot, "有历史接口人")
        self.assertEqual(attempt.contact_employee_no_snapshot, "DEL002")
        self.assertIsNone(handoff.to_contact_id)
        self.assertEqual(handoff.to_contact_name_snapshot, "有历史接口人")
        self.assertEqual(handoff.to_contact_employee_no_snapshot, "DEL002")
        self.assertEqual(handoff.to_department_name_snapshot, "技术二部")
        self.assertEqual(handoff.created_by_username_snapshot, "admin-contact-delete")
        self.assertIsNone(decision.recommended_contact_id)
        self.assertEqual(decision.recommended_contact_name_snapshot, "有历史接口人")
        self.assertEqual(decision.recommended_contact_employee_no_snapshot, "DEL002")

    def test_contacts_list_defaults_to_active_contacts(self):
        department = m.Department.objects.create(name="技术二部", level=2)
        active = m.Contact.objects.create(
            name="启用接口人",
            employee_no="LIST001",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        m.Contact.objects.create(
            name="停用接口人",
            employee_no="LIST002",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=False,
        )

        response = self.client.get("/api/contacts/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [active.id])

    def test_contacts_list_can_filter_inactive_contacts(self):
        department = m.Department.objects.create(name="技术二部", level=2)
        m.Contact.objects.create(
            name="启用接口人",
            employee_no="LIST003",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        inactive = m.Contact.objects.create(
            name="停用接口人",
            employee_no="LIST004",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=False,
        )

        response = self.client.get("/api/contacts/", {"is_active": "false"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]], [inactive.id]
        )


class UserDeleteApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin-user-delete", password="pass", role=User.ROLE_ADMIN
        )
        self.admin.groups.add(Group.objects.get(name="管理员"))
        self.client.force_authenticate(self.admin)

    def test_delete_user_removes_record_and_token(self):
        user = User.objects.create_user(
            username="E9001", password="pass1234", role=User.ROLE_SECONDARY_CONTACT
        )
        token = Token.objects.create(user=user)

        response = self.client.delete(f"/api/users/{user.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(id=user.id).exists())
        self.assertFalse(Token.objects.filter(key=token.key).exists())

    def test_deleted_user_cannot_login(self):
        user = User.objects.create_user(
            username="E9002", password="pass1234", role=User.ROLE_SECONDARY_CONTACT
        )

        self.client.delete(f"/api/users/{user.id}/")
        response = self.client.post(
            "/api/auth/login/", {"username": "E9002", "password": "pass1234"}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_delete_user_removes_bound_contact_and_clears_history_references(self):
        department = m.Department.objects.create(name="技术二部", level=2)
        contact = m.Contact.objects.create(
            name="绑定接口人",
            employee_no="E9003",
            department=department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        user = User.objects.create_user(
            username="E9003",
            password="pass1234",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=contact,
        )
        user.groups.add(Group.objects.get(name="二级接口人"))
        candidate = m.Candidate.objects.create(
            identity_hash="user-delete-history",
            name="李四",
            phone="13900000000",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="A1002",
            position_name="算法工程师",
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
            contact_name_snapshot=contact.name,
            contact_employee_no_snapshot=contact.employee_no,
            created_by_username_snapshot=user.username,
            created_by=user,
        )
        handoff = m.AssignmentHandoff.objects.create(
            attempt=attempt,
            action=m.AssignmentHandoff.ACTION_HR_DISPATCH,
            to_department=department,
            to_contact=contact,
            to_department_name_snapshot=department.name,
            to_contact_name_snapshot=contact.name,
            to_contact_employee_no_snapshot=contact.employee_no,
            created_by_username_snapshot=user.username,
            created_by=user,
        )

        response = self.client.delete(f"/api/users/{user.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(id=user.id).exists())
        self.assertFalse(m.Contact.objects.filter(id=contact.id).exists())
        attempt.refresh_from_db()
        handoff.refresh_from_db()
        self.assertIsNone(attempt.contact_id)
        self.assertIsNone(attempt.created_by_id)
        self.assertEqual(attempt.contact_name_snapshot, "绑定接口人")
        self.assertEqual(attempt.contact_employee_no_snapshot, "E9003")
        self.assertEqual(attempt.created_by_username_snapshot, "E9003")
        self.assertIsNone(handoff.to_contact_id)
        self.assertIsNone(handoff.created_by_id)
        self.assertEqual(handoff.to_contact_name_snapshot, "绑定接口人")
        self.assertEqual(handoff.to_contact_employee_no_snapshot, "E9003")
        self.assertEqual(handoff.created_by_username_snapshot, "E9003")
