"""Agent Gateway：允许内嵌实现与独立 Go Kernel 在同一业务接口后切换。"""

from django.conf import settings

from apps.core import models as m
from apps.pipeline import ai_config
from apps.pipeline.ai import service as ai_service
from apps.pipeline.ai.structured_output import AIServiceError

from .client import AgentKernelClient
from .contracts import KernelPinV1, build_envelope
from .policy import validate_proposal


def is_agent_ready():
    """模型连接与执行内核都可用时，新的 Agent 任务才可提交。"""

    if not ai_config.is_ai_available():
        return False
    mode = getattr(settings, "AGENT_KERNEL_MODE", "embedded")
    if mode == "embedded":
        return True
    if mode == "remote":
        return AgentKernelClient().is_ready()
    return False


def evaluate_resume(
    resume,
    job,
    *,
    department=None,
    force=False,
    processing_run_id=None,
    cancelled=None,
    prompt_version=None,
):
    """统一评估入口；远端模式才跨进程，内嵌模式用于迁移与回归。"""

    mode = getattr(settings, "AGENT_KERNEL_MODE", "embedded")
    if mode == "embedded":
        return ai_service.screen_resume(
            resume,
            job,
            department=department,
            force=force,
            processing_run_id=processing_run_id,
            cancelled=cancelled,
            prompt_version=prompt_version,
        )
    if mode != "remote":
        raise AIServiceError("agent_kernel_unavailable", "Agent Kernel 运行模式配置无效")

    frozen_pin = None
    if processing_run_id is not None:
        run = m.ProcessingRun.objects.filter(pk=processing_run_id).first()
        if not run:
            raise AIServiceError("ai_reference_invalidated", "处理任务已不存在")
        if (
            not run.model_config_revision
            or run.model_config_revision
            != ai_config.current_ai_connection_fingerprint()
        ):
            raise AIServiceError(
                "agent_model_config_unavailable",
                "任务冻结的模型连接版本当前不可用，请重新提交任务",
            )
        try:
            frozen_pin = KernelPinV1(
                pin_id=run.pin_id,
                kernel_build=run.kernel_build,
                protocol_version=run.protocol_version,
                toolset_version=run.toolset_version,
                result_schema_version=run.result_schema_version,
                policy_version=run.policy_version,
                prompt_version=run.prompt_version,
                model_config_revision=run.model_config_revision,
            )
        except ValueError as exc:
            raise AIServiceError(
                "agent_model_config_unavailable",
                "任务缺少可用的 Agent Kernel 冻结版本",
            ) from exc

    prepared = ai_service.prepare_screening(
        resume,
        job,
        department=department,
        force=force,
        prompt_version=prompt_version,
    )
    try:
        envelope = build_envelope(
            prepared,
            processing_run_id=processing_run_id,
            pin=frozen_pin,
        )
        proposal = AgentKernelClient().evaluate(
            envelope,
            model_api_key=prepared.model_config.api_key,
        )
        output = validate_proposal(envelope, proposal)
        return ai_service.complete_screening(
            prepared,
            output,
            kernel_metadata={
                "pin_id": proposal.pin_id,
                "kernel_build": proposal.safe_trace.kernel_build,
                "protocol_version": envelope.pin.protocol_version,
                "toolset_version": envelope.pin.toolset_version,
                "safe_trace": proposal.safe_trace.model_dump(mode="json"),
            },
        )
    except AIServiceError as exc:
        ai_service.mark_screening_error(prepared, exc)
        raise
