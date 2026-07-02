from django.test import TestCase

from apps.core import models as m
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
