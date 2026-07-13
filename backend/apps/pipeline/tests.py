from unittest.mock import patch
from types import SimpleNamespace

from django.test import TestCase

from apps.accounts.models import User
from apps.core import models as m
from apps.pipeline import ai_config, runner
from apps.pipeline.ai.service import AIServiceError
from apps.pipeline.services import allocate, classify_school


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

    def _ai_result(self, confidence=0.78):
        profile, _ = m.ResumeProfile.objects.get_or_create(
            resume=self.resume,
            defaults={"parse_status": "parsed", "raw_text": "候选人简历正文"},
        )
        breakdown = {
            "major_match": confidence,
            "skills_match": confidence,
            "experience_evidence": confidence,
            "job_requirement": confidence,
            "department_certainty": confidence,
            "resume_quality": confidence,
        }
        decision = SimpleNamespace(
            recommendation="dispatch",
            summary="结构化 AI 建议",
            reason="简历证据与当前志愿匹配",
            evidence=["项目经历支持岗位要求"],
            risks=[],
        )
        return SimpleNamespace(
            profile=profile,
            output=SimpleNamespace(
                decision=decision,
                profile=SimpleNamespace(risk_flags=[]),
            ),
            job=self.job,
            department=self.department,
            contact=self.contact,
            confidence=confidence,
            score_breakdown=breakdown,
        )

    def test_rule_allocation_passes_school_gate_when_no_active_rules(self):
        message = allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertIn("已生成 1 条候选人分配尝试", message)
        self.assertEqual(attempt.source, m.AssignmentAttempt.SOURCE_RULE)
        self.assertEqual(attempt.status, m.AssignmentAttempt.STATUS_PENDING_DISPATCH)
        self.assertIsNone(attempt.matched_rule)
        self.assertEqual(self.candidate.workflow.status, m.CandidateWorkflow.STATUS_IN_PROGRESS)

    def test_resume_process_freezes_scope_and_exposes_two_stages(self):
        user = User.objects.create_user(username="hr-run-owner", password="pass")
        run = runner.create_run(
            "resume_process",
            mode="rule",
            scope={"candidate_ids": [self.candidate.id], "source": "resume_import"},
            created_by=user,
        )

        self.assertEqual(run.scope, {"source": "resume_import"})
        self.assertEqual(run.scope_summary["candidate_count"], 1)
        self.assertEqual(
            list(run.scope_items.values_list("candidate_id", flat=True)), [self.candidate.id]
        )
        self.assertEqual(list(run.stages.values_list("step", flat=True)), ["step1", "step2"])

        runner.execute_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.created_by, user)
        self.assertTrue(run.last_heartbeat_at)
        self.assertEqual(list(run.stages.values_list("status", flat=True)), ["success", "success"])

    def test_create_runs_marks_rule_and_ai_as_coordinated_parallel_modes(self):
        with patch("apps.pipeline.runner.ai_config.is_ai_enabled", return_value=True):
            runs = runner.create_runs(
                "step2",
                modes=["rule", "ai"],
                scope={"candidate_ids": [self.candidate.id]},
            )

        self.assertEqual([run.mode for run in runs], ["rule", "ai"])
        self.assertTrue(all(run.scope["parallel_modes"] for run in runs))
        self.assertEqual(
            [list(run.scope_items.values_list("candidate_id", flat=True)) for run in runs],
            [[self.candidate.id], [self.candidate.id]],
        )

    def test_coordinated_rule_and_ai_runs_keep_both_attempt_sources(self):
        with patch("apps.pipeline.runner.ai_config.is_ai_enabled", return_value=True), patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ):
            runs = runner.create_runs(
                "step2",
                modes=["rule", "ai"],
                scope={"candidate_ids": [self.candidate.id]},
            )
            for run in runs:
                runner.execute_run(run.id)

        self.assertEqual(
            set(m.AssignmentAttempt.objects.values_list("source", flat=True)),
            {m.AssignmentAttempt.SOURCE_RULE, m.AssignmentAttempt.SOURCE_AI},
        )

    def test_run_skips_candidate_changed_after_submit(self):
        workflow = m.CandidateWorkflow.objects.create(candidate=self.candidate)
        run = runner.create_run(
            "step2", mode="rule", scope={"candidate_ids": [self.candidate.id]}
        )
        workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
        workflow.save(update_fields=["status"])

        runner.execute_run(run.id)

        scope_item = run.scope_items.get(candidate=self.candidate)
        self.assertEqual(scope_item.status, "skipped_manual_change")
        self.assertFalse(m.AssignmentAttempt.objects.exists())

    def test_scoped_reprocess_classifies_school_tags_before_school_gate(self):
        target_tag = m.SchoolTag.objects.create(code="TARGET", name="目标院校")
        m.School.objects.create(name="南京大学", school_tag=target_tag)
        rule = m.SchoolTagRule.objects.create(name="目标院校", priority=1, is_active=True)
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=target_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_FIRST,
        )
        m.SchoolTagRuleTag.objects.create(
            rule=rule,
            school_tag=target_tag,
            degree_type=m.SchoolTagRuleTag.DEGREE_HIGHEST,
        )
        self.candidate.first_degree_school = "南京大学"
        self.candidate.highest_degree_school = "南京大学"
        self.candidate.first_degree_platform = ""
        self.candidate.highest_degree_platform = ""
        self.candidate.first_degree_tag = None
        self.candidate.highest_degree_tag = None
        self.candidate.save(
            update_fields=[
                "first_degree_school",
                "highest_degree_school",
                "first_degree_platform",
                "highest_degree_platform",
                "first_degree_tag",
                "highest_degree_tag",
            ]
        )

        message = allocate.run(mode="rule", scope={"system_statuses": ["raw"]})

        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.first_degree_tag, target_tag)
        self.assertEqual(self.candidate.highest_degree_tag, target_tag)
        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.matched_rule, rule)
        self.assertEqual(self.candidate.workflow.status, m.CandidateWorkflow.STATUS_IN_PROGRESS)
        self.assertIn("已生成 1 条候选人分配尝试", message)

    def test_scoped_reprocess_preserves_existing_school_tags_and_platforms(self):
        existing_tag = m.SchoolTag.objects.create(code="MANUAL", name="人工确认标签")
        mapped_tag = m.SchoolTag.objects.create(code="TARGET", name="清单目标院校")
        m.School.objects.create(name="南京大学", school_tag=mapped_tag)
        self.candidate.first_degree_school = "南京大学"
        self.candidate.highest_degree_school = "南京大学"
        self.candidate.first_degree_tag = existing_tag
        self.candidate.highest_degree_tag = existing_tag
        self.candidate.first_degree_platform = "人工确认平台"
        self.candidate.highest_degree_platform = "人工确认平台"
        self.candidate.save(
            update_fields=[
                "first_degree_school",
                "highest_degree_school",
                "first_degree_tag",
                "highest_degree_tag",
                "first_degree_platform",
                "highest_degree_platform",
            ]
        )

        allocate.run(mode="rule", scope={"candidate_ids": [self.candidate.id]})

        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.first_degree_tag, existing_tag)
        self.assertEqual(self.candidate.highest_degree_tag, existing_tag)
        self.assertEqual(self.candidate.first_degree_platform, "人工确认平台")
        self.assertEqual(self.candidate.highest_degree_platform, "人工确认平台")

    def test_school_classification_fills_missing_tags_without_overwriting_platforms(self):
        mapped_tag = m.SchoolTag.objects.create(code="TARGET", name="清单目标院校")
        m.School.objects.create(name="南京大学", school_tag=mapped_tag)
        self.candidate.first_degree_school = "南京大学"
        self.candidate.highest_degree_school = "南京大学"
        self.candidate.first_degree_tag = None
        self.candidate.highest_degree_tag = None
        self.candidate.first_degree_platform = "人工确认平台"
        self.candidate.highest_degree_platform = "人工确认平台"
        self.candidate.save(
            update_fields=[
                "first_degree_school",
                "highest_degree_school",
                "first_degree_tag",
                "highest_degree_tag",
                "first_degree_platform",
                "highest_degree_platform",
            ]
        )

        classify_school.classify_candidates([self.candidate], overwrite=False)

        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.first_degree_tag, mapped_tag)
        self.assertEqual(self.candidate.highest_degree_tag, mapped_tag)
        self.assertEqual(self.candidate.first_degree_platform, "人工确认平台")
        self.assertEqual(self.candidate.highest_degree_platform, "人工确认平台")

    def test_school_outside_imported_list_is_always_non_target(self):
        m.SchoolTag.objects.create(
            code="DEFAULT_TARGET", name="默认目标院校", is_default=True, is_active=True
        )
        self.candidate.first_degree_school = "未在清单中的学校"
        self.candidate.highest_degree_school = "另一所未在清单中的学校"
        self.candidate.save(
            update_fields=["first_degree_school", "highest_degree_school"]
        )

        classify_school.classify_candidates([self.candidate])

        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.first_degree_tag.code, "NON_TARGET")
        self.assertEqual(self.candidate.highest_degree_tag.code, "NON_TARGET")

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

    def test_rule_allocation_blocks_current_volunteer_when_secondary_contact_missing(self):
        self.contact.is_active = False
        self.contact.save(update_fields=["is_active"])
        fallback_department = m.Department.objects.create(name="产品部", level=2)
        m.Contact.objects.create(
            name="产品接口人",
            employee_no="L2002",
            department=fallback_department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        fallback_resume = m.Resume.objects.create(
            candidate=self.candidate,
            apply_id="A1002",
            position_name="产品经理",
            volunteer_rank=2,
            resume_file="张三（A1002）.pdf",
        )
        m.Job.objects.create(
            department=fallback_department,
            public_name="产品经理",
            position_name="产品经理",
            category="产品类",
            headcount=1,
        )

        allocate.run(mode="rule")

        self.assertFalse(m.AssignmentAttempt.objects.exists())
        self.candidate.workflow.refresh_from_db()
        self.resume.refresh_from_db()
        fallback_resume.refresh_from_db()
        self.assertEqual(
            self.candidate.workflow.status,
            m.CandidateWorkflow.STATUS_IN_PROGRESS,
        )
        self.assertEqual(self.candidate.workflow.current_resume, self.resume)
        self.assertEqual(self.candidate.workflow.current_rank, 1)
        self.assertEqual(
            self.candidate.workflow.block_reason,
            m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND,
        )
        self.assertIn("技术部", self.candidate.workflow.block_detail)
        self.assertEqual(self.resume.job, self.job)
        self.assertIsNone(fallback_resume.job)

    def test_rule_allocation_clears_contact_block_when_valid_attempt_is_created(self):
        workflow = m.CandidateWorkflow.objects.create(
            candidate=self.candidate,
            status=m.CandidateWorkflow.STATUS_IN_PROGRESS,
            current_resume=self.resume,
            current_rank=1,
            block_reason=m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND,
            block_detail="旧阻塞原因",
        )

        allocate._create_attempt(
            workflow=workflow,
            resume=self.resume,
            contact=self.contact,
            source=m.AssignmentAttempt.SOURCE_RULE,
            mode="rule",
            match_reason="测试分配",
        )

        workflow.refresh_from_db()
        self.assertEqual(workflow.block_reason, "")
        self.assertEqual(workflow.block_detail, "")

    def test_rule_allocation_matches_major_category_dictionary_before_name_fallback(self):
        self.candidate.highest_major = "软件工程"
        self.candidate.save(update_fields=["highest_major"])
        m.JobMajor.objects.create(job=self.job, major="计算机类")
        category = m.MajorCategory.objects.create(
            code="CS_SOFTWARE",
            name="计算机与软件类",
            is_active=True,
        )
        m.MajorAlias.objects.create(
            category=category,
            name="软件工程",
            normalized_name="软件工程",
            match_type=m.MajorAlias.MATCH_EXACT,
            source=m.MajorAlias.SOURCE_BUILTIN,
            is_active=True,
        )
        m.MajorAlias.objects.create(
            category=category,
            name="计算机类",
            normalized_name="计算机类",
            match_type=m.MajorAlias.MATCH_EXACT,
            source=m.MajorAlias.SOURCE_BUILTIN,
            is_active=True,
        )

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.resume, self.resume)
        self.assertEqual(attempt.resume.job, self.job)
        self.assertIn("专业大类匹配", attempt.match_reason)
        self.assertIn("计算机与软件类", attempt.match_reason)

    def test_rule_allocation_allows_wildcard_required_major(self):
        m.JobMajor.objects.create(job=self.job, major="不限专业")

        allocate.run(mode="rule")

        attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(attempt.resume, self.resume)
        self.assertEqual(attempt.resume.job, self.job)
        self.assertIn("需求专业为不限", attempt.match_reason)

    def test_rule_allocation_does_not_treat_related_major_as_default_wildcard(self):
        self.candidate.highest_major = "软件工程"
        self.candidate.save(update_fields=["highest_major"])
        m.JobMajor.objects.create(job=self.job, major="相关专业")
        general = m.MajorCategory.objects.create(
            code="OTHER_GENERAL",
            name="其他通用类",
            is_active=False,
        )
        m.MajorAlias.objects.create(
            category=general,
            name="相关专业",
            normalized_name="相关专业",
            match_type=m.MajorAlias.MATCH_CONTAINS,
            source=m.MajorAlias.SOURCE_BUILTIN,
            is_active=True,
        )

        allocate.run(mode="rule")

        self.assertFalse(m.AssignmentAttempt.objects.exists())
        self.candidate.workflow.refresh_from_db()
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED,
        )

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

        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ):
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

    def test_ai_failure_keeps_current_volunteer_and_never_skips_to_next(self):
        m.Resume.objects.create(
            candidate=self.candidate,
            apply_id="A1002",
            position_name="测试工程师",
            volunteer_rank=2,
            resume_file="张三（A1002）.pdf",
        )
        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            side_effect=AIServiceError("llm_error", "模型服务不可用"),
        ) as mocked:
            allocate.run(mode="ai")

        self.candidate.workflow.refresh_from_db()
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(mocked.call_args.args[0], self.resume)
        self.assertEqual(self.candidate.workflow.current_resume, self.resume)
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
        )

    def test_cancel_ai_review_archives_when_no_other_active_attempt(self):
        m.Config.objects.create(key="ai_dispatch_threshold", value=0.8)
        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ):
            allocate.run(mode="ai")
        attempt = m.AssignmentAttempt.objects.get()

        allocate.cancel_attempt(attempt, "hr_cancelled_review")

        attempt.refresh_from_db()
        self.candidate.workflow.refresh_from_db()
        self.assertEqual(attempt.status, m.AssignmentAttempt.STATUS_CANCELLED)
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_AGENT_NO_RECOMMENDATION,
        )

    def test_manual_direct_to_tertiary_requires_secondary_when_multiple(self):
        other_secondary = m.Contact.objects.create(
            name="另一二级接口人",
            employee_no="L2002",
            department=self.department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        sub_department = m.Department.objects.create(
            name="平台组", level=3, parent=self.department
        )
        tertiary = m.Contact.objects.create(
            name="三级接口人",
            employee_no="L3001",
            department=sub_department,
            contact_level=m.Contact.LEVEL_TERTIARY,
            is_active=True,
        )
        with self.assertRaisesMessage(ValueError, "请明确 secondary_contact_id"):
            allocate.manual_assign(self.resume, tertiary)

        attempt = allocate.manual_assign(
            self.resume, tertiary, secondary_contact=other_secondary
        )

        self.assertEqual(attempt.status, m.AssignmentAttempt.STATUS_ASSIGNED_L3)
        self.assertEqual(attempt.contact, other_secondary)
        self.assertEqual(attempt.sub_contact, tertiary)
        self.assertEqual(attempt.handoffs.count(), 2)

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
            with patch(
                "apps.pipeline.services.allocate.ai_service.screen_resume",
                return_value=self._ai_result(),
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
        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ):
            allocate.run(mode="ai")
        first_attempt = m.AssignmentAttempt.objects.get()
        self.assertEqual(first_attempt.status, m.AssignmentAttempt.STATUS_PENDING_REVIEW)

        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ):
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

    def test_archived_workflow_keeps_last_attempted_resume_when_job_not_matched(self):
        self.job.is_active = False
        self.job.save(update_fields=["is_active"])

        allocate.run(mode="rule")

        self.candidate.workflow.refresh_from_db()
        self.assertEqual(
            self.candidate.workflow.status,
            m.CandidateWorkflow.STATUS_ARCHIVED,
        )
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED,
        )
        self.assertEqual(self.candidate.workflow.current_resume, self.resume)
        self.assertEqual(self.candidate.workflow.current_rank, 1)

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
        filtered_passed_candidate = m.Candidate.objects.create(
            identity_hash="candidate-filtered-passed",
            name="王五",
            phone="13700000000",
            first_degree_platform="平台A",
            highest_degree_platform="平台A",
        )
        filtered_passed_resume = m.Resume.objects.create(
            candidate=filtered_passed_candidate,
            apply_id="C1001",
            position_name="后端工程师",
            volunteer_rank=1,
            resume_file="王五（C1001）.pdf",
        )
        m.CandidateWorkflow.objects.create(
            candidate=filtered_passed_candidate,
            status=m.CandidateWorkflow.STATUS_PASSED,
            current_resume=filtered_passed_resume,
            current_rank=1,
        )
        same_name_raw_candidate = m.Candidate.objects.create(
            identity_hash="candidate-same-name-raw",
            name="张三",
            phone="13600000000",
            first_degree_platform="平台A",
            highest_degree_platform="平台A",
        )
        m.Resume.objects.create(
            candidate=same_name_raw_candidate,
            apply_id="D1001",
            position_name="后端工程师",
            volunteer_rank=1,
            resume_file="张三（D1001）.pdf",
        )

        message = allocate.run(
            mode="rule",
            scope={
                "system_statuses": ["screening_passed"],
                "candidate_filters": {"name": "张三"},
            },
        )

        self.candidate.workflow.refresh_from_db()
        self.assertEqual(self.candidate.workflow.status, m.CandidateWorkflow.STATUS_IN_PROGRESS)
        self.assertIsNone(self.candidate.workflow.passed_attempt_id)
        self.assertEqual(
            m.AssignmentAttempt.objects.filter(workflow=self.candidate.workflow).count(),
            2,
        )
        self.assertFalse(hasattr(other_candidate, "workflow"))
        filtered_passed_candidate.workflow.refresh_from_db()
        self.assertEqual(
            filtered_passed_candidate.workflow.status,
            m.CandidateWorkflow.STATUS_PASSED,
        )
        self.assertFalse(
            m.AssignmentAttempt.objects.filter(
                workflow=filtered_passed_candidate.workflow
            ).exists()
        )
        self.assertFalse(hasattr(same_name_raw_candidate, "workflow"))
        self.assertIn("已生成 1 条候选人分配尝试", message)
