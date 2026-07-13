"""Celery 任务包装。Demo eager 同步执行；生产用 Redis broker 异步。"""
from celery import shared_task

from . import runner


@shared_task
def execute_runs_sequence_task(run_ids):
    """同一批候选人的 Rule/AI 任务按顺序运行，保留两份独立任务进度。"""
    return [runner.execute_run(run_id).id for run_id in run_ids]
