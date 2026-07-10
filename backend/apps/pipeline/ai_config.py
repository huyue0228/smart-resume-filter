"""AI Agent 配置抽象。

敏感配置只从环境变量读取；可由 HR 调整的运行参数仍保存在 Config 表，
但默认值和元数据集中维护在本模块，避免散落在 API 和分配服务里。
"""
import os
import json
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    # 本地 runserver/test 可直接读取仓库根目录 .env；容器显式环境变量优先。
    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
except ImportError:
    # 镜像/部署依赖未更新时仍保持显式环境变量配置可用。
    pass


PUBLIC_AI_CONFIG_REGISTRY = {
    "ai_dispatch_threshold": {
        "label": "AI 自动下发阈值",
        "description": "置信度大于等于该值时，AI 建议可进入待下发。",
        "value_type": "number",
        "default": 0.75,
        "min": 0,
        "max": 1,
    },
    "ai_review_threshold": {
        "label": "AI 人工复核阈值",
        "description": "置信度大于等于该值且低于自动下发阈值时，进入 HR 复核。",
        "value_type": "number",
        "default": 0.5,
        "min": 0,
        "max": 1,
    },
    "ai_timeout_seconds": {
        "label": "AI 超时时间",
        "description": "单次 AI 调用超时时间，单位秒。",
        "value_type": "integer",
        "default": 60,
        "min": 5,
        "max": 600,
    },
    "ai_concurrency": {
        "label": "AI 并发数",
        "description": "后台 AI 任务最大并发数量。",
        "value_type": "integer",
        "default": 2,
        "min": 1,
        "max": 20,
    },
    "ai_retry_count": {
        "label": "AI 重试次数",
        "description": "AI 失败后允许自动重试的次数。",
        "value_type": "integer",
        "default": 1,
        "min": 0,
        "max": 5,
    },
    "ai_retry_backoff_seconds": {
        "label": "AI 重试退避",
        "description": "AI 重试间隔，单位秒。",
        "value_type": "integer",
        "default": 10,
        "min": 0,
        "max": 300,
    },
}


@dataclass(frozen=True)
class AIModelConfig:
    profile: str
    provider: str
    api_style: str
    model_name: str
    api_key_env: str
    base_url_env: str
    prompt_version: str
    decision_version: str
    profile_version: str
    parser_version: str
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
    return os.environ.get(key) or default


def _model_registry():
    default_path = Path(__file__).resolve().parents[2] / "config" / "ai_models.json"
    path = Path(_env("AI_MODEL_CONFIG_FILE", str(default_path))).expanduser()
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            registry = json.load(file_obj)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 AI 模型配置文件 {path}: {exc}") from exc
    profiles = registry.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("AI 模型配置文件缺少非空 profiles")
    return registry


def get_ai_model_config():
    registry = _model_registry()
    profile_name = _env(
        "AI_PROFILE",
        _env("AI_PROVIDER", registry.get("default_profile", "openai")),
    )
    try:
        profile = registry["profiles"][profile_name]
    except KeyError as exc:
        available = "、".join(sorted(registry["profiles"]))
        raise ValueError(
            f"未知 AI_PROFILE={profile_name}，可选：{available}"
        ) from exc
    api_style = _env("AI_API_STYLE", profile.get("api_style", ""))
    if api_style not in ["responses", "chat_json"]:
        raise ValueError(
            f"AI profile {profile_name} 的 api_style 必须是 responses 或 chat_json"
        )
    api_key_env = _env("AI_API_KEY_ENV", profile.get("api_key_env", ""))
    base_url_env = _env("AI_BASE_URL_ENV", profile.get("base_url_env", ""))
    return AIModelConfig(
        profile=profile_name,
        provider=profile_name,
        api_style=api_style,
        model_name=_env(
            "AI_MODEL_NAME",
            _env("OPENAI_MODEL", profile.get("default_model", "")),
        ),
        api_key_env=api_key_env,
        base_url_env=base_url_env,
        prompt_version=_env("AI_PROMPT_VERSION", "resume-screening-v1"),
        decision_version=_env("AI_DECISION_VERSION", "decision-v1"),
        profile_version=_env("AI_PROFILE_VERSION", "profile-v1"),
        parser_version=_env("AI_PARSER_VERSION", "pypdf-v1"),
        api_key=_env(api_key_env) if api_key_env else "",
        base_url=(
            _env(base_url_env, profile.get("base_url", ""))
            if base_url_env
            else profile.get("base_url", "")
        ),
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
