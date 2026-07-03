"""AI Agent 配置抽象。

敏感配置只从环境变量读取；可由 HR 调整的运行参数仍保存在 Config 表，
但默认值和元数据集中维护在本模块，避免散落在 API 和分配服务里。
"""
import os
from dataclasses import dataclass


PUBLIC_AI_CONFIG_REGISTRY = {
    "ai_dispatch_threshold": {
        "label": "AI 自动下发阈值",
        "description": "置信度大于等于该值时，AI 建议可进入待下发。",
        "value_type": "number",
        "default": 0.75,
    },
    "ai_review_threshold": {
        "label": "AI 人工复核阈值",
        "description": "置信度大于等于该值且低于自动下发阈值时，进入 HR 复核。",
        "value_type": "number",
        "default": 0.5,
    },
    "ai_timeout_seconds": {
        "label": "AI 超时时间",
        "description": "单次 AI 调用超时时间，单位秒。",
        "value_type": "integer",
        "default": 60,
    },
    "ai_concurrency": {
        "label": "AI 并发数",
        "description": "后台 AI 任务最大并发数量。",
        "value_type": "integer",
        "default": 2,
    },
    "ai_retry_count": {
        "label": "AI 重试次数",
        "description": "AI 失败后允许自动重试的次数。",
        "value_type": "integer",
        "default": 1,
    },
    "ai_retry_backoff_seconds": {
        "label": "AI 重试退避",
        "description": "AI 重试间隔，单位秒。",
        "value_type": "integer",
        "default": 10,
    },
}


@dataclass(frozen=True)
class AIModelConfig:
    provider: str
    model_name: str
    api_key_env: str
    base_url_env: str
    prompt_version: str
    decision_version: str
    api_key: str
    base_url: str


@dataclass(frozen=True)
class AIRuntimeConfig:
    dispatch_threshold: float
    review_threshold: float
    timeout_seconds: int
    concurrency: int
    retry_count: int
    retry_backoff_seconds: int


def _env(key, default=""):
    return os.environ.get(key, default)


def get_ai_model_config():
    api_key_env = _env("AI_API_KEY_ENV", "OPENAI_API_KEY")
    base_url_env = _env("AI_BASE_URL_ENV", "OPENAI_BASE_URL")
    return AIModelConfig(
        provider=_env("AI_PROVIDER", "openai"),
        model_name=_env("AI_MODEL_NAME", _env("OPENAI_MODEL", "demo-agent")),
        api_key_env=api_key_env,
        base_url_env=base_url_env,
        prompt_version=_env("AI_PROMPT_VERSION", "demo-v1"),
        decision_version=_env("AI_DECISION_VERSION", "demo-v1"),
        api_key=_env(api_key_env),
        base_url=_env(base_url_env),
    )


def _config_value(key, default):
    from apps.core import models as m

    config = m.Config.objects.filter(key=key).first()
    value = config.value if config else default
    if isinstance(value, dict):
        return value.get("value", default)
    return value


def _config_float(key):
    default = PUBLIC_AI_CONFIG_REGISTRY[key]["default"]
    try:
        return float(_config_value(key, default))
    except (TypeError, ValueError):
        return default


def _config_int(key):
    default = PUBLIC_AI_CONFIG_REGISTRY[key]["default"]
    try:
        return int(_config_value(key, default))
    except (TypeError, ValueError):
        return default


def get_ai_runtime_config():
    return AIRuntimeConfig(
        dispatch_threshold=_config_float("ai_dispatch_threshold"),
        review_threshold=_config_float("ai_review_threshold"),
        timeout_seconds=_config_int("ai_timeout_seconds"),
        concurrency=_config_int("ai_concurrency"),
        retry_count=_config_int("ai_retry_count"),
        retry_backoff_seconds=_config_int("ai_retry_backoff_seconds"),
    )
