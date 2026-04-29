from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.link_reader import LinkSnapshot, extract_keywords
from app.wechat_rewrite_policy import build_local_wechat_fallback


class ContentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DraftContent:
    title: str
    summary: str
    body_markdown: str
    tags: list[str]


def _split_sentences(text: str, limit: int = 4) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？；.!?])", text) if piece.strip()]
    if not pieces:
        pieces = [text.strip()]
    return pieces[:limit]


def _summary(text: str, max_chars: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if len(cleaned) <= max_chars else f"{cleaned[:max_chars]}..."


def generate_grounded_draft(
    snapshot: LinkSnapshot,
    *,
    target_platform: str,
    rewrite_strength: int,
    style_reference_url: str | None = None,
) -> DraftContent:
    keywords = snapshot.keywords or extract_keywords(f"{snapshot.title} {snapshot.body}")
    sentences = _split_sentences(snapshot.body)
    tags = keywords[:5] or ["行业观察"]

    if target_platform == "xhs":
        title = f"{snapshot.title}｜3个值得关注的变化"
        bullet_lines = "\n".join(f"{index + 1}. {sentence}" for index, sentence in enumerate(sentences[:3]))
        body = (
            f"今天这条素材的核心是：{snapshot.title}\n\n"
            f"{bullet_lines}\n\n"
            f"我的判断：这些变化会影响后续行业节奏，尤其是{('、'.join(keywords[:3]) if keywords else '相关产业链')}。\n\n"
            f"来源链接：{snapshot.url}\n"
            f"{' '.join(f'#{tag}' for tag in tags[:5])}"
        )
        summary = _summary(f"围绕 {snapshot.title} 的小红书图文草稿。")
    else:
        article = build_local_wechat_fallback(
            snapshot,
            rewrite_strength=rewrite_strength,
            style_reference_url=style_reference_url,
        )
        return DraftContent(
            title=article.title,
            summary=article.summary,
            body_markdown=article.body_markdown,
            tags=article.tags,
        )

    return DraftContent(title=title, summary=summary, body_markdown=body, tags=tags)


def normalize_rewrite_result(result: dict[str, Any], snapshot: LinkSnapshot) -> DraftContent:
    title = str(result.get("title") or "").strip()
    body = str(result.get("body_markdown") or result.get("body") or "").strip()
    summary = str(result.get("summary") or _summary(body)).strip()
    tags = result.get("tags") or snapshot.keywords[:5]
    if not isinstance(tags, list):
        tags = [str(tags)]

    if not title:
        raise ContentValidationError("改写结果缺少标题")
    if not body:
        raise ContentValidationError("改写结果缺少正文")

    keywords = snapshot.keywords or extract_keywords(f"{snapshot.title} {snapshot.body}")
    haystack = f"{title} {summary} {body}".replace(" ", "")
    related = any(keyword.replace(" ", "") in haystack for keyword in keywords)
    if keywords and not related:
        raise ContentValidationError("改写结果与素材无关")

    return DraftContent(title=title, summary=summary, body_markdown=body, tags=[str(tag) for tag in tags])
