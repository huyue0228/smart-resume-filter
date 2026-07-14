"""AI Agent 配置抽象。

模型连接只从管理员在系统设置保存的 Config 记录读取。内网模型共用一套连接
字段，不区分服务商或 Profile，也不从环境变量或部署文件读取连接信息。
"""
import base64
import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

PUBLIC_AI_CONFIG_REGISTRY = {
    "ai_enabled": {
        "label": "AI 分配开关",
        "description": "关闭时新任务只运行规则分配；开启时新任务只运行 AI 分配。",
        "value_type": "boolean",
        "default": False,
    },
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
        "label": "AI 并发上限",
        "description": "所有后台任务共享的模型调用并发上限；系统会根据限流情况自动升降。",
        "value_type": "integer",
        "default": 8,
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
    "api_style": "ai_connection_api_style",
    "model_name": "ai_connection_model_name",
    "base_url": "ai_connection_base_url",
    "api_key": "ai_connection_api_key",
}

AI_CONNECTION_TEST_FINGERPRINT_KEY = "ai_connection_test_fingerprint"
AI_CONNECTION_TESTED_AT_KEY = "ai_connection_tested_at"


@dataclass(frozen=True)
class AIModelConfig:
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


@transaction.atomic
def save_ai_connection_config(payload):
    """保存管理员维护的连接参数；API Key 仅接受写入并以密文保存。"""
    if payload["api_style"] not in {"responses", "chat_json"}:
        raise ValueError("API 风格必须是 responses 或 chat_json")
    if not isinstance(payload["model_name"], str) or not payload["model_name"].strip():
        raise ValueError("模型名称不能为空")
    normalized_base_url = validate_ai_base_url(payload["base_url"])
    api_key_value = payload.get("api_key", "")
    if api_key_value is not None and not isinstance(api_key_value, str):
        raise ValueError("API Key 格式不正确")
    api_key_value = (api_key_value or "").strip()
    from apps.core import models as m

    previous_base_url = _connection_value("base_url")
    base_url_unchanged = _base_urls_match(previous_base_url, normalized_base_url)
    for field in ["api_style", "model_name", "base_url"]:
        value = normalized_base_url if field == "base_url" else payload[field].strip()
        m.Config.objects.update_or_create(
            key=AI_CONNECTION_CONFIG_KEYS[field], defaults={"value": value}
        )
    # 项目尚未上线，不保留已废弃的服务商/Profile 配置。
    m.Config.objects.filter(key="ai_connection_profile").delete()
    if payload.get("clear_api_key"):
        m.Config.objects.filter(key=AI_CONNECTION_CONFIG_KEYS["api_key"]).delete()
    elif api_key_value:
        m.Config.objects.update_or_create(
            key=AI_CONNECTION_CONFIG_KEYS["api_key"],
            defaults={"value": encrypt_api_key(api_key_value)},
        )
    elif not base_url_unchanged:
        # 访问令牌只绑定原 Base URL，不得在地址变化后静默转发到新服务。
        m.Config.objects.filter(key=AI_CONNECTION_CONFIG_KEYS["api_key"]).delete()
    invalidate_ai_connection_test(disable_ai=True)


