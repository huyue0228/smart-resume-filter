"""独立 Agent Kernel HTTP 客户端；异常只暴露受控错误。"""

import logging

import httpx
from django.conf import settings
from pydantic import ValidationError

from apps.pipeline.ai.structured_output import AIServiceError

from .contracts import (
    PROTOCOL_VERSION,
    RESULT_SCHEMA_VERSION,
    TOOLSET_VERSION,
    AgentActionProposalV1,
    CaseEnvelopeV1,
)


logger = logging.getLogger(__name__)


ERROR_CODES = {
    "llm_timeout": "模型请求超时",
    "agent_cancelled": "Agent 任务已取消",
    "agent_budget_exhausted": "Agent 已达到本次工具或轮次预算",
    "agent_evidence_invalid": "Agent 返回的简历证据无法校验",
    "ai_connection_error": "模型服务连接失败",
    "agent_invalid_output": "Agent 未返回符合协议的结果",
    "agent_kernel_unavailable": "Agent Kernel 服务不可用",
}


class AgentKernelClient:
    def __init__(self, *, base_url=None, token=None):
        self.base_url = (
            base_url or getattr(settings, "AGENT_KERNEL_URL", "http://127.0.0.1:8090")
        ).rstrip("/")
        self.token = token or getattr(settings, "AGENT_KERNEL_TOKEN", "")

    def is_ready(self):
        """只接受与控制面冻结版本完全一致的健康实例。"""

        if not self.token:
            return False
        try:
            response = httpx.get(f"{self.base_url}/healthz", timeout=3.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        expected = {
            "ok": True,
            "build": getattr(settings, "AGENT_KERNEL_BUILD", "dev"),
            "protocol_version": PROTOCOL_VERSION,
            "toolset_version": TOOLSET_VERSION,
            "result_schema_version": RESULT_SCHEMA_VERSION,
        }
        return isinstance(payload, dict) and all(
            payload.get(key) == value for key, value in expected.items()
        )

    def evaluate(self, envelope: CaseEnvelopeV1, *, model_api_key=""):
        if not self.token:
            raise AIServiceError(
                "agent_kernel_unavailable", "Agent Kernel 服务令牌尚未配置"
            )
        timeout = httpx.Timeout(
            envelope.model.timeout_seconds + 15,
            connect=min(10, envelope.model.timeout_seconds),
        )
        try:
            response = httpx.post(
                f"{self.base_url}/v1/evaluate",
                json=envelope.model_dump(mode="json"),
                headers={
                    "X-Agent-Kernel-Token": self.token,
                    "X-Model-API-Key": model_api_key,
                },
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise AIServiceError("llm_timeout", ERROR_CODES["llm_timeout"]) from exc
        except httpx.HTTPError as exc:
            raise AIServiceError(
                "agent_kernel_unavailable", "Agent Kernel 服务不可用"
            ) from exc
        if response.status_code != 200:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            code = payload.get("code")
            if code not in ERROR_CODES:
                code = "agent_kernel_unavailable"
            message = ERROR_CODES.get(code, "Agent Kernel 服务不可用")
            logger.warning(
                "Agent Kernel rejected request status=%s code=%s",
                response.status_code,
                code,
            )
            safe_trace = payload.get("safe_trace")
            raise AIServiceError(
                code,
                message,
                safe_trace=safe_trace if isinstance(safe_trace, dict) else {},
            )
        try:
            return AgentActionProposalV1.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise AIServiceError(
                "agent_invalid_output", "Agent Kernel 返回内容不符合协议"
            ) from exc
