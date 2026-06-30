"""流水线编排：单步或一键全流程，记录 ProcessingRun。"""
from django.utils import timezone

from apps.core.models import ProcessingRun

from .services import allocate, classify_job, classify_school, dedup, demand

STEP_FUNCS = {
    "step1": lambda mode, scope: dedup.run(scope),
    "step2": lambda mode, scope: allocate.run(scope, mode),
    "step3": lambda mode, scope: classify_school.run(scope),
    "step4": lambda mode, scope: demand.run(scope),
    # 兼容旧 demo 入口。当前设计中分配已经合并进 Step2。
    "step5": lambda mode, scope: allocate.run(scope, mode),
}

# 一键全流程：前置院校分类、需求录入先完成，再执行候选人主流程。
STEP_ORDER = ["step3", "step4", "step1", "step2"]


def run_step(step, mode="rule", scope=None):
    scope = scope or {}
    run = ProcessingRun.objects.create(
        step=step, mode=mode, scope=scope, status="running", started_at=timezone.now()
    )
    try:
        if step == "all":
            msgs = [f"{s}: {STEP_FUNCS[s](mode, scope)}" for s in STEP_ORDER]
            message = " | ".join(msgs)
        elif step in STEP_FUNCS:
            message = STEP_FUNCS[step](mode, scope)
        else:
            raise ValueError(f"未知步骤: {step}")
        run.status = "success"
        run.message = message
    except Exception as exc:  # noqa: BLE001 - 记录失败信息供前端展示
        run.status = "failed"
        run.message = f"{type(exc).__name__}: {exc}"
    run.finished_at = timezone.now()
    run.save()
    return run
