"""流水线编排：单步、上传后主流程或一键全流程，记录共享 ProcessingRun。"""
from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from apps.core.models import (
    CandidateWorkflow,
    ProcessingRun,
    ProcessingRunScopeItem,
    ProcessingRunStage,
)
from apps.pipeline import ai_config

from .cancellation import RunCancelled, raise_if_cancel_requested
from .services import allocate, classify_job, classify_school, dedup, demand

STEP_FUNCS = {
    "step1": lambda mode, scope, run: dedup.run(scope),
    "step2": lambda mode, scope, run: allocate.run(scope, mode, processing_run=run),
    "step3": lambda mode, scope, run: classify_school.run(scope),
    "step4": lambda mode, scope, run: demand.run(scope),
    # 兼容旧 demo 入口。当前设计中分配已经合并进 Step2。
    "step5": lambda mode, scope, run: allocate.run(scope, mode, processing_run=run),
}

RESUME_PROCESS_STEP = "resume_process"
STAGE_LABELS = {
    "step1": "查重与志愿排序",
    "step2": "简历分类、分配与下发",
    "step3": "院校分类",
    "step4": "需求数据准备核对",
    "step5": "简历分类、分配与下发",
}

# 一键全流程：前置院校分类、需求录入先完成，再执行候选人主流程。
STEP_ORDER = ["step3", "step4", "step1", "step2"]


def _candidate_ids_for_run(step, scope):
    """在提交时冻结候选人范围，后台执行不再重新解释页面筛选。"""
    candidate_ids = scope.get("candidate_ids") or []
    if candidate_ids:
        return sorted({int(candidate_id) for candidate_id in candidate_ids})
    if step in {"step2", "step5", RESUME_PROCESS_STEP}:
        return list(allocate.candidate_ids_for_scope(scope))
    if step == "step1":
        return list(dedup.candidate_ids_for_scope(scope))
    return []


def _scope_summary(scope, candidate_ids):
    summary = {"candidate_count": len(candidate_ids)}
    statuses = scope.get("system_statuses") or []
    if statuses:
        summary["system_statuses"] = statuses
    source = scope.get("source")
    if source:
        summary["source"] = source
    return summary


def _stage_steps(step):
    if step == RESUME_PROCESS_STEP:
        return ["step1", "step2"]
    if step == "all":
        return STEP_ORDER
    return [step]


def create_run(step, mode="rule", scope=None, created_by=None):
    if step not in {"all", RESUME_PROCESS_STEP} and step not in STEP_FUNCS:
        raise ValueError(f"未知步骤: {step}")
    if mode not in ["rule", "ai"]:
        raise ValueError(f"未知模式: {mode}")
    scope = deepcopy(scope or {})
    candidate_ids = _candidate_ids_for_run(step, scope)
    # candidate_ids 保存在范围明细表；scope 只保留触发时的可审计筛选快照。
    scope.pop("candidate_ids", None)
    versions = {}
    if mode == "ai":
        config = ai_config.get_ai_model_config()
        versions = {
            "model_name": config.model_name,
            "prompt_version": config.prompt_version,
            "decision_version": config.decision_version,
        }
    run = ProcessingRun.objects.create(
        step=step,
        mode=mode,
        scope=scope,
        scope_summary=_scope_summary(scope, candidate_ids),
        status="pending",
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
        created_by_username_snapshot=(
            created_by.username if getattr(created_by, "is_authenticated", False) else ""
        ),
        **versions,
    )
    workflow_revisions = dict(
        CandidateWorkflow.objects.filter(candidate_id__in=candidate_ids).values_list(
            "candidate_id", "revision"
        )
    )
    ProcessingRunScopeItem.objects.bulk_create(
        [
            ProcessingRunScopeItem(
                run=run,
                candidate_id=candidate_id,
                workflow_revision_at_submit=workflow_revisions.get(candidate_id),
            )
            for candidate_id in candidate_ids
        ],
        batch_size=1000,
    )
    ProcessingRunStage.objects.bulk_create(
        [
            ProcessingRunStage(
                run=run,
                sequence=index,
                step=stage_step,
                label=STAGE_LABELS[stage_step],
            )
            for index, stage_step in enumerate(_stage_steps(step), start=1)
        ]
    )
    return run


