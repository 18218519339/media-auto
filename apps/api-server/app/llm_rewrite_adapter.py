from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from app.link_reader import LinkSnapshot
from app.wechat_rewrite_policy import (
    WechatArticle,
    WechatArticleValidationError,
    build_wechat_messages,
    validate_wechat_article,
)


class LLMRewriteError(RuntimeError):
    pass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def is_llm_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY"))


def _completion_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/chat/completions"):
        return stripped
    return f"{stripped}/chat/completions"


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise LLMRewriteError("模型没有返回 JSON 对象")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMRewriteError("模型返回的 JSON 无法解析") from exc
    if not isinstance(payload, dict):
        raise LLMRewriteError("模型返回内容不是 JSON 对象")
    return payload


def rewrite_wechat_article(
    snapshot: LinkSnapshot,
    *,
    rewrite_strength: int,
    style_reference_url: str | None,
) -> WechatArticle:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise LLMRewriteError("未配置 LLM_API_KEY，无法调用模型改写")

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    timeout = _env_float("LLM_TIMEOUT_SECONDS", 45)
    temperature = _env_float("LLM_TEMPERATURE", 0.35)

    payload = {
        "model": model,
        "messages": build_wechat_messages(
            snapshot,
            rewrite_strength=rewrite_strength,
            style_reference_url=style_reference_url,
        ),
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(
                _completion_url(base_url),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise LLMRewriteError("模型改写请求超时") from exc
    except httpx.HTTPError as exc:
        raise LLMRewriteError(f"模型改写请求失败：{exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:300]
        raise LLMRewriteError(f"模型接口返回 HTTP {response.status_code}：{detail}")

    try:
        completion = response.json()
        content = completion["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LLMRewriteError("模型接口返回格式不符合 OpenAI-compatible chat/completions") from exc

    result = _extract_json_object(str(content))
    try:
        return validate_wechat_article(result, snapshot)
    except WechatArticleValidationError as exc:
        raise LLMRewriteError(str(exc)) from exc
