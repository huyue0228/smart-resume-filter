from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.core import models as m
from apps.pipeline import ai_config
from apps.pipeline.ai import service
from apps.pipeline.ai.schemas import ResumeScreeningOutput
from apps.pipeline.services import allocate


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
        service.close_cached_ai_clients()
        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "gpt-5.4-mini",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
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

    def tearDown(self):
        service.close_cached_ai_clients()

    def test_structured_result_is_scored_and_persisted_as_profile(self):
        output = screening_output(
            contact_id=self.contact.id,
            department_id=self.department.id,
            job_id=self.job.id,
        )
        with patch.object(service, "_extract_pdf", return_value=("a" * 64, "PDF 正文" * 80)), patch.object(
            service, "_call_model", return_value=output
        ):
            result = service.screen_resume(self.resume, self.job)

        self.assertEqual(result.job, self.job)
        self.assertEqual(result.contact, self.contact)
        self.assertAlmostEqual(result.confidence, 0.82)
        self.assertEqual(result.profile.parse_status, "parsed")
        self.assertEqual(result.profile.skills, ["Python", "Django"])
        self.assertEqual(result.profile.file_checksum, "a" * 64)

    def test_nul_bytes_are_removed_before_ai_data_is_persisted(self):
        output = screening_output(
            contact_id=self.contact.id,
            department_id=self.department.id,
            job_id=self.job.id,
        )
        output.profile.summary = "后端\x00开发"
        output.profile.projects[0].description = "实现\x00服务"
        output.profile.skills = ["Python\x00", "Django"]
        output.decision.summary = "建议\x00下发"
        output.decision.reason = "专业\x00匹配"
        output.decision.evidence = ["项目\x00证据"]
        output.decision.risks = ["风险\x00提示"]

        with patch.object(
            service,
            "_extract_pdf",
            return_value=("n" * 64, "PDF\x00正文" * 80),
        ), patch.object(service, "_call_model", return_value=output):
            result = service.screen_resume(self.resume, self.job)

        workflow = m.CandidateWorkflow.objects.create(
            candidate=self.resume.candidate,
            current_resume=self.resume,
            current_rank=1,
        )
        decision = allocate._create_agent_decision(workflow, self.resume, result)
        result.profile.refresh_from_db()

        self.assertNotIn("\x00", result.profile.raw_text)
        self.assertNotIn("\x00", result.profile.summary)
        self.assertNotIn("\x00", result.profile.project_experiences[0]["description"])
        self.assertNotIn("\x00", result.profile.skills[0])
        self.assertNotIn("\x00", decision.summary)
        self.assertNotIn("\x00", decision.reason)
        self.assertNotIn("\x00", decision.evidence[0])
        self.assertNotIn("\x00", decision.risks[0])

    def test_ai_service_error_message_removes_nul_bytes(self):
        error = service.AIServiceError("pdf_parse_failed", "解析\x00失败")

        self.assertEqual(error.message, "解析失败")

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
                service.screen_resume(self.resume, self.job)

        self.assertEqual(captured.exception.code, "reference_not_found")

    def test_guard_rejects_job_other_than_current_volunteer_job(self):
        other_job = m.Job.objects.create(
            department=self.department,
            public_name="产品经理",
            position_name="产品经理",
            category="产品类",
            is_active=True,
        )
        output = screening_output(
            contact_id=self.contact.id,
            department_id=self.department.id,
            job_id=other_job.id,
        )
        with patch.object(
            service, "_extract_pdf", return_value=("c" * 64, "PDF 正文" * 80)
        ), patch.object(service, "_call_model", return_value=output):
            with self.assertRaises(service.AIServiceError) as captured:
                service.screen_resume(self.resume, self.job)

        self.assertEqual(captured.exception.code, "reference_not_found")
        self.assertIn("当前志愿岗位", captured.exception.message)

    def test_missing_key_uses_internal_no_auth_client(self):
        context = service._current_job_context(self.job)
        m.Config.objects.filter(key="ai_connection_api_key").delete()
        client = SimpleNamespace(
            responses=SimpleNamespace(parse=Mock(return_value=SimpleNamespace(output_parsed=screening_output(
                contact_id=self.contact.id,
                department_id=self.department.id,
                job_id=self.job.id,
            ))))
        )
        http_client = Mock()
        with patch.object(service.httpx, "Client", return_value=http_client) as httpx_client, patch(
            "openai.OpenAI", return_value=client
        ) as openai_client:
            service._call_model(self.resume, "PDF 正文", context)

        self.assertEqual(openai_client.call_args.kwargs["api_key"], "internal-no-key")
        hook = httpx_client.call_args.kwargs["event_hooks"]["request"][0]
        request = service.httpx.Request(
            "POST", "https://model.internal/v1/responses", headers={"Authorization": "Bearer internal-no-key"}
        )
        hook(request)
        self.assertNotIn("Authorization", request.headers)

    def test_provider_exception_is_reduced_to_safe_summary(self):
        class ProviderError(Exception):
            status_code = 401

            def __str__(self):
                return "Authorization: Bearer sk-secret-must-not-leak"

        code, summary = service._safe_model_error(ProviderError())

        self.assertEqual(code, "llm_connection_error")
        self.assertIn("认证失败", summary)
        self.assertNotIn("sk-secret", summary)

    def test_rate_limit_releases_slot_retries_and_records_feedback(self):
        class ProviderRateLimit(Exception):
            status_code = 429
            response = SimpleNamespace(
                status_code=429,
                headers={"retry-after": "2"},
            )

        output = screening_output(
            contact_id=self.contact.id,
            department_id=self.department.id,
            job_id=self.job.id,
        )
        parse = Mock(
            side_effect=[
                ProviderRateLimit("secret provider detail"),
                SimpleNamespace(output_parsed=output),
            ]
        )
        client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
        first_slot = Mock(released=False)
        second_slot = Mock(released=False)
        context = service._current_job_context(self.job)

        with patch.object(
            service, "_get_openai_client", return_value=client
        ), patch.object(
            service.concurrency,
            "acquire_slot",
            side_effect=[first_slot, second_slot],
        ), patch.object(
            service.concurrency, "record_rate_limit"
        ) as record_rate, patch.object(
            service.concurrency, "record_retry"
        ) as record_retry, patch.object(
            service.concurrency, "retry_delay", return_value=0
        ):
            result = service._call_model(
                self.resume,
                "PDF 正文",
                context,
                processing_run_id=123,
            )

        self.assertEqual(result.decision.job_id, self.job.id)
        first_slot.release.assert_called_once_with("rate_limit", retry_after=2.0)
        second_slot.release.assert_called_once_with("success", retry_after=0)
        record_rate.assert_called_once_with(123)
        record_retry.assert_called_once_with(123)

    def test_client_initialization_exception_is_safely_mapped(self):
        context = service._current_job_context(self.job)
        with patch(
            "openai.OpenAI",
            side_effect=RuntimeError("proxy setup failed: sk-secret-must-not-leak"),
        ):
            with self.assertRaises(service.AIServiceError) as captured:
                service._call_model(self.resume, "PDF 正文", context)

        self.assertEqual(captured.exception.code, "llm_error")
        self.assertNotIn("sk-secret", captured.exception.message)

    def test_openai_client_disables_ssl_verification(self):
        http_client = Mock()
        client = SimpleNamespace(
            responses=SimpleNamespace(
                create=Mock(return_value=SimpleNamespace())
            )
        )

        with patch.object(service.httpx, "Client", return_value=http_client) as httpx_client, patch(
            "openai.OpenAI", return_value=client
        ) as openai_client:
            service.test_model_connection()

        httpx_client.assert_called_once_with(verify=False)
        self.assertIs(openai_client.call_args.kwargs["http_client"], http_client)

    def test_openai_client_is_reused_for_same_worker_connection(self):
        http_client = Mock()
        create = Mock(return_value=SimpleNamespace())
        client = SimpleNamespace(
            responses=SimpleNamespace(create=create)
        )

        with patch.object(service.httpx, "Client", return_value=http_client) as httpx_client, patch(
            "openai.OpenAI", return_value=client
        ) as openai_client:
            service.test_model_connection()
            service.test_model_connection()

        httpx_client.assert_called_once_with(verify=False)
        openai_client.assert_called_once()
        self.assertEqual(create.call_count, 2)

    def test_client_cache_key_tracks_connection_but_not_model_name(self):
        model_config = ai_config.get_ai_model_config()
        runtime_config = ai_config.get_ai_runtime_config()
        original = service._client_cache_key(model_config, runtime_config)

        self.assertEqual(
            service._client_cache_key(
                replace(model_config, model_name="another-model"), runtime_config
            ),
            original,
        )
        for changed in [
            replace(model_config, api_style="chat_json"),
            replace(model_config, base_url="https://another-model.internal/v1"),
            replace(model_config, api_key="another-key"),
        ]:
            self.assertNotEqual(
                service._client_cache_key(changed, runtime_config), original
            )
        self.assertNotEqual(
            service._client_cache_key(
                model_config, replace(runtime_config, timeout_seconds=120)
            ),
            original,
        )

    def test_cached_clients_are_closed_and_cleared(self):
        client = Mock()
        http_client = Mock()
        service._CLIENT_CACHE["test"] = (client, http_client)

        service.close_cached_ai_clients()

        client.close.assert_called_once_with()
        self.assertEqual(service._CLIENT_CACHE, {})

    def test_model_discovery_returns_sorted_model_ids_without_auth_header(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [{"id": "glm-4.7"}, {"id": "deepseek-v4"}, {"id": "glm-4.7"}]
        }
        m.Config.objects.filter(key="ai_connection_api_key").delete()

        with patch.object(service.httpx, "get", return_value=response) as get:
            models = service.list_available_models(base_url="https://model.internal/v1")

        self.assertEqual(models, ["deepseek-v4", "glm-4.7"])
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])
        self.assertEqual(get.call_args.args[0], "https://model.internal/v1/models")

    def test_model_discovery_uses_new_token_without_returning_it(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [{"id": "deepseek-v4"}]}

        with patch.object(service.httpx, "get", return_value=response) as get:
            models = service.list_available_models(
                base_url="https://model.internal/v1/", api_key="new-secret"
            )

        self.assertEqual(models, ["deepseek-v4"])
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"], "Bearer new-secret"
        )

    def test_model_discovery_reuses_saved_token_when_new_token_is_blank(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [{"id": "glm-4.7"}]}

        with patch.object(service.httpx, "get", return_value=response) as get:
            models = service.list_available_models(
                base_url="https://model.internal/v1", api_key="   "
            )

        self.assertEqual(models, ["glm-4.7"])
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"], "Bearer test-key"
        )

    def test_model_discovery_never_forwards_saved_token_to_changed_base_url(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [{"id": "deepseek-v4"}]}

        with patch.object(service.httpx, "get", return_value=response) as get:
            models = service.list_available_models(
                base_url="https://another-model.internal/v1", api_key=""
            )

        self.assertEqual(models, ["deepseek-v4"])
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])

    def test_model_discovery_maps_http_auth_failure_to_safe_message(self):
        request = service.httpx.Request("GET", "https://model.internal/v1/models")
        response = service.httpx.Response(401, request=request)
        error = service.httpx.HTTPStatusError(
            "Authorization: Bearer secret", request=request, response=response
        )

        with patch.object(service.httpx, "get", side_effect=error):
            with self.assertRaises(service.AIServiceError) as captured:
                service.list_available_models(base_url="https://model.internal/v1")

        self.assertEqual(captured.exception.code, "llm_connection_error")
        self.assertIn("认证失败", captured.exception.message)
        self.assertNotIn("secret", captured.exception.message)

    def test_provider_failure_does_not_raise_unbound_local_error(self):
        context = service._current_job_context(self.job)
        client = SimpleNamespace(
            responses=SimpleNamespace(
                parse=Mock(side_effect=RuntimeError("provider failed"))
            )
        )

        with patch("openai.OpenAI", return_value=client), patch.object(
            service.time, "sleep"
        ):
            with self.assertRaises(service.AIServiceError) as captured:
                service._call_model(self.resume, "PDF 正文", context)

        self.assertEqual(captured.exception.code, "llm_error")
        self.assertNotIsInstance(captured.exception.__cause__, UnboundLocalError)

    def test_chat_json_style_validates_schema(self):
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
        context = service._current_job_context(self.job)
        ai_config.save_ai_connection_config(
            {
                "api_style": "chat_json",
                "model_name": "deepseek-v4-pro",
                "base_url": "https://api.deepseek.com",
                "api_key": "test-key",
            }
        )
        http_client = Mock()
        with patch.object(service.httpx, "Client", return_value=http_client), patch(
            "openai.OpenAI", return_value=client
        ) as openai_client:
            result = service._call_model(self.resume, "PDF 正文", context)

        self.assertEqual(result.decision.job_id, self.job.id)
        openai_client.assert_called_once_with(
            api_key="test-key",
            timeout=60,
            max_retries=0,
            http_client=http_client,
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
            service.screen_resume(self.resume, self.job)

        self.assertEqual(captured.exception.code, "pdf_missing")

    def test_prompt_contains_only_current_volunteer_job(self):
        context = service._current_job_context(self.job)

        system, user = service._prompt(self.resume, "PDF 正文", context)
        payload = json.loads(user)

        self.assertEqual(payload["current_job"]["id"], self.job.id)
        self.assertNotIn("eligible_jobs", payload)
        self.assertIn("禁止推荐其它岗位", system)
