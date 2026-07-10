"""流水线编排：单步或一键全流程，记录 ProcessingRun。"""
from django.utils import timezone

from apps.core.models import ProcessingRun
from apps.pipeline import ai_config

from .services import allocate, classify_job, classify_school, dedup, demand

STEP_FUNCS = {
    "step1": lambda mode, scope, run: dedup.run(scope),
    "step2": lambda mode, scope, run: allocate.run(scope, mode, processing_run=run),
    "step3": lambda mode, scope, run: classify_school.run(scope),
    "step4": lambda mode, scope, run: demand.run(scope),
    # 兼容旧 demo 入口。当前设计中分配已经合并进 Step2。
    "step5": lambda mode, scope, run: allocate.run(scope, mode, processing_run=run),
}

# 一键全流程：前置院校分类、需求录入先完成，再执行候选人主流程。
STEP_ORDER = ["step3", "step4", "step1", "step2"]


def create_run(step, mode="rule", scope=None):
    if step != "all" and step not in STEP_FUNCS:
        raise ValueError(f"未知步骤: {step}")
    if mode not in ["rule", "ai"]:
        raise ValueError(f"未知模式: {mode}")
    versions = {}
    if mode == "ai":
        config = ai_config.get_ai_model_config()
        versions = {
            "model_name": config.model_name,
            "prompt_version": config.prompt_version,
            "decision_version": config.decision_version,
        }
    return ProcessingRun.objects.create(
        step=step, mode=mode, scope=scope or {}, status="pending", **versions
    )


def execute_run(run_id):
    run = ProcessingRun.objects.get(pk=run_id)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])
    step, mode, scope = run.step, run.mode, run.scope or {}
    try:
        if step == "all":
            msgs = [f"{s}: {STEP_FUNCS[s](mode, scope, run)}" for s in STEP_ORDER]
            message = " | ".join(msgs)
        else:
            message = STEP_FUNCS[step](mode, scope, run)
        run.refresh_from_db()
        run.status = "partial_failed" if run.failed_count else "success"
        run.message = message
    except Exception as exc:  # noqa: BLE001 - 记录失败信息供前端展示
        run.status = "failed"
        run.message = f"{type(exc).__name__}: {exc}"
        run.error = run.message
    run.finished_at = timezone.now()
    run.save()
    return run


def run_step(step, mode="rule", scope=None):
    """同步兼容入口；API 生产路径通过 Celery 调用 execute_run。"""
    scope = scope or {}
    return execute_run(create_run(step, mode=mode, scope=scope).id)
