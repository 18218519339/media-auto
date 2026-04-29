from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.link_reader import LinkSnapshot
from app.wechat_rewrite_policy import (
    WechatArticle,
    WechatArticleValidationError,
    build_wechat_messages,
    validate_wechat_article,
)


LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-cp-U0PpeSIHuauE45_PHxlHTmkaEW3UwGP1Cr6MMPStJbJPr8wbv2uK7frOExrcaeNEKkAN_kWqfoccW8QfBSR2QBQT7QQ0TPGrTELD4Qi9yxccY-fHwttWD_E")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.minimax.chat/v1")


class LLMRewriteError(RuntimeError):
    pass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def is_llm_configured() -> bool:
    return bool(LLM_API_KEY)


def _llm_request(endpoint: str, payload: dict) -> dict:
    url = f"{LLM_API_BASE}{endpoint}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            err = json.loads(body)
            raise LLMRewriteError(f"{err.get('error', {}).get('message', body)}")
        except json.JSONDecodeError:
            raise LLMRewriteError(body) from exc
    except urllib.error.URLError as exc:
        raise LLMRewriteError(f"网络请求失败：{exc.reason}") from exc


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
    if not LLM_API_KEY:
        raise LLMRewriteError("未配置 LLM_API_KEY，无法调用模型改写")

    temperature = _env_float("LLM_TEMPERATURE", 0.35)

    payload = {
        "model": "MiniMax-Text-01",
        "messages": build_wechat_messages(
            snapshot,
            rewrite_strength=rewrite_strength,
            style_reference_url=style_reference_url,
        ),
        "temperature": temperature,
    }
    try:
        completion = _llm_request("/text/chatcompletion_v2", payload)
        content = completion["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LLMRewriteError(f"模型接口返回格式错误：{exc}") from exc

    result = _extract_json_object(str(content))
    try:
        return validate_wechat_article(result, snapshot)
    except WechatArticleValidationError as exc:
        raise LLMRewriteError(str(exc)) from exc
