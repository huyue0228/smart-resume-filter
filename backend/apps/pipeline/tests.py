from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.core import models as m
from apps.pipeline import ai_config
from apps.pipeline.services import allocate


class AllocationDesignContractTests(TestCase):
    def setUp(self):
        self.department = m.Department.objects.create(name="技术部", level=2)
        self.contact = m.Contact.objects.create(
            name="二级接口人",
            employee_no="L2001",
            department=self.department,
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
            resume_file="张三（A1001）.pdf",
        )
        self.job = m.Job.objects.create(
            department=self.department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )

    def test_rule_allocation_passes_school_gate_when_no_active_rules(self):
        message = allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertIn("已生成 1 条候选人分配尝试", message)
        self.assertEqual(attempt.source, m.AssignmentAttempt.SOURCE_RULE)
        self.assertEqual(attempt.status, m.AssignmentAttempt.STATUS_PENDING_DISPATCH)
        self.assertIsNone(attempt.matched_rule)
        self.assertEqual(self.candidate.workflow.status, m.CandidateWorkflow.STATUS_IN_PROGRESS)

    def test_rule_allocation_skips_resume_when_required_major_not_matched(self):
        self.candidate.highest_major = "计算机科学与技术"
        self.candidate.save(update_fields=["highest_major"])
        m.JobMajor.objects.create(job=self.job, major="电气工程")
        next_resume = m.Resume.objects.create(
            candidate=self.candidate,
            apply_id="A1002",
            position_name="产品经理",
            volunteer_rank=2,
            resume_file="张三（A1002）.pdf",
        )
        next_job = m.Job.objects.create(
            department=self.department,
            public_name="产品经理",
            position_name="产品经理",
            category="产品类",
            headcount=1,
        )
        m.JobMajor.objects.create(job=next_job, major="计算机")

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.resume, next_resume)
        self.assertEqual(attempt.resume.job, next_job)

    def test_rule_allocation_allows_job_without_required_majors(self):
        self.candidate.highest_major = "材料科学与工程"
        self.candidate.save(update_fields=["highest_major"])

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.resume, self.resume)
        self.assertEqual(attempt.resume.job, self.job)

    def test_rule_allocation_prefers_same_entity_job(self):
        self.resume.entity = "GW"
        self.resume.save(update_fields=["entity"])
        self.job.entity = "YLS"
        self.job.save(update_fields=["entity"])
        same_entity_job = m.Job.objects.create(
            entity="GW",
            department=self.department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.resume.job, same_entity_job)

    def test_rule_allocation_uses_stable_job_match_priority(self):
        self.job.public_name = "后端"
        self.job.position_name = "后端"
        self.job.save(update_fields=["public_name", "position_name"])
        exact_position_job = m.Job.objects.create(
            department=self.department,
            public_name="服务端研发",
            position_name="后端工程师",
            category="技术类",
            headcount=1,
        )
        exact_public_job = m.Job.objects.create(
            department=self.department,
            public_name="后端工程师",
            position_name="后端研发",
            category="技术类",
            headcount=1,
        )

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.resume.job, exact_public_job)
        self.assertNotEqual(attempt.resume.job, exact_position_job)
        self.assertIn("岗位名精确命中对外发布名称", attempt.match_reason)

    def test_rule_allocation_records_explainable_match_reason(self):
        self.candidate.highest_major = "计算机科学与技术"
        self.candidate.save(update_fields=["highest_major"])
        m.JobMajor.objects.create(job=self.job, major="计算机")

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertIn("院校准入", attempt.match_reason)
        self.assertIn("第1志愿", attempt.match_reason)
        self.assertIn("岗位名精确命中", attempt.match_reason)
        self.assertIn("专业匹配", attempt.match_reason)
        self.assertIn("分配至技术部/二级接口人", attempt.match_reason)

    def test_rule_allocation_matches_school_tag_rule_links(self):
        first_tag = m.SchoolTag.objects.create(code="A", name="平台A")
        highest_tag = m.SchoolTag.objects.create(code="A_PLUS", name="平台A+")
        self.candidate.first_degree_tag = first_tag
        self.candidate.highest_degree_tag = highest_tag
        self.candidate.save(update_fields=["first_degree_tag", "highest_degree_tag"])
        rule = m.SchoolTagRule.objects.create(name="目标院校", priority=1, is_active=True)
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=first_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_FIRST,
        )
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=highest_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_HIGHEST,
        )

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.matched_rule, rule)

    def test_school_gate_does_not_fall_back_to_legacy_platform_text(self):
        first_tag = m.SchoolTag.objects.create(code="A", name="平台A")
        highest_tag = m.SchoolTag.objects.create(code="A_PLUS", name="平台A+")
        rule = m.SchoolTagRule.objects.create(name="目标院校", priority=1, is_active=True)
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=first_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_FIRST,
        )
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=highest_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_HIGHEST,
        )

        allocate.run(mode="rule")

        self.assertFalse(m.AssignmentAttempt.objects.exists())
        self.candidate.workflow.refresh_from_db()
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_SCHOOL_RULE_NOT_MATCHED,
        )

    def test_ai_allocation_uses_configured_review_threshold(self):
        m.Config.objects.create(key="ai_dispatch_threshold", value=0.8)
        m.Config.objects.create(key="ai_review_threshold", value=0.5)

        allocate.run(mode="ai")

        attempt = m.AssignmentAttempt.objects.get()
        decision = m.AgentDispatchDecision.objects.get()
        self.assertEqual(attempt.source, m.AssignmentAttempt.SOURCE_AI)
        self.assertEqual(attempt.status, m.AssignmentAttempt.STATUS_PENDING_REVIEW)
        self.assertTrue(attempt.review_required)
        self.assertEqual(decision.recommendation, m.AgentDispatchDecision.RECOMMEND_REVIEW)
        self.assertGreaterEqual(decision.confidence_score, 0.5)
        self.assertLess(decision.confidence_score, 0.8)
        self.assertEqual(decision.recommended_contact_name_snapshot, "二级接口人")
        self.assertEqual(decision.recommended_contact_employee_no_snapshot, "L2001")

    def test_dispatch_attempt_records_handoff_snapshots(self):
        allocate.run(mode="rule")
        attempt = m.AssignmentAttempt.objects.get()
        user = User.objects.create_user(username="hr-snapshot", password="pass")

        allocate.dispatch_attempt(attempt, user=user)

        attempt.refresh_from_db()
        handoff = m.AssignmentHandoff.objects.get()
        self.assertEqual(attempt.contact_name_snapshot, "二级接口人")
        self.assertEqual(attempt.contact_employee_no_snapshot, "L2001")
        self.assertEqual(handoff.to_department_name_snapshot, "技术部")
        self.assertEqual(handoff.to_contact_name_snapshot, "二级接口人")
        self.assertEqual(handoff.to_contact_employee_no_snapshot, "L2001")
        self.assertEqual(handoff.created_by_username_snapshot, "hr-snapshot")

    def test_ai_model_versions_come_from_backend_config(self):
        with patch.dict(
            "os.environ",
            {
                "AI_MODEL_NAME": "gpt-test",
                "AI_PROMPT_VERSION": "prompt-2026-07",
                "AI_DECISION_VERSION": "decision-2026-07",
            },
        ):
            allocate.run(mode="ai")

        decision = m.AgentDispatchDecision.objects.get()
        self.assertEqual(decision.model_name, "gpt-test")
        self.assertEqual(decision.prompt_version, "prompt-2026-07")
        self.assertEqual(decision.decision_version, "decision-2026-07")

    def test_ai_runtime_config_uses_database_overrides(self):
        m.Config.objects.create(key="ai_timeout_seconds", value=120)
        m.Config.objects.create(key="ai_retry_count", value=3)

        config = ai_config.get_ai_runtime_config()

        self.assertEqual(config.timeout_seconds, 120)
        self.assertEqual(config.retry_count, 3)
        self.assertEqual(config.dispatch_threshold, 0.75)

    def test_ai_allocation_records_pdf_missing_without_assignment_attempt(self):
        self.resume.resume_file = ""
        self.resume.save(update_fields=["resume_file"])
        run = m.ProcessingRun.objects.create(step="step2", mode="ai")

        allocate.run(mode="ai", processing_run=run)

        self.assertFalse(m.AssignmentAttempt.objects.exists())
        decision = m.AgentDispatchDecision.objects.get()
        self.assertEqual(decision.processing_run, run)
        self.assertIsNone(decision.recommendation)
        self.assertIsNone(decision.confidence_score)
        self.assertEqual(decision.error_code, "pdf_missing")
        self.assertIn("PDF", decision.error_message)
        self.assertEqual(decision.resume, self.resume)
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
        )
        self.assertEqual(self.candidate.workflow.current_resume, self.resume)
        self.assertEqual(self.candidate.workflow.current_rank, 1)

    def test_rerun_cancels_pending_review_ai_attempts(self):
        m.Config.objects.create(key="ai_dispatch_threshold", value=0.8)
        m.Config.objects.create(key="ai_review_threshold", value=0.5)
        allocate.run(mode="ai")
        first_attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(first_attempt.status, m.AssignmentAttempt.STATUS_PENDING_REVIEW)

        allocate.run(mode="ai")

        first_attempt.refresh_from_db()
        self.assertEqual(first_attempt.status, m.AssignmentAttempt.STATUS_CANCELLED)
        self.assertEqual(first_attempt.cancel_reason, m.AssignmentAttempt.CANCEL_RERUN)
        self.assertEqual(
            m.AssignmentAttempt.objects.filter(
                status=m.AssignmentAttempt.STATUS_PENDING_REVIEW
            ).count(),
            1,
        )

    def test_scoped_reprocess_reopens_only_selected_system_statuses(self):
        allocate.run(mode="rule")
        passed_attempt = m.AssignmentAttempt.objects.get()
        allocate.dispatch_attempt(passed_attempt)
        tertiary_department = m.Department.objects.create(
            name="技术三部", level=3, parent=self.department
        )
        tertiary_contact = m.Contact.objects.create(
            name="三级接口人",
            employee_no="T2001",
            department=tertiary_department,
            contact_level=m.Contact.LEVEL_TERTIARY,
            is_active=True,
        )
        allocate.assign_sub_contact(passed_attempt, tertiary_contact)
        allocate.submit_feedback(passed_attempt, m.AssignmentAttempt.FEEDBACK_PASSED)
        self.candidate.workflow.refresh_from_db()
        self.assertEqual(self.candidate.workflow.status, m.CandidateWorkflow.STATUS_PASSED)

        other_candidate = m.Candidate.objects.create(
            identity_hash="candidate-unselected",
            name="李四",
            phone="13900000000",
            first_degree_platform="平台A",
            highest_degree_platform="平台A",
        )
        m.Resume.objects.create(
            candidate=other_candidate,
            apply_id="B1001",
            position_name="后端工程师",
            volunteer_rank=1,
            resume_file="李四（B1001）.pdf",
        )

        message = allocate.run(
            mode="rule",
            scope={"system_statuses": ["screening_passed"]},
        )

        self.candidate.workflow.refresh_from_db()
        self.assertEqual(self.candidate.workflow.status, m.CandidateWorkflow.STATUS_IN_PROGRESS)
        self.assertIsNone(self.candidate.workflow.passed_attempt_id)
        self.assertEqual(
            m.AssignmentAttempt.objects.filter(workflow=self.candidate.workflow).count(),
            2,
        )
        self.assertFalse(hasattr(other_candidate, "workflow"))
        self.assertIn("已生成 1 条候选人分配尝试", message)
