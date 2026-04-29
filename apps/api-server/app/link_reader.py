from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


class LinkReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class LinkSnapshot:
    url: str
    title: str
    body: str
    source_platform: str
    published_at: str | None
    keywords: list[str]

    @property
    def word_count(self) -> int:
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", self.body)
        ascii_words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+\-_.]*", self.body)
        return len(chinese_chars) + len(ascii_words)


KNOWN_KEYWORDS = [
    "DRAM现货价格",
    "HBM3E",
    "CoWoS",
    "DDR5",
    "NPU",
    "边缘 AI",
    "边缘AI",
    "先进封装",
    "AI服务器",
    "AI",
    "GPU",
    "半导体",
    "算力",
    "大模型",
    "内存",
    "存储",
]


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"([。！？；])\s+", r"\1", text)
    return text.strip()


def detect_source_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "mp.weixin.qq.com" in host or "weixin.qq.com" in host:
        return "wechat"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xhs"
    return host or "unknown"


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    found: list[str] = []
    compact_text = text.replace(" ", "")
    for keyword in KNOWN_KEYWORDS:
        if keyword in text or keyword.replace(" ", "") in compact_text:
            normalized = keyword.replace(" ", "") if keyword == "边缘 AI" else keyword
            if normalized not in found:
                found.append(normalized)

    for token in re.findall(r"\b[A-Z][A-Za-z0-9+\-]{1,}\b", text):
        if token not in found:
            found.append(token)

    return found[:limit]


class LinkReader:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20,
        min_body_chars: int = 60,
        trust_env: bool = False,
    ) -> None:
        self.transport = transport
        self.timeout = timeout
        self.min_body_chars = min_body_chars
        self.trust_env = trust_env

    def read(self, url: str) -> LinkSnapshot:
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=self.timeout,
                trust_env=self.trust_env,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                    )
                },
            ) as client:
                response = client.get(url)
        except httpx.TimeoutException as exc:
            raise LinkReadError("链接读取超时") from exc
        except httpx.HTTPError as exc:
            raise LinkReadError(f"链接读取失败：{exc}") from exc

        if response.status_code >= 400:
            raise LinkReadError(f"链接读取失败：HTTP {response.status_code}")

        return self._parse(url, response.text)

    def _parse(self, url: str, html: str) -> LinkSnapshot:
        soup = BeautifulSoup(html, "lxml")
        for node in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
            node.decompose()

        title = self._extract_title(soup)
        body = self._extract_body(soup)
        if len(body) < self.min_body_chars:
            raise LinkReadError(f"正文过短：仅提取到 {len(body)} 个字符")

        return LinkSnapshot(
            url=url,
            title=title,
            body=body,
            source_platform=detect_source_platform(url),
            published_at=self._extract_published_at(soup),
            keywords=extract_keywords(f"{title} {body}"),
        )

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        for selector, attr in [
            ('meta[property="og:title"]', "content"),
            ('meta[name="twitter:title"]', "content"),
        ]:
            node = soup.select_one(selector)
            if node and node.get(attr):
                return clean_text(str(node[attr]))
        if soup.find("h1"):
            return clean_text(soup.find("h1").get_text(" ", strip=True))
        if soup.title:
            return clean_text(soup.title.get_text(" ", strip=True))
        return "未命名素材"

    @staticmethod
    def _extract_body(soup: BeautifulSoup) -> str:
        candidates = []
        for selector in [
            "article",
            "main",
            "#js_content",
            ".rich_media_content",
            ".article",
            ".content",
            "body",
        ]:
            node = soup.select_one(selector)
            if node:
                text = clean_text(node.get_text(" ", strip=True))
                if text:
                    candidates.append(text)
        if not candidates:
            return ""
        return max(candidates, key=len)

    @staticmethod
    def _extract_published_at(soup: BeautifulSoup) -> str | None:
        for selector, attr in [
            ('meta[property="article:published_time"]', "content"),
            ('meta[name="publishdate"]', "content"),
            ('meta[name="pubdate"]', "content"),
        ]:
            node = soup.select_one(selector)
            if node and node.get(attr):
                return clean_text(str(node[attr]))
        return None