def create_runs(step, modes, scope=None, created_by=None):
    """为一次多策略处理分别建单，并标记为同一范围的协同运行。"""
    unique_modes = list(dict.fromkeys(modes or []))
    if not unique_modes:
        raise ValueError("至少选择一种分配方式")
    if any(mode not in {"rule", "ai"} for mode in unique_modes):
        raise ValueError("存在未知分配方式")
    if "ai" in unique_modes and not ai_config.is_ai_enabled():
        raise ValueError("AI 模式未启用，请先由管理员完成模型连接配置并测试")
    run_scope = deepcopy(scope or {})
    if len(unique_modes) > 1:
        run_scope["parallel_modes"] = True
    return [
        create_run(step, mode=mode, scope=run_scope, created_by=created_by)
        for mode in unique_modes
    ]


def _run_scope(run):
    scope = deepcopy(run.scope or {})
    candidate_ids = list(run.scope_items.order_by("candidate_id").values_list("candidate_id", flat=True))
    if candidate_ids:
        scope["candidate_ids"] = candidate_ids
    return scope


def _heartbeat(run, *, stage=""):
    run.current_stage = stage
    run.last_heartbeat_at = timezone.now()
    run.save(update_fields=["current_stage", "last_heartbeat_at"])


def _run_one_stage(run, stage, mode, scope):
    raise_if_cancel_requested(run)
    stage_record = run.stages.get(step=stage)
    stage_record.status = "running"
    stage_record.started_at = timezone.now()
    stage_record.save(update_fields=["status", "started_at"])
    _heartbeat(run, stage=stage)
    if stage == "step1":
        message = dedup.run(scope, processing_run=run, processing_stage=stage_record)
    elif stage in {"step2", "step5"}:
        message = allocate.run(
            scope, mode, processing_run=run, processing_stage=stage_record
        )
    else:
        message = STEP_FUNCS[stage](mode, scope, run)
    run.refresh_from_db()
    stage_record.refresh_from_db()
    stage_record.status = "partial_failed" if stage_record.failed_count else "success"
    stage_record.message = message
    stage_record.finished_at = timezone.now()
    stage_record.save(update_fields=["status", "message", "finished_at"])
    return message


def execute_run(run_id):
    # 只由第一个成功领取 pending 任务的 worker 运行，避免取消请求与 worker
    # 启动同时发生时，把已取消任务重新写回 running。
    with transaction.atomic():
        run = ProcessingRun.objects.select_for_update().get(pk=run_id)
        if run.status != "pending" or run.cancel_requested_at:
            if run.status == "cancelling":
                run.status = "cancelled"
                run.cancelled_at = run.cancelled_at or timezone.now()
                run.finished_at = run.cancelled_at
                run.current_stage = ""
                run.message = "任务已取消；未开始处理"
                run.save(
                    update_fields=[
                        "status",
                        "cancelled_at",
                        "finished_at",
                        "current_stage",
                        "message",
                    ]
                )
            return run
        run.status = "running"
        run.started_at = timezone.now()
        run.last_heartbeat_at = run.started_at
        run.save(update_fields=["status", "started_at", "last_heartbeat_at"])
    step, mode, scope = run.step, run.mode, _run_scope(run)
    try:
        messages = [
            f"{stage}: {_run_one_stage(run, stage, mode, scope)}"
            for stage in _stage_steps(step)
        ]
        message = " | ".join(messages)
        run.refresh_from_db()
        run.status = "partial_failed" if run.failed_count else "success"
        run.message = message
    except RunCancelled:
        run.refresh_from_db()
        run.status = "cancelled"
        run.message = "任务已取消；已完成的候选人处理结果已保留"
        run.cancelled_at = run.cancelled_at or timezone.now()
        run.stages.filter(status="running").update(
            status="cancelled", finished_at=run.cancelled_at
        )
    except Exception as exc:  # noqa: BLE001 - 记录失败信息供前端展示
        run.status = "failed"
        run.message = f"{type(exc).__name__}: {exc}"
        run.error = run.message
    run.finished_at = timezone.now()
    run.last_heartbeat_at = run.finished_at
    run.current_stage = ""
    run.save()
    return run


def run_step(step, mode="rule", scope=None):
    """同步兼容入口；API 生产路径通过 Celery 调用 execute_run。"""
    scope = scope or {}
    return execute_run(create_run(step, mode=mode, scope=scope).id)
