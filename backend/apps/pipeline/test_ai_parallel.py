from types import SimpleNamespace
from unittest.mock import patch

from celery.exceptions import Retry
from django.test import SimpleTestCase, TestCase, override_settings

from apps.core import models as m
from apps.pipeline import ai_config, runner
from apps.pipeline.ai import concurrency
from apps.pipeline.services import allocate
from apps.pipeline.tasks import dispatch_ai_run_task


class _FakeRedis:
    """只实现控制器测试所需的 Lua 语义；生产原子性由 Redis 脚本提供。"""

    def __init__(self):
        self.limit = 0
        self.successes = 0
        self.in_flight = set()
        self.blocked_until = 0

    def eval(self, script, _key_count, _leases_key, _state_key, *args):
        if script == concurrency._ACQUIRE_SCRIPT:
            now, ceiling, lease_id, _expires_at = args
            self.limit = self.limit or min(2, int(ceiling))
            if now < self.blocked_until or len(self.in_flight) >= self.limit:
                return [0, self.limit, len(self.in_flight), 50]
            self.in_flight.add(lease_id)
            return [1, self.limit, len(self.in_flight), 0]
        now, ceiling, outcome, retry_after, backoff, lease_id = args
        self.in_flight.discard(lease_id)
        if outcome == "success":
            self.successes += 1
            if self.successes >= self.limit and self.limit < int(ceiling):
                self.limit = min(int(ceiling), self.limit * 2)
                self.successes = 0
        elif outcome == "rate_limit":
            self.limit = max(1, int(self.limit * 0.8))
            self.successes = 0
            self.blocked_until = now + max(float(retry_after), float(backoff), 1)
        return [self.limit, len(self.in_flight)]


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
class AdaptiveConcurrencyTests(SimpleTestCase):
    def setUp(self):
        self.model = SimpleNamespace(
            api_style="responses",
            base_url="https://model.internal/v1",
            model_name="test-model",
            api_key="secret",
        )
        self.runtime = SimpleNamespace(
            concurrency=8,
            timeout_seconds=60,
            retry_backoff_seconds=1,
        )

    def test_clean_windows_grow_and_rate_limit_reduces_shared_limit(self):
        fake = _FakeRedis()
        with patch.object(concurrency, "_redis_client", return_value=fake):
            first = concurrency.acquire_slot(self.model, self.runtime)
            first.release("success")
            second = concurrency.acquire_slot(self.model, self.runtime)
            second.release("success")
            self.assertEqual(fake.limit, 4)

            limited = concurrency.acquire_slot(self.model, self.runtime)
            limited.release("rate_limit", retry_after=2)

        self.assertEqual(fake.limit, 3)
        self.assertGreater(fake.blocked_until, 0)

    def test_resource_key_is_model_scoped_and_never_contains_secret(self):
        leases, state = concurrency._resource_key(self.model)

        self.assertIn("srf:ai-limit", leases)
        self.assertIn("srf:ai-limit", state)
        self.assertNotIn("secret", leases)
        other = SimpleNamespace(**{**self.model.__dict__, "model_name": "other"})
        self.assertNotEqual(concurrency._resource_key(other), (leases, state))


