from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.permissions import ensure_rbac_defaults
from apps.core import models as m
from apps.pipeline import ai_config, prompt_management, runner
from apps.pipeline.ai import prompt_harness


class PromptManagementApiTests(TestCase):
    def setUp(self):
        ensure_rbac_defaults()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="prompt-admin",
            password="pass",
            role=User.ROLE_ADMIN,
        )
        self.admin.groups.add(Group.objects.get(name="管理员"))
        self.hr = User.objects.create_user(
            username="prompt-hr",
            password="pass",
            role=User.ROLE_HR,
        )
        self.hr.groups.add(Group.objects.get(name="HR"))
        self.client.force_authenticate(self.admin)
        ai_config.save_ai_connection_config(
            {
                "api_style": "responses",
                "model_name": "prompt-test-model",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
        ai_config.mark_ai_connection_tested()

    def _payload(self):
        response = self.client.get("/api/ai-prompts/")
        self.assertEqual(response.status_code, 200)
        return response.data

    def _save_modules(self, modules, lock_version=None):
        payload = self._payload()
        return self.client.patch(
            "/api/ai-prompts/draft/",
            {
                "modules": modules,
                "lock_version": (
                    payload["draft"]["lock_version"]
                    if lock_version is None
                    else lock_version
                ),
            },
            format="json",
        )

    def _mark_draft_tested(self):
        with patch.object(
            prompt_management,
            "_run_screening_prompt_test",
            return_value={"ok": True, "recommendation": "review", "evidence_count": 1},
        ), patch.object(
            prompt_management,
            "_run_school_prompt_test",
            return_value={"ok": True, "requested_count": 3, "returned_count": 2},
        ):
            response = self.client.post("/api/ai-prompts/draft/test/", format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["draft"]["test_valid"])
        return response.data["draft"]

    def test_migration_seeds_default_active_and_untested_draft(self):
        payload = self._payload()

        self.assertEqual(payload["active"]["version"], "resume-screening-v2")
        self.assertEqual(payload["active"]["modules"], prompt_harness.DEFAULT_MODULES)
        self.assertEqual(payload["draft"]["modules"], prompt_harness.DEFAULT_MODULES)
        self.assertFalse(payload["draft"]["test_valid"])
        self.assertEqual(
            [item["key"] for item in payload["module_definitions"]],
            list(prompt_harness.MODULE_KEYS),
        )
        preview = payload["full_prompt_preview"]
        screening_preview = preview["resume_screening"]
        school_preview = preview["school_province"]
        connection_preview = preview["connection_test"]
        self.assertEqual(
            screening_preview["editable_module_order"],
            list(prompt_harness.SCREENING_MODULE_KEYS),
        )
        self.assertIn(
            prompt_harness.SCREENING_SECURITY_BASE,
            str(screening_preview["fixed_system_sections"]),
        )
        self.assertIn(
            '"current_job"',
            screening_preview["user_payload_template"]["content"],
        )
        self.assertIn(
            '"ResumeScreeningOutput"',
            str(screening_preview["fixed_system_sections"]),
        )
        self.assertIn(
            prompt_harness.SCHOOL_SECURITY_BASE,
            str(school_preview["fixed_system_sections"]),
        )
        self.assertIn(
            "province 只能填写下列标准简称之一",
            str(school_preview["fixed_system_sections"]),
        )
        self.assertIn(
            '"schools"',
            school_preview["user_payload_template"]["content"],
        )
        self.assertEqual(connection_preview["editable_module_order"], [])
        self.assertEqual(connection_preview["fixed_system_sections"], [])
        self.assertEqual(
            connection_preview["fixed_user_prompt"]["content"],
            prompt_harness.MODEL_CONNECTION_TEST_PROMPT,
        )
        self.assertNotIn("真实简历", str(preview))
        self.assertNotIn("connection_fingerprint", str(payload))

    def test_all_prompt_endpoints_require_ai_connection_permission(self):
        self.client.force_authenticate(self.hr)
        version = m.AIPromptVersion.objects.get(
            status=m.AIPromptVersion.STATUS_ACTIVE
        ).version
        requests = [
            ("get", "/api/ai-prompts/", None),
            ("patch", "/api/ai-prompts/draft/", {}),
            ("post", "/api/ai-prompts/draft/reset/", {}),
            ("post", "/api/ai-prompts/draft/test/", {}),
            ("post", "/api/ai-prompts/draft/publish/", {}),
            ("get", "/api/ai-prompts/versions/", None),
            ("get", f"/api/ai-prompts/versions/{version}/", None),
            ("post", f"/api/ai-prompts/versions/{version}/restore/", {}),
        ]

        for method, url, body in requests:
            response = getattr(self.client, method)(url, body, format="json")
            self.assertEqual(response.status_code, 403, url)

    def test_draft_requires_exact_complete_modules_and_enforces_lengths(self):
        current = self._payload()["draft"]
        modules = deepcopy(current["modules"])
        modules.pop("screening_role_goal")
        response = self._save_modules(modules)
        self.assertEqual(response.status_code, 400)
        self.assertIn("缺少", response.data["detail"])

        modules = deepcopy(current["modules"])
        modules["unknown"] = "unexpected"
        response = self._save_modules(modules)
        self.assertEqual(response.status_code, 400)
        self.assertIn("未知", response.data["detail"])

        modules = deepcopy(current["modules"])
        modules["screening_role_goal"] = "x" * 8001
        response = self._save_modules(modules)
        self.assertEqual(response.status_code, 400)

        modules = {key: "x" * 5000 for key in prompt_harness.MODULE_KEYS}
        response = self._save_modules(modules)
        self.assertEqual(response.status_code, 400)
        self.assertIn("24,000", response.data["detail"])

    def test_draft_strips_nul_and_outer_whitespace(self):
        payload = self._payload()
        modules = deepcopy(payload["draft"]["modules"])
        modules["screening_role_goal"] = " \x00新的任务目标\x00 "

        response = self._save_modules(modules)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["modules"]["screening_role_goal"],
            "新的任务目标",
        )

    def test_optimistic_lock_conflict_does_not_overwrite_newer_draft(self):
        payload = self._payload()
        stale_lock = payload["draft"]["lock_version"]
        first_modules = deepcopy(payload["draft"]["modules"])
        first_modules["screening_role_goal"] = "第一位管理员保存的内容"
        first = self._save_modules(first_modules, stale_lock)
        self.assertEqual(first.status_code, 200)

        stale_modules = deepcopy(payload["draft"]["modules"])
        stale_modules["screening_role_goal"] = "过期页面尝试覆盖"
        second = self._save_modules(stale_modules, stale_lock)

        self.assertEqual(second.status_code, 409)
        draft = m.AIPromptVersion.objects.get(
            status=m.AIPromptVersion.STATUS_DRAFT
        )
        self.assertEqual(
            draft.modules["screening_role_goal"],
            "第一位管理员保存的内容",
        )

    def test_edit_and_connection_change_invalidate_prompt_test(self):
        tested = self._mark_draft_tested()
        modules = deepcopy(tested["modules"])
        modules["screening_role_goal"] += " 更新"
        saved = self._save_modules(modules, tested["lock_version"])
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(saved.data["test_valid"])
        self.assertIsNone(saved.data["tested_at"])

        self._mark_draft_tested()
        ai_config.save_ai_connection_config(
            {
                "api_style": "chat_json",
                "model_name": "changed-model",
                "base_url": "https://model.internal/v1",
                "api_key": "test-key",
            }
        )
        draft = self._payload()["draft"]
        self.assertFalse(draft["test_valid"])
        self.assertIsNone(draft["tested_at"])
        publish = self.client.post(
            "/api/ai-prompts/draft/publish/",
            {"lock_version": draft["lock_version"]},
            format="json",
        )
        self.assertEqual(publish.status_code, 400)

    def test_publish_is_atomic_and_restore_requires_retest(self):
        tested = self._mark_draft_tested()

        response = self.client.post(
            "/api/ai-prompts/draft/publish/",
            {"lock_version": tested["lock_version"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("只影响新提交", response.data["detail"])
        self.assertRegex(
            response.data["active"]["version"],
            r"^prompt-v000001-[0-9a-f]{8}$",
        )
        self.assertEqual(
            m.AIPromptVersion.objects.filter(
                status=m.AIPromptVersion.STATUS_ACTIVE
            ).count(),
            1,
        )
        self.assertEqual(
            m.AIPromptVersion.objects.filter(
                status=m.AIPromptVersion.STATUS_DRAFT
            ).count(),
            1,
        )
        self.assertFalse(response.data["draft"]["test_valid"])
        self.assertTrue(ai_config.is_ai_connection_tested())

        old_version = "resume-screening-v2"
        restored = self.client.post(
            f"/api/ai-prompts/versions/{old_version}/restore/",
            {"lock_version": response.data["draft"]["lock_version"]},
            format="json",
        )
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.data["restored_from_version"], old_version)
        self.assertFalse(restored.data["test_valid"])
        active = m.AIPromptVersion.objects.get(
            status=m.AIPromptVersion.STATUS_ACTIVE
        )
        self.assertEqual(active.version, response.data["active"]["version"])

    def test_versions_are_paginated_and_history_detail_is_read_only(self):
        response = self.client.get("/api/ai-prompts/versions/", {"page_size": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertNotIn("modules", response.data["results"][0])
        version = response.data["results"][0]["version"]
        detail = self.client.get(f"/api/ai-prompts/versions/{version}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("modules", detail.data)
        self.assertEqual(
            self.client.patch(
                f"/api/ai-prompts/versions/{version}/",
                {"modules": {}},
                format="json",
            ).status_code,
            405,
        )

    def test_run_submission_freezes_active_prompt_version(self):
        first = runner.create_run("step2", mode="ai", scope={})
        self.assertEqual(first.prompt_version, "resume-screening-v2")
        tested = self._mark_draft_tested()
        published = self.client.post(
            "/api/ai-prompts/draft/publish/",
            {"lock_version": tested["lock_version"]},
            format="json",
        )
        self.assertEqual(published.status_code, 200)

        second = runner.create_run("step2", mode="ai", scope={})

        self.assertEqual(first.prompt_version, "resume-screening-v2")
        self.assertEqual(second.prompt_version, published.data["active"]["version"])
        self.assertNotEqual(first.prompt_version, second.prompt_version)
