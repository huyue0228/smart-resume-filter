"""AI Agent 配置抽象。

模型连接只从管理员在系统设置保存的 Config 记录读取。模型 profile 注册表只为
配置界面提供可选模板，运行时不读取环境变量或部署文件中的连接信息。
"""
import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings

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


AI_CONNECTION_CONFIG_KEYS = {
    "profile": "ai_connection_profile",
    "api_style": "ai_connection_api_style",
    "model_name": "ai_connection_model_name",
    "base_url": "ai_connection_base_url",
    "api_key": "ai_connection_api_key",
}


@dataclass(frozen=True)
class AIModelConfig:
    profile: str
    api_style: str
    model_name: str
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


def _model_registry():
    default_path = Path(__file__).resolve().parents[2] / "config" / "ai_models.json"
    path = default_path
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            registry = json.load(file_obj)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 AI 模型配置文件 {path}: {exc}") from exc
    profiles = registry.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("AI 模型配置文件缺少非空 profiles")
    return registry


def ai_connection_profiles():
    """返回可由管理员选择的模型 profile（不含任何密钥）。"""
    registry = _model_registry()
    return [
        {
            "key": key,
            "label": profile.get("label", key),
            "api_style": profile.get("api_style", ""),
            "default_model": profile.get("default_model", ""),
            "base_url": profile.get("base_url", ""),
        }
        for key, profile in registry["profiles"].items()
    ]


def _connection_value(name):
    from apps.core import models as m

    config = m.Config.objects.filter(key=AI_CONNECTION_CONFIG_KEYS[name]).first()
    if not config:
        return None
    value = config.value
    return value.get("value") if isinstance(value, dict) else value


def _secret_fernet():
    """用 Django SECRET_KEY 派生数据库密钥的加密器，不将 API Key 明文落库。"""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError("服务端缺少 cryptography，无法安全保存模型 API Key") from exc
    digest = hashlib.sha256(
        f"{settings.SECRET_KEY}:smart-resume-filter:ai-connection:v1".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(value):
    return _secret_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_api_key(value):
    if not value:
        return ""
    try:
        return _secret_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - 密钥轮换或数据损坏均不得泄漏原文
        raise ValueError("已保存的模型 API Key 无法解密，请由管理员重新保存") from exc


def save_ai_connection_config(payload):
    """保存管理员维护的连接参数；API Key 仅接受写入并以密文保存。"""
    registry = _model_registry()
    profile_name = payload["profile"]
    if profile_name not in registry["profiles"]:
        raise ValueError("未知模型 profile")
    if payload["api_style"] not in {"responses", "chat_json"}:
        raise ValueError("API 风格必须是 responses 或 chat_json")
    if not isinstance(payload["model_name"], str) or not payload["model_name"].strip():
        raise ValueError("模型名称不能为空")
    if not isinstance(payload["base_url"], str):
        raise ValueError("API 地址格式不正确")
    if payload["base_url"]:
        parsed = urlparse(payload["base_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API 地址必须是完整的 http(s) 地址")
    if payload.get("api_key") and not isinstance(payload["api_key"], str):
        raise ValueError("API Key 格式不正确")
    from apps.core import models as m

    for field in ["profile", "api_style", "model_name", "base_url"]:
        m.Config.objects.update_or_create(
            key=AI_CONNECTION_CONFIG_KEYS[field], defaults={"value": payload[field].strip()}
        )
    if payload.get("clear_api_key"):
        m.Config.objects.filter(key=AI_CONNECTION_CONFIG_KEYS["api_key"]).delete()
    elif payload.get("api_key"):
        m.Config.objects.update_or_create(
            key=AI_CONNECTION_CONFIG_KEYS["api_key"],
            defaults={"value": encrypt_api_key(payload["api_key"].strip())},
        )


def get_ai_connection_status():
    registry = _model_registry()
    default_profile_name = registry.get("default_profile", "openai")
    default_profile = registry["profiles"].get(default_profile_name, {})
    stored_key = _connection_value("api_key")
    return {
        "profile": _connection_value("profile") or default_profile_name,
        "api_style": _connection_value("api_style") or default_profile.get("api_style", ""),
        "model_name": _connection_value("model_name") or default_profile.get("default_model", ""),
        "base_url": _connection_value("base_url") or default_profile.get("base_url", ""),
        "api_key_configured": bool(stored_key),
        "api_key_source": "system_config" if stored_key else "not_configured",
        "profiles": ai_connection_profiles(),
        "profile_version": "profile-v1",
    }


def is_ai_enabled():
    """仅用于决定是否提交 AI 任务；不暴露任何连接或密钥信息。"""
    try:
        return bool(get_ai_model_config().api_key)
    except (RuntimeError, ValueError):
        return False


def get_ai_model_config():
    registry = _model_registry()
    profile_name = _connection_value("profile")
    api_style = _connection_value("api_style")
    model_name = _connection_value("model_name")
    base_url = _connection_value("base_url")
    if not all(isinstance(value, str) and value.strip() for value in [profile_name, api_style, model_name]):
        raise ValueError("AI 模型连接尚未完成配置，请由管理员在系统设置中保存")
    if base_url is None or not isinstance(base_url, str):
        raise ValueError("AI 模型连接的 API 地址尚未配置")
    try:
        profile = registry["profiles"][profile_name]
    except KeyError as exc:
        available = "、".join(sorted(registry["profiles"]))
        raise ValueError(f"未知模型 profile={profile_name}，可选：{available}") from exc
    if api_style not in ["responses", "chat_json"]:
        raise ValueError(
            f"AI profile {profile_name} 的 api_style 必须是 responses 或 chat_json"
        )
    saved_api_key = _connection_value("api_key")
    saved_base_url = _connection_value("base_url")
    return AIModelConfig(
        profile=profile_name,
        api_style=api_style,
        model_name=model_name,
        prompt_version="resume-screening-v1",
        decision_version="decision-v1",
        profile_version="profile-v1",
        parser_version="pypdf-v1",
        api_key=decrypt_api_key(saved_api_key) if saved_api_key else "",
        base_url=base_url,
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
