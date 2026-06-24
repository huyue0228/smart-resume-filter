"""Celery 任务包装。Demo eager 同步执行；生产用 Redis broker 异步。"""
from celery import shared_task

from . import runner


@shared_task
def run_step_task(step, mode="rule", scope=None):
    run = runner.run_step(step, mode, scope)
    return run.id
