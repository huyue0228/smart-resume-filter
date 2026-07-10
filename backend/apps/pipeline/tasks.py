"""Celery 任务包装。Demo eager 同步执行；生产用 Redis broker 异步。"""
from celery import shared_task

from . import runner


@shared_task
def execute_run_task(run_id):
    run = runner.execute_run(run_id)
    return run.id


@shared_task
def run_step_task(step, mode="rule", scope=None):
    """保留给旧调用方的同步建单包装。"""
    return runner.run_step(step, mode, scope).id
