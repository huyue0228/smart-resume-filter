from unittest.mock import patch
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core import models as m, system_status
from apps.pipeline import ai_config, runner
from apps.pipeline.ai import service as ai_service
from apps.pipeline.ai.service import AIServiceError
from apps.pipeline.services import allocate, classify_school


class AllocationDesignContractTests(TestCase):
    def setUp(self):
        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "gpt-test",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
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

    def test_configured_run_creates_one_run_with_current_rule_mode(self):
        with patch("apps.pipeline.runner.ai_config.allocation_mode", return_value="rule"):
            run = runner.create_configured_run(
                "step2",
                scope={"candidate_ids": [self.candidate.id]},
            )

        self.assertEqual(run.mode, "rule")
        self.assertEqual(
            list(run.scope_items.values_list("candidate_id", flat=True)),
            [self.candidate.id],
        )
        self.assertNotIn("parallel_modes", run.scope)

    def test_configured_run_freezes_ai_mode_at_submission_time(self):
        with patch("apps.pipeline.runner.ai_config.allocation_mode", return_value="ai"):
            run = runner.create_configured_run(
                "step2",
                scope={"candidate_ids": [self.candidate.id]},
            )

        with patch("apps.pipeline.runner.ai_config.allocation_mode", return_value="rule"), patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ):
            runner.execute_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.mode, "ai")
        self.assertEqual(
            list(m.AssignmentAttempt.objects.values_list("source", flat=True)),
            [m.AssignmentAttempt.SOURCE_AI],
        )

    def test_force_reprocess_skips_candidate_changed_after_submit(self):
        workflow = m.CandidateWorkflow.objects.create(candidate=self.candidate)
        run = runner.create_run(
            "step2",
            mode="rule",
            scope={"candidate_ids": [self.candidate.id], "force_reprocess": True},
        )
        workflow.status = m.CandidateWorkflow.STATUS_IN_PROGRESS
        workflow.save(update_fields=["status"])

        runner.execute_run(run.id)

        scope_item = run.scope_items.get(candidate=self.candidate)
        self.assertEqual(scope_item.status, "skipped_manual_change")
        self.assertIsNotNone(scope_item.finished_at)
        run.refresh_from_db()
        self.assertEqual(run.success_count, 0)
        self.assertEqual(run.skipped_count, 1)
        self.assertEqual(run.stages.get(step="step2").skipped_count, 1)
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
        self.assertIn("后端工程师", self.candidate.workflow.block_detail)
        self.assertIn("二级接口人", self.candidate.workflow.block_detail)
        self.assertEqual(self.resume.job, self.job)
        self.assertIsNone(fallback_resume.job)

    def test_rule_archive_detail_identifies_missing_job_requirement(self):
        self.job.is_active = False
        self.job.save(update_fields=["is_active"])

        allocate.run(mode="rule")

        self.candidate.workflow.refresh_from_db()
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_JOB_NOT_MATCHED,
        )
        self.assertIn("第1志愿", self.candidate.workflow.archive_detail)
        self.assertIn("后端工程师", self.candidate.workflow.archive_detail)
        self.assertIn("岗位需求中未配置", self.candidate.workflow.archive_detail)

    def test_rule_archive_detail_identifies_missing_secondary_department(self):
        self.job.department = None
        self.job.save(update_fields=["department"])

        allocate.run(mode="rule")

        self.candidate.workflow.refresh_from_db()
        self.assertEqual(
            self.candidate.workflow.archive_reason,
            m.CandidateWorkflow.ARCHIVE_DEPARTMENT_NOT_FOUND,
        )
        self.assertIn("后端工程师", self.candidate.workflow.archive_detail)
        self.assertIn("未配置有效二级部门", self.candidate.workflow.archive_detail)

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

    def test_school_gate_requires_allowed_highest_education_in_same_rule(self):
        first_tag = m.SchoolTag.objects.create(code="EDU_FIRST", name="第一标签")
        highest_tag = m.SchoolTag.objects.create(code="EDU_HIGH", name="最高标签")
        self.candidate.first_degree_tag = first_tag
        self.candidate.highest_degree_tag = highest_tag
        self.candidate.highest_education = m.Candidate.EDUCATION_MASTER
        self.candidate.save(
            update_fields=["first_degree_tag", "highest_degree_tag", "highest_education"]
        )
        bachelor_rule = m.SchoolTagRule.objects.create(
            name="仅本科", priority=1, is_active=True
        )
        master_rule = m.SchoolTagRule.objects.create(
            name="允许硕士", priority=2, is_active=True
        )
        for rule in [bachelor_rule, master_rule]:
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
        m.SchoolTagRuleEducation.objects.create(
            rule=bachelor_rule, education=m.Candidate.EDUCATION_BACHELOR
        )
        m.SchoolTagRuleEducation.objects.create(
            rule=master_rule, education=m.Candidate.EDUCATION_MASTER
        )

        allocate.run(mode="rule")

        self.assertEqual(m.AssignmentAttempt.objects.get().matched_rule, master_rule)

    def test_missing_highest_education_blocks_ai_before_model_call(self):
        first_tag = m.SchoolTag.objects.create(code="MISS_FIRST", name="第一标签")
        highest_tag = m.SchoolTag.objects.create(code="MISS_HIGH", name="最高标签")
        self.candidate.first_degree_tag = first_tag
        self.candidate.highest_degree_tag = highest_tag
        self.candidate.highest_education = ""
        self.candidate.save(
            update_fields=["first_degree_tag", "highest_degree_tag", "highest_education"]
        )
        rule = m.SchoolTagRule.objects.create(name="限制学历", priority=1, is_active=True)
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
        m.SchoolTagRuleEducation.objects.create(
            rule=rule, education=m.Candidate.EDUCATION_MASTER
        )

        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume"
        ) as screen_resume:
            allocate.run(mode="ai")

        screen_resume.assert_not_called()
        self.candidate.workflow.refresh_from_db()
        self.assertIn("最高学历缺失", self.candidate.workflow.archive_detail)

    def test_disallowed_highest_education_records_explicit_archive_detail(self):
        first_tag = m.SchoolTag.objects.create(code="NO_FIRST", name="第一标签")
        highest_tag = m.SchoolTag.objects.create(code="NO_HIGH", name="最高标签")
        self.candidate.first_degree_tag = first_tag
        self.candidate.highest_degree_tag = highest_tag
        self.candidate.highest_education = m.Candidate.EDUCATION_ASSOCIATE
        self.candidate.save(
            update_fields=["first_degree_tag", "highest_degree_tag", "highest_education"]
        )
        rule = m.SchoolTagRule.objects.create(name="仅本科", priority=1, is_active=True)
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
        m.SchoolTagRuleEducation.objects.create(
            rule=rule, education=m.Candidate.EDUCATION_BACHELOR
        )

        allocate.run(mode="rule")

        self.candidate.workflow.refresh_from_db()
        self.assertIn("不在", self.candidate.workflow.archive_detail)
        self.assertIn("允许范围", self.candidate.workflow.archive_detail)

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

    def test_ai_allocation_only_passes_current_volunteer_job_to_model(self):
        unrelated_job = m.Job.objects.create(
            department=self.department,
            public_name="产品经理",
            position_name="产品经理",
            category="产品类",
            headcount=1,
        )
        m.JobMajor.objects.create(job=unrelated_job, major="工商管理")

        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ) as mocked:
            allocate.run(mode="ai")

        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[0], self.resume)
        self.assertEqual(mocked.call_args.args[1], self.job)

    def test_ai_current_job_lookup_does_not_load_unrelated_job_majors(self):
        for index in range(5):
            unrelated_job = m.Job.objects.create(
                department=self.department,
                public_name=f"无关岗位{index}",
                position_name=f"无关岗位{index}",
                category="其它类",
                headcount=1,
            )
            m.JobMajor.objects.create(job=unrelated_job, major=f"无关专业{index}")

        with self.assertNumQueries(2):
            current_job = allocate._current_volunteer_job(self.resume)
        with self.assertNumQueries(2):
            context = ai_service._current_job_context(current_job)

        self.assertEqual(current_job, self.job)
        self.assertEqual(context["id"], self.job.id)
        self.assertEqual(context["required_majors"], [])

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

    def test_ai_archive_detail_identifies_missing_secondary_department(self):
        self.job.department = None
        self.job.save(update_fields=["department"])
        with patch("apps.pipeline.services.allocate.ai_service.screen_resume") as mocked:
            allocate.run(mode="ai")

        self.candidate.workflow.refresh_from_db()
        decision = m.AgentDispatchDecision.objects.get()
        mocked.assert_not_called()
        self.assertEqual(decision.error_code, "reference_not_found")
        self.assertIn("后端工程师", decision.error_message)
        self.assertIn("未配置有效二级部门", self.candidate.workflow.archive_detail)

    def test_ai_archive_detail_identifies_missing_job_requirement(self):
        self.job.is_active = False
        self.job.save(update_fields=["is_active"])
        with patch("apps.pipeline.services.allocate.ai_service.screen_resume") as mocked:
            allocate.run(mode="ai")

        self.candidate.workflow.refresh_from_db()
        decision = m.AgentDispatchDecision.objects.get()
        mocked.assert_not_called()
        self.assertEqual(decision.error_code, "guardrail_blocked")
        self.assertIn("后端工程师", decision.error_message)
        self.assertIn("岗位需求中未配置", self.candidate.workflow.archive_detail)

    def test_ai_archive_detail_identifies_missing_secondary_contact(self):
        self.contact.is_active = False
        self.contact.save(update_fields=["is_active"])
        with patch("apps.pipeline.services.allocate.ai_service.screen_resume") as mocked:
            allocate.run(mode="ai")

        self.candidate.workflow.refresh_from_db()
        decision = m.AgentDispatchDecision.objects.get()
        mocked.assert_not_called()
        self.assertEqual(decision.error_code, "reference_not_found")
        self.assertIn("技术部", decision.error_message)
        self.assertIn("没有启用的二级接口人", self.candidate.workflow.archive_detail)

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

    def test_secondary_stage_rejection_advances_to_next_volunteer(self):
        second_resume = m.Resume.objects.create(
            candidate=self.candidate,
            apply_id="A1002",
            position_name="后端工程师",
            volunteer_rank=2,
            resume_file="张三（A1002）.pdf",
        )
        allocate.run(mode="rule")
        first_attempt = m.AssignmentAttempt.objects.get()
        allocate.dispatch_attempt(first_attempt)

        allocate.submit_feedback(
            first_attempt,
            m.AssignmentAttempt.FEEDBACK_REJECTED,
            "二级判断不匹配",
        )

        first_attempt.refresh_from_db()
        next_attempt = m.AssignmentAttempt.objects.exclude(pk=first_attempt.pk).get()
        self.assertEqual(first_attempt.status, m.AssignmentAttempt.STATUS_REJECTED)
        self.assertEqual(first_attempt.feedback_note, "二级判断不匹配")
        self.assertEqual(next_attempt.resume, second_resume)
        self.assertEqual(next_attempt.status, m.AssignmentAttempt.STATUS_PENDING_DISPATCH)

    def test_ai_model_versions_come_from_backend_config(self):
        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "gpt-test",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
        with patch(
            "apps.pipeline.services.allocate.ai_service.screen_resume",
            return_value=self._ai_result(),
        ):
            allocate.run(mode="ai")

        decision = m.AgentDispatchDecision.objects.get()
        self.assertEqual(decision.model_name, "gpt-test")
        self.assertEqual(decision.prompt_version, "resume-screening-v1")
        self.assertEqual(decision.decision_version, "decision-v1")

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

    def test_force_reprocess_selected_reopens_all_system_statuses(self):
        status_candidates = [("raw", self.candidate, self.resume)]

        def create_candidate(code, *, job_category=""):
            candidate = m.Candidate.objects.create(
                identity_hash=f"candidate-force-{code}",
                name=f"候选人-{code}",
                phone=f"1390000{len(status_candidates):04d}",
                first_degree_platform="平台A",
                highest_degree_platform="平台A",
            )
            resume = m.Resume.objects.create(
                candidate=candidate,
                apply_id=f"FORCE-{code}",
                position_name="后端工程师",
                volunteer_rank=1,
                job_category=job_category,
                resume_file=f"{code}.pdf",
            )
            status_candidates.append((code, candidate, resume))
            return candidate, resume

        classified, classified_resume = create_candidate(
            "classified", job_category="技术类"
        )
        allocated, allocated_resume = create_candidate("allocated")
        pending_screening, pending_screening_resume = create_candidate(
            "pending_screening"
        )
        passed, passed_resume = create_candidate("screening_passed")
        rejected, rejected_resume = create_candidate("screening_rejected")

        def create_attempt(candidate, resume, status, *, workflow_status="in_progress"):
            workflow = m.CandidateWorkflow.objects.create(
                candidate=candidate,
                status=workflow_status,
                current_resume=resume,
                current_rank=1,
            )
            attempt = m.AssignmentAttempt.objects.create(
                workflow=workflow,
                resume=resume,
                attempt_no=1,
                source=m.AssignmentAttempt.SOURCE_RULE,
                status=status,
                department=self.department,
                contact=self.contact,
            )
            if workflow_status == m.CandidateWorkflow.STATUS_PASSED:
                workflow.passed_attempt = attempt
                workflow.save(update_fields=["passed_attempt"])
            return workflow, attempt

        create_attempt(
            allocated,
            allocated_resume,
            m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
        )
        create_attempt(
            pending_screening,
            pending_screening_resume,
            m.AssignmentAttempt.STATUS_DISPATCHED_L2,
        )
        create_attempt(
            passed,
            passed_resume,
            m.AssignmentAttempt.STATUS_PASSED,
            workflow_status=m.CandidateWorkflow.STATUS_PASSED,
        )
        create_attempt(
            rejected,
            rejected_resume,
            m.AssignmentAttempt.STATUS_REJECTED,
            workflow_status=m.CandidateWorkflow.STATUS_ARCHIVED,
        )

        actual_statuses = {
            code: system_status.candidate_system_status(
                m.Candidate.objects.prefetch_related(
                    "resumes", "workflow__attempts"
                ).get(pk=candidate.pk)
            )
            for code, candidate, _resume in status_candidates
        }
        self.assertEqual(set(actual_statuses.values()), set(system_status.LABELS))

        candidate_ids = [candidate.id for _code, candidate, _resume in status_candidates]
        allocate.run(
            mode="rule",
            scope={"candidate_ids": candidate_ids, "force_reprocess": True},
        )

        self.assertEqual(
            m.CandidateWorkflow.objects.filter(
                candidate_id__in=candidate_ids,
                dispatch_strategy="rule",
            ).count(),
            6,
        )
        for _code, candidate, _resume in status_candidates:
            candidate.workflow.refresh_from_db()
            self.assertEqual(
                candidate.workflow.status, m.CandidateWorkflow.STATUS_IN_PROGRESS
            )

    def test_force_reprocess_preserves_history_and_cancels_unfeedbacked_auto_attempts(self):
        allocate.run(mode="rule")
        passed_attempt = m.AssignmentAttempt.objects.get()
        allocate.dispatch_attempt(passed_attempt)
        allocate.submit_feedback(
            passed_attempt,
            m.AssignmentAttempt.FEEDBACK_PASSED,
            "业务确认通过",
        )
        workflow = self.candidate.workflow
        workflow.archive_reason = m.CandidateWorkflow.ARCHIVE_ALL_REJECTED
        workflow.archive_detail = "旧归档原因"
        workflow.block_reason = m.CandidateWorkflow.BLOCK_CONTACT_NOT_FOUND
        workflow.block_detail = "旧阻塞原因"
        workflow.completed_at = timezone.now()
        workflow.save(
            update_fields=[
                "archive_reason",
                "archive_detail",
                "block_reason",
                "block_detail",
                "completed_at",
            ]
        )
        old_decision = m.AgentDispatchDecision.objects.create(
            workflow=workflow,
            resume=self.resume,
            recommendation=m.AgentDispatchDecision.RECOMMEND_REVIEW,
            summary="历史 AI 决策",
        )
        pending_auto = m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=self.resume,
            attempt_no=2,
            source=m.AssignmentAttempt.SOURCE_AI,
            status=m.AssignmentAttempt.STATUS_PENDING_REVIEW,
            department=self.department,
            contact=self.contact,
        )
        manual_attempt = m.AssignmentAttempt.objects.create(
            workflow=workflow,
            resume=self.resume,
            attempt_no=3,
            source=m.AssignmentAttempt.SOURCE_MANUAL,
            status=m.AssignmentAttempt.STATUS_PENDING_DISPATCH,
            department=self.department,
            contact=self.contact,
        )

        allocate.run(
            mode="rule",
            scope={"candidate_ids": [self.candidate.id], "force_reprocess": True},
        )

        workflow.refresh_from_db()
        passed_attempt.refresh_from_db()
        pending_auto.refresh_from_db()
        manual_attempt.refresh_from_db()
        self.assertEqual(workflow.status, m.CandidateWorkflow.STATUS_IN_PROGRESS)
        self.assertIsNone(workflow.passed_attempt_id)
        self.assertEqual(workflow.archive_reason, "")
        self.assertEqual(workflow.archive_detail, "")
        self.assertEqual(workflow.block_reason, "")
        self.assertEqual(workflow.block_detail, "")
        self.assertIsNone(workflow.completed_at)
        self.assertEqual(passed_attempt.feedback_result, m.AssignmentAttempt.FEEDBACK_PASSED)
        self.assertEqual(passed_attempt.feedback_note, "业务确认通过")
        self.assertEqual(pending_auto.status, m.AssignmentAttempt.STATUS_CANCELLED)
        self.assertEqual(pending_auto.cancel_reason, m.AssignmentAttempt.CANCEL_RERUN)
        self.assertEqual(manual_attempt.status, m.AssignmentAttempt.STATUS_PENDING_DISPATCH)
        self.assertTrue(m.AgentDispatchDecision.objects.filter(pk=old_decision.pk).exists())
        self.assertEqual(workflow.attempts.count(), 4)

    def test_resume_import_scope_does_not_reopen_terminal_workflow(self):
        allocate.run(mode="rule")
        passed_attempt = m.AssignmentAttempt.objects.get()
        allocate.dispatch_attempt(passed_attempt)
        allocate.submit_feedback(passed_attempt, m.AssignmentAttempt.FEEDBACK_PASSED)
        workflow = self.candidate.workflow
        passed_attempt_count = workflow.attempts.count()

        allocate.run(
            mode="rule",
            scope={
                "candidate_ids": [self.candidate.id],
                "source": "resume_import",
            },
        )

        workflow.refresh_from_db()
        passed_attempt.refresh_from_db()
        self.assertEqual(workflow.status, m.CandidateWorkflow.STATUS_PASSED)
        self.assertEqual(workflow.passed_attempt, passed_attempt)
        self.assertEqual(workflow.attempts.count(), passed_attempt_count)
        self.assertEqual(passed_attempt.status, m.AssignmentAttempt.STATUS_PASSED)
