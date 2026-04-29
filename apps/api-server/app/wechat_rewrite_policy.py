from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.link_reader import LinkSnapshot, clean_text, extract_keywords


class WechatArticleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class WechatArticle:
    title: str
    summary: str
    body_markdown: str
    tags: list[str]
    fact_check_notes: list[str]
    quality_checks: dict[str, Any]


WECHAT_NOISE_PHRASES = [
    "在小说阅读器读本章",
    "去阅读",
    "在小说阅读器中沉浸阅读",
    "微信扫一扫",
    "关注该公众号",
    "继续滑动看下一个",
    "轻触阅读原文",
    "向上滑动看下一个",
    "预览时标签不可点",
    "使用完整服务",
    "使用小程序",
    "轻点两下取消赞",
    "轻点两下取消在看",
    "取消 允许",
    "知道了",
    "小程序",
    "留言",
    "收藏",
    "听过",
]

INTERNAL_MARKERS = [
    "素材来源",
    "发布建议",
    "关键要点",
    "OpenClaw",
    "source_snapshot",
    "source_keywords",
    "fake_rewrite_adapter",
    "原文标题：",
    "来源链接：",
]


def clean_wechat_source_text(text: str) -> str:
    cleaned = text
    for phrase in WECHAT_NOISE_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"视频\s+小程序\s+赞.*?(分享|收藏|听过)", " ", cleaned)
    cleaned = re.sub(r"(取消\s+允许\s*){2,}", " ", cleaned)
    cleaned = re.sub(r"[，、：]\s*([，、：]\s*){2,}", "，", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return clean_text(cleaned)


def article_system_prompt() -> str:
    return (
        "你是资深 AI、半导体、算力产业公众号主笔。"
        "请把给定素材改写成可进入人工审核的公众号行业深度解读初稿。"
        "必须基于素材，不编造价格、公司采购、政策、库存、时间线等事实。"
        "输出只能是 JSON，不要输出 Markdown 代码块。"
    )


def article_user_prompt(
    snapshot: LinkSnapshot,
    *,
    rewrite_strength: int,
    style_reference_url: str | None,
) -> str:
    keywords = snapshot.keywords or extract_keywords(f"{snapshot.title} {snapshot.body}")
    cleaned_body = clean_wechat_source_text(snapshot.body)
    reference = style_reference_url or "无"
    keyword_line = "、".join(keywords) or "无"
    return f"""
请生成公众号文章 JSON，字段必须包含：
- title：18-32 字左右，不照抄原题，不标题党
- summary：80-120 字，概括事件、判断和行业影响
- body_markdown：900-1400 字，结构为导语、核心事实、为什么重要、产业影响、后续观察、风险提示/来源说明
- tags：3-6 个标签
- fact_check_notes：发布前需要人工核查的事实列表

硬性规则：
- 正文不能出现“素材来源”“发布建议”“关键要点”“OpenClaw”等内部词
- 正文不能出现公众号页面噪声，如“微信扫一扫”“轻触阅读原文”“在小说阅读器读本章”
- 必须覆盖素材关键词：{keyword_line}
- 涉及价格、库存、采购、政策、型号参数时只能使用素材中已有信息
- 风格：行业深度解读，克制、清晰、有观点，但不夸张

改写强度：{rewrite_strength}/10
样式参考链接：{reference}
素材标题：{snapshot.title}
素材链接：{snapshot.url}
素材正文：
{cleaned_body[:6000]}
""".strip()


def build_wechat_messages(
    snapshot: LinkSnapshot,
    *,
    rewrite_strength: int,
    style_reference_url: str | None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": article_system_prompt()},
        {
            "role": "user",
            "content": article_user_prompt(
                snapshot,
                rewrite_strength=rewrite_strength,
                style_reference_url=style_reference_url,
            ),
        },
    ]


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _paragraph_count(body: str) -> int:
    return len([piece for piece in re.split(r"\n\s*\n", body.strip()) if piece.strip()])


def _covered_keywords(text: str, keywords: list[str]) -> list[str]:
    compact_text = _compact(text)
    covered: list[str] = []
    for keyword in keywords:
        compact_keyword = _compact(keyword)
        if keyword in text or compact_keyword in compact_text:
            covered.append(keyword)
    return covered


def validate_wechat_article(result: dict[str, Any], snapshot: LinkSnapshot) -> WechatArticle:
    title = str(result.get("title") or "").strip()
    summary = str(result.get("summary") or "").strip()
    body = str(result.get("body_markdown") or result.get("body") or "").strip()
    tags = _as_string_list(result.get("tags"))
    fact_check_notes = _as_string_list(result.get("fact_check_notes"))

    if not title:
        raise WechatArticleValidationError("模型改写结果缺少标题")
    if not summary:
        raise WechatArticleValidationError("模型改写结果缺少摘要")
    if not body:
        raise WechatArticleValidationError("模型改写结果缺少正文")
    if _compact(title) == _compact(snapshot.title):
        raise WechatArticleValidationError("公众号标题不能直接照抄原文标题")
    if "行业解读与发布建议" in title:
        raise WechatArticleValidationError("公众号标题仍保留模板痕迹")

    haystack = f"{title}\n{summary}\n{body}"
    banned_terms = [term for term in [*WECHAT_NOISE_PHRASES, *INTERNAL_MARKERS] if term in haystack]
    if banned_terms:
        raise WechatArticleValidationError(f"公众号草稿包含不可发布词：{'、'.join(banned_terms[:5])}")

    if len(summary) < 40 or len(summary) > 180:
        raise WechatArticleValidationError("公众号摘要长度应控制在 40-180 字之间")

    body_chars = len(_compact(body))
    if body_chars < 260:
        raise WechatArticleValidationError("公众号正文过短，尚不足以作为深度解读初稿")
    paragraphs = _paragraph_count(body)
    if paragraphs < 4:
        raise WechatArticleValidationError("公众号正文段落过少，缺少完整分析结构")

    keywords = snapshot.keywords or extract_keywords(f"{snapshot.title} {snapshot.body}")
    covered = _covered_keywords(haystack, keywords)
    required = min(3, len(keywords))
    if required and len(covered) < required:
        missing = [keyword for keyword in keywords if keyword not in covered]
        raise WechatArticleValidationError(f"公众号草稿与素材无关，关键词覆盖不足，缺少：{'、'.join(missing[:5])}")

    if not tags:
        tags = covered[:5] or keywords[:5] or ["行业解读"]
    if not fact_check_notes:
        fact_check_notes = ["发布前复核公司名称、价格、库存、采购与时间线等关键事实。"]

    quality_checks = {
        "keyword_coverage": covered,
        "paragraph_count": paragraphs,
        "body_chars": body_chars,
        "noise_clean": True,
        "source_retained": snapshot.url,
        "fact_check_notes": fact_check_notes,
    }
    return WechatArticle(
        title=title,
        summary=summary,
        body_markdown=body,
        tags=tags[:6],
        fact_check_notes=fact_check_notes,
        quality_checks=quality_checks,
    )


def build_local_wechat_fallback(
    snapshot: LinkSnapshot,
    *,
    rewrite_strength: int,
    style_reference_url: str | None,
) -> WechatArticle:
    keywords = snapshot.keywords or extract_keywords(f"{snapshot.title} {snapshot.body}")
    cleaned_body = clean_wechat_source_text(snapshot.body)
    sentences = [piece.strip() for piece in re.split(r"(?<=[。！？；.!?])", cleaned_body) if piece.strip()]
    if not sentences:
        sentences = [cleaned_body]

    topic = keywords[0] if keywords else snapshot.title[:12]
    title = f"{topic}背后，算力产业链正在重新定价"
    if _compact(title) == _compact(snapshot.title):
        title = f"{topic}变化，正在牵动产业链判断"

    keyword_line = "、".join(keywords[:5]) or "素材中的核心信号"
    lead = sentences[0]
    fact = " ".join(sentences[1:3]) if len(sentences) > 1 else lead
    body = (
        f"{lead} 这条素材真正值得关注的，不只是单个事件本身，而是它折射出的算力产业链定价逻辑变化。\n\n"
        f"从核心事实看，{fact} 这些信息共同指向一个判断：当市场从单纯追逐供给稀缺，转向评估训练、推理、成本和交付节奏时，"
        f"{keyword_line} 都会被放到更现实的商业框架里重新衡量。\n\n"
        f"为什么这件事重要？AI 基础设施投入已经从早期的抢资源阶段，进入更重视效率和确定性的阶段。"
        f"对于采购方来说，参数和品牌仍然重要，但能否匹配具体业务负载、能否控制总拥有成本、能否稳定交付，正在变成更关键的决策变量。\n\n"
        f"放到产业链里看，上游芯片、先进封装、内存和整机渠道都会受到这种变化影响。"
        f"如果需求判断出现偏差，库存压力会先在渠道端暴露；如果供需继续偏紧，价格和排期又会重新影响下游部署节奏。\n\n"
        f"后续可以继续观察三点：第一，相关产品的渠道价格和库存是否继续变化；第二，客户是否把更多预算转向推理性价比；"
        f"第三，国产算力、存储和封装环节能否借此获得更多验证机会。\n\n"
        f"以上为基于公开素材的行业解读，涉及价格、采购、库存和政策判断，发布前仍需人工复核来源、时间线与关键数据。"
    )
    summary = (
        f"围绕 {snapshot.title}，这篇文章从 {keyword_line} 切入，分析 AI 算力采购从稀缺驱动转向效率、成本与交付确定性的变化。"
    )
    result = {
        "title": title,
        "summary": summary,
        "body_markdown": body,
        "tags": keywords[:5] or ["AI", "算力", "半导体"],
        "fact_check_notes": ["本地兜底稿需重点复核价格、库存、采购和政策表述。"],
    }
    article = validate_wechat_article(result, snapshot)
    return WechatArticle(
        title=article.title,
        summary=article.summary,
        body_markdown=f"{article.body_markdown}\n\n> 本文为本地兜底稿，建议接入模型后重新生成并人工审核。",
        tags=article.tags,
        fact_check_notes=article.fact_check_notes,
        quality_checks={**article.quality_checks, "engine": "local_fallback"},
    )
