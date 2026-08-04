"""使用当前已测试通过的 AI 连接补全院校所在省份。"""

from __future__ import annotations

import logging
import time

from pydantic import ValidationError

from apps.pipeline import ai_config
from apps.pipeline.regions import NORTH_PROVINCES, SOUTH_PROVINCES

from . import concurrency, prompt_harness
from .schemas import SchoolProvinceOutput
from .service import (
    AIServiceError,
    _get_openai_client,
    _model_failure_kind,
    _release_model_slot,
    _safe_model_error,
)


logger = logging.getLogger(__name__)
MAX_SCHOOLS_PER_REQUEST = 50
SUPPORTED_PROVINCES = tuple(sorted(NORTH_PROVINCES | SOUTH_PROVINCES))


def _canonical_province(value):
    text = str(value or "").strip()
    for province in sorted(SUPPORTED_PROVINCES, key=len, reverse=True):
        if province in text:
            return province
    return ""


def _prompt(
    school_names,
    *,
    prompt_version=None,
    prompt_modules=None,
):
    if prompt_modules is None:
        _resolved_version, prompt_modules = prompt_harness.get_prompt_modules(
            prompt_version
        )
    return prompt_harness.build_school_prompt(prompt_modules, school_names)


def call_school_province_model(
    school_names,
    *,
    prompt_version=None,
    prompt_modules=None,
):
    """通过正式结构化调用路径返回模型原始 Pydantic 结果。"""
    names = list(dict.fromkeys(str(name or "").strip() for name in school_names))
    names = [name for name in names if name]
    if not names:
        return SchoolProvinceOutput(schools=[])
    if len(names) > MAX_SCHOOLS_PER_REQUEST:
        raise ValueError(f"单次最多补全 {MAX_SCHOOLS_PER_REQUEST} 所院校")

    model_config = ai_config.get_ai_model_config(prompt_version=prompt_version)
    runtime_config = ai_config.get_ai_runtime_config()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIServiceError("ai_not_configured", "服务端未安装 OpenAI SDK") from exc

    try:
        client = _get_openai_client(OpenAI, model_config, runtime_config)
    except Exception as exc:
        code, message = _safe_model_error(exc)
        logger.warning(
            "School province AI client initialization failed code=%s error_type=%s",
            code,
            type(exc).__name__,
        )
        raise AIServiceError(code, message) from exc

    system, user = _prompt(
        names,
        prompt_version=prompt_version,
        prompt_modules=prompt_modules,
    )
    system_with_protocol = prompt_harness.append_structured_output_protocol(
        system, SchoolProvinceOutput
    )
    attempts = max(1, runtime_config.retry_count + 1)
    output = None
    for index in range(attempts):
        slot = concurrency.acquire_slot(model_config, runtime_config)
        try:
            if model_config.api_style == "chat_json":
                response = client.chat.completions.create(
                    model=model_config.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": system_with_protocol,
                        },
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    stream=False,
                )
                content = response.choices[0].message.content
                if not content:
                    _release_model_slot(slot, "success")
                    raise AIServiceError("ai_invalid_output", "模型未返回 JSON 内容")
                output = SchoolProvinceOutput.model_validate_json(content)
            else:
                response = client.responses.parse(
                    model=model_config.model_name,
                    input=[
                        {"role": "system", "content": system_with_protocol},
                        {"role": "user", "content": user},
                    ],
                    text_format=SchoolProvinceOutput,
                    store=False,
                )
                output = response.output_parsed
                if output is None:
                    _release_model_slot(slot, "success")
                    raise AIServiceError(
                        "ai_invalid_output", "模型未返回可解析的结构化结果"
                    )
            _release_model_slot(slot, "success")
            break
        except AIServiceError:
            if not slot.released:
                _release_model_slot(slot, "neutral")
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            _release_model_slot(slot, "success")
            raise AIServiceError(
                "ai_invalid_output", "AI 返回的院校省份不符合结构化要求"
            ) from exc
        except Exception as exc:
            code, message = _safe_model_error(exc)
            failure_kind, retryable, retry_after = _model_failure_kind(exc)
            _release_model_slot(slot, failure_kind, retry_after=retry_after)
            logger.warning(
                "School province AI call failed attempt=%s/%s code=%s error_type=%s",
                index + 1,
                attempts,
                code,
                type(exc).__name__,
            )
            if not retryable or index + 1 >= attempts:
                raise AIServiceError(code, message) from exc
            delay = concurrency.retry_delay(
                runtime_config,
                index,
                retry_after=retry_after,
            )
            if delay:
                time.sleep(delay)

    return output or SchoolProvinceOutput(schools=[])


def infer_school_provinces(
    school_names,
    *,
    prompt_version=None,
    prompt_modules=None,
):
    """返回 ``{院校名称: 标准省份简称}``，无把握或越界输出不会进入结果。"""
    names = list(dict.fromkeys(str(name or "").strip() for name in school_names))
    names = [name for name in names if name]
    output = call_school_province_model(
        names,
        prompt_version=prompt_version,
        prompt_modules=prompt_modules,
    )
    requested_names = set(names)
    result = {}
    for item in output.schools:
        name = item.name.strip()
        province = _canonical_province(item.province)
        if name in requested_names and province:
            result[name] = province
    return result
