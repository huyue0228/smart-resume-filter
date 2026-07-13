from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.core import models as m
from apps.pipeline.ai import service
from apps.pipeline.ai.schemas import ResumeScreeningOutput


def screening_output(*, contact_id, department_id, job_id, recommendation="dispatch"):
    return ResumeScreeningOutput.model_validate(
        {
            "profile": {
                "education": [
                    {"school": "某大学", "degree": "硕士", "major": "计算机", "period": "2024-2027"}
                ],
                "major_direction": "计算机科学",
                "projects": [
                    {"name": "检索系统", "role": "开发", "period": "2025", "description": "实现服务", "evidence": "Python"}
                ],
                "internships": [],
                "skills": ["Python", "Django"],
                "certificates": [],
                "summary": "具备后端开发基础",
                "risk_flags": [],
            },
            "decision": {
                "recommendation": recommendation,
                "job_id": job_id,
                "department_id": department_id,
                "contact_id": contact_id,
                "score_breakdown": {
                    "major_match": 0.8,
                    "skills_match": 0.9,
                    "experience_evidence": 0.7,
                    "job_requirement": 0.8,
                    "department_certainty": 1.0,
                    "resume_quality": 0.8,
                },
                "summary": "建议进入后端岗位流程",
                "reason": "专业、技能和项目证据匹配",
                "evidence": ["Python 项目经历"],
                "risks": [],
            },
        }
    )


class AIResumeScreeningServiceTests(TestCase):
    def setUp(self):
        self.department = m.Department.objects.create(name="技术部", level=2)
        self.contact = m.Contact.objects.create(
            name="接口人",
            employee_no="AI-L2-1",
            department=self.department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        self.job = m.Job.objects.create(
            department=self.department,
            public_name="后端工程师",
            position_name="后端工程师",
            category="技术类",
            is_active=True,
        )
        m.JobMajor.objects.create(job=self.job, major="计算机")
        candidate = m.Candidate.objects.create(
            identity_hash="ai-candidate",
            name="张三",
            phone="13800000000",
            highest_major="计算机科学与技术",
        )
        self.resume = m.Resume.objects.create(
            candidate=candidate,
            apply_id="AI-1001",
            position_name="后端工程师",
            volunteer_rank=1,
            resume_file="张三（AI-1001）.pdf",
        )

    def test_structured_result_is_scored_and_persisted_as_profile(self):
        output = screening_output(
            contact_id=self.contact.id,
            department_id=self.department.id,
            job_id=self.job.id,
        )
        with patch.object(service, "_extract_pdf", return_value=("a" * 64, "PDF 正文" * 80)), patch.object(
            service, "_call_model", return_value=output
        ):
            result = service.screen_resume(self.resume, [self.job])

        self.assertEqual(result.job, self.job)
        self.assertEqual(result.contact, self.contact)
        self.assertAlmostEqual(result.confidence, 0.82)
        self.assertEqual(result.profile.parse_status, "parsed")
        self.assertEqual(result.profile.skills, ["Python", "Django"])
        self.assertEqual(result.profile.file_checksum, "a" * 64)

    def test_guard_rejects_contact_outside_recommended_department(self):
        other_department = m.Department.objects.create(name="财务部", level=2)
        other_contact = m.Contact.objects.create(
            name="越权接口人",
            employee_no="AI-L2-2",
            department=other_department,
            contact_level=m.Contact.LEVEL_SECONDARY,
            is_active=True,
        )
        output = screening_output(
            contact_id=other_contact.id,
            department_id=self.department.id,
            job_id=self.job.id,
        )
        with patch.object(service, "_extract_pdf", return_value=("b" * 64, "PDF 正文" * 80)), patch.object(
            service, "_call_model", return_value=output
        ):
            with self.assertRaises(service.AIServiceError) as captured:
                service.screen_resume(self.resume, [self.job])

        self.assertEqual(captured.exception.code, "reference_not_found")

    def test_missing_key_is_explicit_configuration_failure(self):
        context = service._eligible_context(self.resume, [self.job])
        with patch.dict(
            "os.environ",
            {
                "AI_PROFILE": "openai",
                "AI_MODEL_NAME": "gpt-5.4-mini",
                "AI_API_KEY_ENV": "OPENAI_API_KEY",
                "AI_BASE_URL_ENV": "OPENAI_BASE_URL",
                "OPENAI_API_KEY": "",
                "OPENAI_BASE_URL": "",
            },
            clear=False,
        ):
            with self.assertRaises(service.AIServiceError) as captured:
                service._call_model(self.resume, "PDF 正文", context)

        self.assertEqual(captured.exception.code, "ai_not_configured")

    def test_provider_exception_is_reduced_to_safe_summary(self):
        class ProviderError(Exception):
            status_code = 401

            def __str__(self):
                return "Authorization: Bearer sk-secret-must-not-leak"

        code, summary = service._safe_model_error(ProviderError())

        self.assertEqual(code, "llm_connection_error")
        self.assertIn("认证失败", summary)
        self.assertNotIn("sk-secret", summary)

    def test_client_initialization_exception_is_safely_mapped(self):
        context = service._eligible_context(self.resume, [self.job])
        with patch.dict(
            "os.environ",
            {
                "AI_PROFILE": "openai",
                "AI_MODEL_NAME": "gpt-5.4-mini",
                "AI_API_KEY_ENV": "OPENAI_API_KEY",
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), patch(
            "openai.OpenAI",
            side_effect=RuntimeError("proxy setup failed: sk-secret-must-not-leak"),
        ):
            with self.assertRaises(service.AIServiceError) as captured:
                service._call_model(self.resume, "PDF 正文", context)

        self.assertEqual(captured.exception.code, "llm_error")
        self.assertNotIn("sk-secret", captured.exception.message)

    def test_deepseek_uses_chat_json_output_and_validates_schema(self):
        output = screening_output(
            contact_id=self.contact.id,
            department_id=self.department.id,
            job_id=self.job.id,
        )
        create = Mock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=output.model_dump_json())
                    )
                ]
            )
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        context = service._eligible_context(self.resume, [self.job])
        with patch.dict(
            "os.environ",
            {
                "AI_PROFILE": "deepseek",
                "AI_MODEL_NAME": "deepseek-v4-pro",
                "AI_API_KEY_ENV": "DEEPSEEK_API_KEY",
                "AI_BASE_URL_ENV": "DEEPSEEK_BASE_URL",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            },
        ), patch("openai.OpenAI", return_value=client) as openai_client:
            result = service._call_model(self.resume, "PDF 正文", context)

        self.assertEqual(result.decision.job_id, self.job.id)
        openai_client.assert_called_once_with(
            api_key="test-key",
            timeout=60,
            max_retries=0,
            base_url="https://api.deepseek.com",
        )
        self.assertEqual(create.call_args.kwargs["model"], "deepseek-v4-pro")
        self.assertEqual(
            create.call_args.kwargs["response_format"], {"type": "json_object"}
        )

    def test_pdf_missing_does_not_fall_back_to_metadata(self):
        self.resume.resume_file = ""
        self.resume.save(update_fields=["resume_file"])

        with self.assertRaises(service.AIServiceError) as captured:
            service.screen_resume(self.resume, [self.job])

        self.assertEqual(captured.exception.code, "pdf_missing")
