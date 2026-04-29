from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


KIMI_API_KEY = os.getenv("KIMI_API_KEY", "sk-EQFL1bPqYdm12sk0IiOEJAYRCkXheqNRUEu4ekKkuwoJlyC7")
KIMI_API_BASE = os.getenv("KIMI_API_BASE", "https://api.moonshot.cn/v1")


class ImageGenError(Exception):
    def __init__(self, message: str, code: int | None = None):
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass
class GeneratedImage:
    url: str
    b64_json: str | None = None


def _kimi_request(endpoint: str, payload: dict) -> dict:
    url = f"{KIMI_API_BASE}{endpoint}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KIMI_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            err = json.loads(body)
            raise ImageGenError(f"{err.get('error', {}).get('message', body)}", err.get('code'))
        except json.JSONDecodeError:
            raise ImageGenError(body) from exc
    except urllib.error.URLError as exc:
        raise ImageGenError(f"Network error: {exc.reason}") from exc


def generate_image(prompt: str, size: str = "1024x1024", quality: str = "standard") -> GeneratedImage:
    """Generate an image using Kimi/Moonshot image generation API."""
    payload = {
        "model": "moonshot-v1-image",
        "prompt": prompt,
        "image_size": size,
        "quality": quality,
        "n": 1,
    }
    result = _kimi_request("/images/generations", payload)

    data = result.get("data", [])
    if not data:
        raise ImageGenError("No image data returned")

    item = data[0]
    return GeneratedImage(
        url=item.get("url", ""),
        b64_json=item.get("b64_json"),
    )


def generate_wechat_cover(title: str, summary: str) -> GeneratedImage:
    """Generate a WeChat article cover image."""
    prompt = (
        f"为微信公众号文章生成封面图。标题：{title}。摘要：{summary}。 "
        f"风格要求：科技行业媒体风格，简洁大气，高端克制，颜色偏深蓝或墨绿色调，文字清晰可读。 "
        f"图片比例16:9，适合公众号封面展示。"
    )
    return generate_image(prompt, size="1024x1024", quality="standard")


def download_image_bytes(url: str) -> bytes:
    """Download image from URL and return bytes."""
    if url.startswith("data:"):
        # base64 inline data
        b64 = url.split(",", 1)[1]
        return base64.b64decode(b64)

    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()
