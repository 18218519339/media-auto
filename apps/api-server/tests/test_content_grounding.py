from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.llm_rewrite_adapter import LLMRewriteError, rewrite_wechat_article
from app.main import create_app
from app.link_reader import LinkReadError, LinkReader, LinkSnapshot
from app.wechat_rewrite_policy import (
    WechatArticleValidationError,
    build_local_wechat_fallback,
    clean_wechat_source_text,
    validate_wechat_article,
)


def _html(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html>
      <head>
        <title>{title}</title>
        <meta property="og:title" content="{title}" />
      </head>
      <body>
        <article>
          <h1>{title}</h1>
          <p>{body}</p>
        </article>
      </body>
    </html>
    """


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("MEDIA_AUTOMATION_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(
        "app.services.rewrite_wechat_article",
        lambda snapshot, rewrite_strength, style_reference_url: build_local_wechat_fallback(
            snapshot,
            rewrite_strength=rewrite_strength,
            style_reference_url=style_reference_url,
        ),
    )
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_link_reader_extracts_title_body_and_keywords_from_html() -> None:
    html = _html(
        "HBM3E 与 CoWoS 产能追踪",
        "HBM3E 订单继续增长，CoWoS 封装产能成为算力服务器交付节奏的关键约束。"
        "DRAM现货价格也出现连续三周上涨，渠道库存下降明显。",
    )

    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=html))
    snapshot = LinkReader(transport=transport).read("https://news.example.com/hbm3e-cowos")

    assert snapshot.title == "HBM3E 与 CoWoS 产能追踪"
    assert "HBM3E" in snapshot.body
    assert "CoWoS" in snapshot.body
    assert "DRAM现货价格" in snapshot.body
    assert {"HBM3E", "CoWoS", "DRAM现货价格"}.issubset(set(snapshot.keywords))
    assert snapshot.word_count >= 3


def test_link_reader_rejects_short_or_failed_pages() -> None:
    short_transport = httpx.MockTransport(lambda _: httpx.Response(200, text="<html><p>太短</p></html>"))
    with pytest.raises(LinkReadError, match="正文过短"):
        LinkReader(transport=short_transport, min_body_chars=20).read("https://news.example.com/short")

    not_found_transport = httpx.MockTransport(lambda _: httpx.Response(404, text="missing"))
    with pytest.raises(LinkReadError, match="404"):
        LinkReader(transport=not_found_transport).read("https://news.example.com/missing")


def test_link_reader_ignores_broken_environment_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _html(
        "公众号文章读取测试",
        "HBM3E 与 CoWoS 继续成为 AI 算力供应链里的关键变量，DRAM现货价格变化也影响内存模组报价节奏。",
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")

    try:
        snapshot = LinkReader().read(f"http://127.0.0.1:{server.server_port}/article")
    finally:
        server.shutdown()
        server.server_close()

    assert snapshot.title == "公众号文章读取测试"
    assert "HBM3E" in snapshot.body
    assert "CoWoS" in snapshot.body


def test_api_generate_uses_real_snapshot_content(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    snapshot = LinkSnapshot(
        url="https://news.example.com/hbm3e",
        title="HBM3E 供需变化早报",
        body=(
            "HBM3E 订单增速超预期，CoWoS 先进封装排产延长。"
            "DRAM现货价格本周上行，内存模组厂开始调整报价。"
        ),
        source_platform="news.example.com",
        published_at=None,
        keywords=["HBM3E", "CoWoS", "DRAM现货价格"],
    )
    monkeypatch.setattr("app.services.read_url_snapshot", lambda url: snapshot)

    source = client.post(
        "/api/sources",
        json={
            "url": "https://news.example.com/hbm3e",
            "target_platform": "wechat",
            "rewrite_strength": 7,
            "image_mode": "ai",
        },
    ).json()
    draft = client.post(f"/api/sources/{source['id']}/generate", json={"simulate": True}).json()["draft"]
    pipeline = client.get("/api/pipeline").json()["items"][0]

    assert pipeline["source"]["original_title"] == "HBM3E 供需变化早报"
    assert "HBM3E 订单增速超预期" in pipeline["source"]["original_body_snapshot"]
    assert "HBM3E" in draft["body_markdown"]
    assert "CoWoS" in draft["body_markdown"]
    assert "DRAM现货价格" in draft["body_markdown"]
    assert "这是一份由系统保存的素材正文快照" not in draft["body_markdown"]

def test_api_generate_persists_read_failure_for_pipeline(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    def fail_read(url: str) -> LinkSnapshot:
        raise LinkReadError("正文过短，无法生成草稿")

    monkeypatch.setattr("app.services.read_url_snapshot", fail_read)

    source = client.post(
        "/api/sources",
        json={"url": "https://news.example.com/short", "target_platform": "xhs"},
    ).json()
    response = client.post(f"/api/sources/{source['id']}/generate", json={"simulate": True})

    assert response.status_code == 422
    pipeline_item = client.get("/api/pipeline").json()["items"][0]
    assert pipeline_item["source"]["id"] == source["id"]
    assert pipeline_item["source"]["status"] == "failed"
    assert pipeline_item["draft"] is None
    assert pipeline_item["logs"][-1]["stage"] == "read_failed"
    assert pipeline_item["logs"][-1]["error_code"] == "READ_FAILED"


def test_different_source_links_generate_different_drafts(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    snapshots = {
        "https://news.example.com/hbm3e": LinkSnapshot(
            url="https://news.example.com/hbm3e",
            title="HBM3E 价格追踪",
            body="HBM3E 需求上升，CoWoS 产能紧张，AI 服务器交付节奏受到关注。",
            source_platform="news.example.com",
            published_at=None,
            keywords=["HBM3E", "CoWoS"],
        ),
        "https://news.example.com/edge-ai": LinkSnapshot(
            url="https://news.example.com/edge-ai",
            title="边缘 AI 芯片出货观察",
            body="边缘 AI 芯片在工业视觉场景出货增加，低功耗 NPU 模组成为新品重点。",
            source_platform="news.example.com",
            published_at=None,
            keywords=["边缘AI", "NPU"],
        ),
    }
    monkeypatch.setattr("app.services.read_url_snapshot", lambda url: snapshots[url])

    first = client.post(
        "/api/sources",
        json={"url": "https://news.example.com/hbm3e", "target_platform": "wechat"},
    ).json()
    second = client.post(
        "/api/sources",
        json={"url": "https://news.example.com/edge-ai", "target_platform": "wechat"},
    ).json()

    first_draft = client.post(f"/api/sources/{first['id']}/generate", json={"simulate": True}).json()["draft"]
    second_draft = client.post(f"/api/sources/{second['id']}/generate", json={"simulate": True}).json()["draft"]

    assert "HBM3E" in first_draft["body_markdown"]
    assert "边缘 AI" in second_draft["body_markdown"]
    assert first_draft["body_markdown"] != second_draft["body_markdown"]


def test_openclaw_payload_contains_source_snapshot(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    snapshot = LinkSnapshot(
        url="https://news.example.com/dram",
        title="DRAM现货价格周报",
        body="DRAM现货价格继续上行，DDR5 模组报价跟随调整，渠道库存下降。",
        source_platform="news.example.com",
        published_at=None,
        keywords=["DRAM现货价格", "DDR5"],
    )
    monkeypatch.setattr("app.services.read_url_snapshot", lambda url: snapshot)

    source = client.post(
        "/api/sources",
        json={"url": "https://news.example.com/dram", "target_platform": "wechat"},
    ).json()
    response = client.post(f"/api/sources/{source['id']}/generate", json={"simulate": False})
    assert response.status_code == 200

    task = client.get("/api/openclaw/tasks/next").json()
    assert task["payload"]["source_title"] == "DRAM现货价格周报"
    assert "DRAM现货价格继续上行" in task["payload"]["source_snapshot"]
    assert task["payload"]["source_keywords"] == ["DRAM现货价格", "DDR5"]


def test_openclaw_rejects_empty_or_unrelated_rewrite_result(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    snapshot = LinkSnapshot(
        url="https://news.example.com/cowos",
        title="CoWoS 产能新闻",
        body="CoWoS 产能排期延长，HBM3E 供应链紧张，AI 加速卡交付周期受到影响。",
        source_platform="news.example.com",
        published_at=None,
        keywords=["CoWoS", "HBM3E"],
    )
    monkeypatch.setattr("app.services.read_url_snapshot", lambda url: snapshot)

    source = client.post(
        "/api/sources",
        json={"url": "https://news.example.com/cowos", "target_platform": "wechat"},
    ).json()
    client.post(f"/api/sources/{source['id']}/generate", json={"simulate": False})
    task = client.get("/api/openclaw/tasks/next").json()

    empty = client.post(
        f"/api/openclaw/tasks/{task['id']}/result",
        json={"status": "succeeded", "result": {"title": "", "body_markdown": ""}},
    )
    assert empty.status_code == 400

    unrelated = client.post(
        f"/api/openclaw/tasks/{task['id']}/result",
        json={
            "status": "succeeded",
            "result": {
                "title": "旅游攻略",
                "summary": "这是一篇关于城市徒步和咖啡店探访的生活方式文章，介绍路线选择、拍照点位和周末出行建议。",
                "body_markdown": (
                    "这是一篇关于城市徒步和咖啡店探访的生活方式文章，介绍路线选择、拍照点位和周末出行建议。\n\n"
                    "第一段讨论街区散步体验，强调慢节奏生活和消费场景，适合把城市更新、街区商业和年轻人周末休闲放在一起观察。\n\n"
                    "第二段介绍店铺风格和饮品口味，描述空间设计、菜单结构、座位密度和拍照动线，和科技产业没有关系。\n\n"
                    "第三段总结周末安排，建议读者记录路线并分享给朋友，同时提醒提前查看天气、交通和店铺排队情况。\n\n"
                    "第四段补充预算和时间安排，建议半天完成两到三个点位，不要把行程排得太满，以免影响体验。\n\n"
                    "第五段强调这类内容更适合生活方式读者，重点是路线、审美、消费体验和城市氛围，"
                    "并不涉及芯片、封装、存储、服务器或企业基础设施采购等产业议题。"
                ),
                "tags": ["旅游"],
                "fact_check_notes": ["核查店铺营业时间"],
            },
        },
    )
    assert unrelated.status_code == 400
    assert "素材无关" in unrelated.json()["detail"]


def test_llm_rewrite_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "")
    import app.llm_rewrite_adapter as llm_adapter
    llm_adapter.KIMI_API_KEY = ""
    snapshot = LinkSnapshot(
        url="https://mp.weixin.qq.com/s/pro6000d",
        title="Pro 6000D 滞销观察",
        body="Pro 6000D 与 Blackwell、HBM、GDDR7、算力采购相关。",
        source_platform="wechat",
        published_at=None,
        keywords=["Pro 6000D", "Blackwell", "HBM", "GDDR7", "算力"],
    )

    with pytest.raises(LLMRewriteError, match="KIMI_API_KEY"):
        rewrite_wechat_article(snapshot, rewrite_strength=7, style_reference_url=None)


def test_wechat_source_cleaner_removes_wechat_page_noise() -> None:
    noisy = (
        "Pro 6000D 滞销成烫手山芋，Blackwell 架构产品需求遇冷。"
        "在小说阅读器读本章 去阅读 在小说阅读器中沉浸阅读 "
        "微信扫一扫 关注该公众号 继续滑动看下一个 轻触阅读原文 "
        "HBM 没有采用，GDDR7 成为妥协选择，算力采购逻辑出现变化。"
    )

    cleaned = clean_wechat_source_text(noisy)

    assert "Pro 6000D" in cleaned
    assert "Blackwell" in cleaned
    assert "GDDR7" in cleaned
    assert "在小说阅读器读本章" not in cleaned
    assert "微信扫一扫" not in cleaned
    assert "轻触阅读原文" not in cleaned


def test_wechat_article_quality_validation_rejects_template_and_noise() -> None:
    snapshot = LinkSnapshot(
        url="https://mp.weixin.qq.com/s/pro6000d",
        title="Pro 6000D 滞销观察",
        body=(
            "Pro 6000D 在 Blackwell 架构下需求遇冷，渠道库存压力上升。"
            "HBM 缺位和 GDDR7 妥协让产品定位尴尬，算力采购转向更看重推理性价比。"
        ),
        source_platform="wechat",
        published_at=None,
        keywords=["Pro 6000D", "Blackwell", "HBM", "GDDR7", "算力"],
    )
    bad_article = {
        "title": "Pro 6000D 滞销观察：行业解读与发布建议",
        "summary": "素材来源和关键要点整理。",
        "body_markdown": (
            "## 素材来源\n\n"
            "- 原文标题：Pro 6000D 滞销观察\n"
            "- 关键要点：Pro 6000D、Blackwell\n\n"
            "微信扫一扫 关注该公众号。"
        ),
        "tags": ["Pro 6000D"],
        "fact_check_notes": ["需要核查库存数据"],
    }

    with pytest.raises(WechatArticleValidationError):
        validate_wechat_article(bad_article, snapshot)


def test_wechat_article_quality_validation_accepts_publishable_industry_analysis() -> None:
    snapshot = LinkSnapshot(
        url="https://mp.weixin.qq.com/s/pro6000d",
        title="Pro 6000D 滞销观察",
        body=(
            "Pro 6000D 在 Blackwell 架构下需求遇冷，渠道库存压力上升。"
            "HBM 缺位和 GDDR7 妥协让产品定位尴尬，算力采购转向更看重推理性价比。"
        ),
        source_platform="wechat",
        published_at=None,
        keywords=["Pro 6000D", "Blackwell", "HBM", "GDDR7", "算力"],
    )
    good_article = {
        "title": "Pro 6000D遇冷，算力采购逻辑正在转向",
        "summary": "围绕 Pro 6000D 的需求变化，可以看到高端算力采购从单纯追逐英伟达生态，转向更看重训练、推理和成本结构的匹配。",
        "body_markdown": (
            "Pro 6000D 的市场反馈，正在给 AI 算力产业链释放一个清晰信号：合规特供产品不再天然等于紧缺资产。\n\n"
            "从素材信息看，Pro 6000D 依托 Blackwell 架构，却因为 HBM 缺位和 GDDR7 方案妥协，在定位上处在一个尴尬区间。"
            "它既难以承担最顶级训练集群的想象空间，也很难在推理侧与更重视成本的方案直接竞争。\n\n"
            "这件事真正值得关注的地方，不是单个型号卖得快慢，而是算力采购逻辑的变化。"
            "当企业开始区分训练、推理和具体业务负载，单一品牌溢价就会被重新评估，渠道库存也会更快暴露压力。\n\n"
            "后续需要继续观察三点：第一，Pro 6000D 库存消化是否会影响同架构其他产品的渠道定价；"
            "第二，国产算力在推理场景中的替代节奏是否继续加快；第三，客户是否会把采购重心从参数转向总拥有成本。\n\n"
            "以上内容基于公开素材整理改写，涉及价格、库存和采购判断，发布前仍需人工复核来源与时间线。"
        ),
        "tags": ["Pro 6000D", "Blackwell", "算力", "HBM", "GDDR7"],
        "fact_check_notes": ["核查库存、价格与采购口径"],
    }

    validated = validate_wechat_article(good_article, snapshot)

    assert validated.title == good_article["title"]
    assert "素材来源" not in validated.body_markdown
    assert "发布建议" not in validated.body_markdown
    assert "微信扫一扫" not in validated.body_markdown
    assert {"Pro 6000D", "Blackwell", "算力"}.issubset(set(validated.tags))