class AIParallelPipelineTests(TestCase):
    def setUp(self):
        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "gpt-test",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
        self.department = m.Department.objects.create(name="并发技术部", level=2)
        self.contact = m.Contact.objects.create(
            name="并发接口人",
            employee_no="PAR-L2",
            department=self.department,
            contact_level=m.Contact.LEVEL_SECONDARY,
        )
        self.job = m.Job.objects.create(
            department=self.department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
        )

    def _candidate(self, index):
        candidate = m.Candidate.objects.create(
            identity_hash=f"parallel-{index}",
            name=f"候选人{index}",
            phone=f"138000{index:05d}",
        )
        resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id=f"PAR-{index}",
            position_name="后端工程师",
            volunteer_rank=1,
            resume_file=f"候选人{index}.pdf",
        )
        return candidate, resume

    def _ai_result(self, resume):
        profile = m.ResumeProfile.objects.create(
            resume=resume,
            parse_status="parsed",
            raw_text="候选人简历正文",
        )
        output = SimpleNamespace(
            decision=SimpleNamespace(
                recommendation="dispatch",
                summary="建议下发",
                reason="岗位匹配",
                evidence=["项目经历"],
                risks=[],
            ),
            profile=SimpleNamespace(risk_flags=[]),
        )
        return SimpleNamespace(
            profile=profile,
            output=output,
            job=self.job,
            department=self.department,
            contact=self.contact,
            confidence=0.9,
            score_breakdown={},
        )

    def test_manual_revision_change_during_model_call_discards_ai_result(self):
        candidate, resume = self._candidate(1)
        run = runner.create_run(
            "step2", mode="ai", scope={"candidate_ids": [candidate.id]}
        )

        def change_workflow(*_args, **_kwargs):
            workflow = m.CandidateWorkflow.objects.get(candidate=candidate)
            workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
            workflow.save(update_fields=["status"])
            return self._ai_result(resume)

        with patch.object(
            allocate.ai_service,
            "screen_resume",
            side_effect=change_workflow,
        ):
            runner.execute_run(run.id)

        run.refresh_from_db()
        item = run.scope_items.get()
        self.assertEqual(item.status, "skipped_manual_change")
        self.assertEqual(run.skipped_count, 1)
        self.assertFalse(m.AssignmentAttempt.objects.exists())

    def test_eager_ai_run_uses_candidate_task_counters_and_default_ceiling(self):
        candidate, resume = self._candidate(88)
        run = runner.create_run(
            "step2", mode="ai", scope={"candidate_ids": [candidate.id]}
        )

        with patch.object(
            allocate.ai_service,
            "screen_resume",
            return_value=self._ai_result(resume),
        ):
            runner.execute_run(run.id)

        run.refresh_from_db()
        stage = run.stages.get(step="step2")
        self.assertEqual(run.status, "success")
        self.assertEqual(run.ai_concurrency_limit, 8)
        self.assertEqual(run.ai_effective_concurrency, 1)
        self.assertEqual((run.chunk_size, run.chunk_total, run.chunk_done), (1, 1, 1))
        self.assertEqual((run.processed_count, run.success_count), (1, 1))
        self.assertEqual((stage.processed_count, stage.success_count), (1, 1))
        self.assertEqual(m.AssignmentAttempt.objects.get().source, "ai")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_dispatcher_only_queues_four_times_the_configured_ceiling(self):
        candidates = [self._candidate(index)[0] for index in range(2, 42)]
        run = runner.create_run(
            "step2",
            mode="ai",
            scope={"candidate_ids": [candidate.id for candidate in candidates]},
        )
        run.status = "running"
        run.started_at = run.created_at
        run.save(update_fields=["status", "started_at"])
        runner.prepare_ai_stage(run, {})

        with patch(
            "apps.pipeline.tasks.process_ai_scope_item_task.apply_async"
        ) as publish:
            result = dispatch_ai_run_task.run(run.id)

        self.assertEqual(result, "queued:32")
        self.assertEqual(publish.call_count, 32)
        self.assertEqual(run.scope_items.filter(status="queued").count(), 32)
        self.assertEqual(run.scope_items.filter(status="pending").count(), 8)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_dispatch_publish_failure_rolls_back_queued_state(self):
        candidate, _resume = self._candidate(99)
        run = runner.create_run(
            "step2", mode="ai", scope={"candidate_ids": [candidate.id]}
        )
        run.status = "running"
        run.save(update_fields=["status"])
        runner.prepare_ai_stage(run, {})

        with patch(
            "apps.pipeline.tasks.process_ai_scope_item_task.apply_async",
            side_effect=RuntimeError("broker unavailable"),
        ), self.assertRaises(Retry):
            dispatch_ai_run_task.run(run.id)

        self.assertEqual(run.scope_items.get().status, "pending")