def _connection_fingerprint():
    """生成当前完整连接的不可逆指纹，不在任何接口中返回。"""
    config = get_ai_model_config()
    payload = {
        "api_style": config.api_style,
        "model_name": config.model_name,
        "base_url": config.base_url,
        "api_key_hash": hashlib.sha256(config.api_key.encode("utf-8")).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def invalidate_ai_connection_test(*, disable_ai=False):
    from apps.core import models as m

    m.Config.objects.filter(
        key__in=[AI_CONNECTION_TEST_FINGERPRINT_KEY, AI_CONNECTION_TESTED_AT_KEY]
    ).delete()
    if disable_ai:
        m.Config.objects.update_or_create(key="ai_enabled", defaults={"value": False})


def mark_ai_connection_tested():
    from apps.core import models as m

    fingerprint = _connection_fingerprint()
    tested_at = timezone.now().isoformat()
    m.Config.objects.update_or_create(
        key=AI_CONNECTION_TEST_FINGERPRINT_KEY,
        defaults={"value": fingerprint},
    )
    m.Config.objects.update_or_create(
        key=AI_CONNECTION_TESTED_AT_KEY,
        defaults={"value": tested_at},
    )
    return tested_at


def is_ai_connection_tested():
    from apps.core import models as m

    stored = m.Config.objects.filter(
        key=AI_CONNECTION_TEST_FINGERPRINT_KEY
    ).values_list("value", flat=True).first()
    if not stored:
        return False
    try:
        return stored == _connection_fingerprint()
    except (RuntimeError, ValueError):
        return False


def is_ai_switch_enabled():
    return bool(_config_value("ai_enabled", False))


def allocation_mode():
    if not is_ai_switch_enabled():
        return "rule"
    if not is_ai_connection_tested():
        raise ValueError("AI 分配已开启，但当前模型连接尚未测试成功")
    return "ai"


def get_ai_connection_status():
    stored_key = _connection_value("api_key")
    tested_at = _connection_value_by_key(AI_CONNECTION_TESTED_AT_KEY) or ""
    return {
        "api_style": _connection_value("api_style") or "chat_json",
        "model_name": _connection_value("model_name") or "",
        "base_url": _connection_value("base_url") or "",
        "api_key_configured": bool(stored_key),
        "api_key_source": "system_config" if stored_key else "not_configured",
        "test_passed": is_ai_connection_tested(),
        "tested_at": tested_at,
    }


def is_ai_enabled():
    """AI 仅在全局开关开启且当前连接测试通过时可提交新调用。"""
    try:
        return allocation_mode() == "ai"
    except (RuntimeError, ValueError):
        return False


def get_ai_model_config():
    api_style = _connection_value("api_style")
    model_name = _connection_value("model_name")
    base_url = _connection_value("base_url")
    if not all(isinstance(value, str) and value.strip() for value in [api_style, model_name, base_url]):
        raise ValueError("AI 模型连接尚未完成配置，请由管理员在系统设置中保存")
    if api_style not in ["responses", "chat_json"]:
        raise ValueError("AI 模型连接的 api_style 必须是 responses 或 chat_json")
    validate_ai_base_url(base_url)
    saved_api_key = _connection_value("api_key")
    return AIModelConfig(
        api_style=api_style,
        model_name=model_name,
        prompt_version="resume-screening-v1",
        decision_version="decision-v1",
        profile_version="profile-v1",
        parser_version="pypdf-v1",
        api_key=decrypt_api_key(saved_api_key) if saved_api_key else "",
        base_url=base_url,
    )


def validate_ai_base_url(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Base URL 不能为空")
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是完整的 http(s) 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL 不能包含账号、密码、查询参数或锚点")
    return value.strip().rstrip("/")


def _base_urls_match(left, right):
    try:
        return validate_ai_base_url(left) == validate_ai_base_url(right)
    except ValueError:
        return False


def get_ai_discovery_config(*, base_url, api_key=""):
    """返回模型发现所需连接参数；未提交新令牌时复用已保存令牌。"""
    normalized_base_url = validate_ai_base_url(base_url)
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("API Key 格式不正确")
    submitted_api_key = (api_key or "").strip()
    saved_api_key = _connection_value("api_key")
    saved_base_url = _connection_value("base_url")
    can_reuse_saved_key = _base_urls_match(saved_base_url, normalized_base_url)
    effective_api_key = submitted_api_key
    if not effective_api_key and saved_api_key and can_reuse_saved_key:
        effective_api_key = decrypt_api_key(saved_api_key)
    return normalized_base_url, effective_api_key


def _config_value(key, default):
    from apps.core import models as m

    config = m.Config.objects.filter(key=key).first()
    value = config.value if config else default
    if isinstance(value, dict):
        return value.get("value", default)
    return value


def _connection_value_by_key(key):
    from apps.core import models as m

    config = m.Config.objects.filter(key=key).first()
    if not config:
        return None
    value = config.value
    return value.get("value") if isinstance(value, dict) else value


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
