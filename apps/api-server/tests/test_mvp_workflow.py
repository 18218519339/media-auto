from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.link_reader import LinkSnapshot
from app.main import create_app
from app.models import WechatAccount
from app.wechat_rewrite_policy import build_local_wechat_fallback


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
    monkeypatch.setattr(
        "app.services.read_url_snapshot",
        lambda url: LinkSnapshot(
            url=url,
            title="AI半导体早报素材",
            body=(
                "HBM3E 需求继续增长，CoWoS 先进封装排期延长。"
                "DRAM现货价格上涨，算力服务器供应链需要关注内存和封装产能。"
            ),
            source_platform="example.com",
            published_at=None,
            keywords=["HBM3E", "CoWoS", "DRAM现货价格"],
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
    app.state.testing_session = TestingSessionLocal
    return TestClient(app)


def test_wechat_source_can_generate_save_draft_schedule_and_log(client: TestClient) -> None:
    source_response = client.post(
        "/api/sources",
        json={
            "url": "https://example.com/ai-semiconductor-daily",
            "style_reference_url": "https://mp.weixin.qq.com/s/reference",
            "target_platform": "wechat",
            "rewrite_strength": 7,
            "image_mode": "ai",
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]

    generate_response = client.post(f"/api/sources/{source_id}/generate", json={"simulate": True})
    assert generate_response.status_code == 200
    draft = generate_response.json()["draft"]
    assert draft["target_platform"] == "wechat"
    assert draft["status"] == "awaiting_review"
    assert "行业解读" in draft["body_markdown"]

    draft_id = draft["id"]
    approve_response = client.post(f"/api/drafts/{draft_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    account_response = client.post(
        "/api/wechat/accounts",
        json={
            "name": "AI半导体早报",
            "app_id": "wx1234567890",
            "app_secret": "super-secret",
            "ip_allowlist_status": "configured",
        },
    )
    assert account_response.status_code == 201
    assert account_response.json()["app_secret_masked"] == "su********et"

    save_response = client.post(f"/api/drafts/{draft_id}/save-wechat-draft")
    assert save_response.status_code == 200
    assert save_response.json()["status"] == "wechat_draft_saved"
    assert save_response.json()["wechat_draft_media_id"].startswith("wechat-draft-")

    publish_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    schedule_response = client.post(
        "/api/publish-jobs",
        json={
            "draft_id": draft_id,
            "scheduled_at": publish_at,
            "execution_mode": "openclaw",
        },
    )
    assert schedule_response.status_code == 201
    assert schedule_response.json()["status"] == "scheduled"

    pipeline_response = client.get("/api/pipeline")
    assert pipeline_response.status_code == 200
    pipeline = pipeline_response.json()
    assert pipeline["items"][0]["source"]["target_platform"] == "wechat"
    assert any(log["stage"] == "wechat_draft_saved" for log in pipeline["items"][0]["logs"])


def test_unapproved_draft_cannot_be_scheduled(client: TestClient) -> None:
    source = client.post(
        "/api/sources",
        json={
            "url": "https://example.com/xhs-memory-market",
            "target_platform": "xhs",
            "rewrite_strength": 5,
            "image_mode": "ai",
        },
    ).json()
    draft = client.post(f"/api/sources/{source['id']}/generate", json={"simulate": True}).json()["draft"]

    schedule_response = client.post(
        "/api/publish-jobs",
        json={
            "draft_id": draft["id"],
            "scheduled_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "execution_mode": "openclaw",
        },
    )

    assert schedule_response.status_code == 400
    assert "审核" in schedule_response.json()["detail"]


def test_wechat_secret_is_encrypted_at_rest_and_masked_in_api(client: TestClient) -> None:
    response = client.post(
        "/api/wechat/accounts",
        json={
            "name": "安全测试公众号",
            "app_id": "wx-encrypted",
            "app_secret": "plain-text-secret",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["app_secret_masked"] == "pl********et"
    assert "plain-text-secret" not in str(payload)

    session_factory = client.app.state.testing_session
    with session_factory() as session:
        account = session.execute(select(WechatAccount)).scalar_one()
        assert account.encrypted_app_secret != "plain-text-secret"
        assert "plain-text-secret" not in account.encrypted_app_secret


def test_scheduler_only_enqueues_due_publish_jobs(client: TestClient) -> None:
    source = client.post(
        "/api/sources",
        json={
            "url": "https://example.com/xhs-ai-infra",
            "target_platform": "xhs",
            "rewrite_strength": 8,
            "image_mode": "ai",
        },
    ).json()
    draft = client.post(f"/api/sources/{source['id']}/generate", json={"simulate": True}).json()["draft"]
    client.post(f"/api/drafts/{draft['id']}/approve")

    future_schedule = client.post(
        "/api/publish-jobs",
        json={
            "draft_id": draft["id"],
            "scheduled_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "execution_mode": "openclaw",
        },
    ).json()
    assert future_schedule["openclaw_task_id"] is None

    no_due = client.post("/api/scheduler/run-due")
    assert no_due.status_code == 200
    assert no_due.json()["triggered_count"] == 0
    assert client.get("/api/openclaw/tasks/next").json() is None

    due_schedule = client.post(
        "/api/publish-jobs",
        json={
            "draft_id": draft["id"],
            "scheduled_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            "execution_mode": "openclaw",
        },
    ).json()
    assert due_schedule["openclaw_task_id"] is None

    due = client.post("/api/scheduler/run-due")
    assert due.status_code == 200
    assert due.json()["triggered_count"] == 1
    task = client.get("/api/openclaw/tasks/next").json()
    assert task["task_type"] == "publish_xhs_note"
    assert task["payload"]["draft_id"] == draft["id"]


def test_openclaw_rewrite_result_can_create_draft_without_simulation(client: TestClient) -> None:
    source = client.post(
        "/api/sources",
        json={
            "url": "https://example.com/semiconductor-source",
            "style_reference_url": "https://mp.weixin.qq.com/s/style",
            "target_platform": "wechat",
            "rewrite_strength": 9,
            "image_mode": "ai",
        },
    ).json()

    generate_response = client.post(f"/api/sources/{source['id']}/generate", json={"simulate": False})
    assert generate_response.status_code == 200
    assert generate_response.json()["draft"] is None

    task = client.get("/api/openclaw/tasks/next").json()
    assert task["task_type"] == "rewrite_external_site"
    result = client.post(
        f"/api/openclaw/tasks/{task['id']}/result",
        json={
            "status": "succeeded",
            "result": {
                "title": "HBM3E升温，算力供应链进入再平衡",
                "summary": "HBM3E 需求增长、CoWoS 排期延长与 DRAM现货价格上涨同时出现，说明 AI 算力供应链正在从单点抢货转向封装、内存和交付节奏的综合博弈。",
                "body_markdown": (
                    "HBM3E 需求继续增长，CoWoS 先进封装排期延长，这两个信号放在一起看，意味着 AI 算力供应链的约束正在从单一芯片扩散到更多关键环节。\n\n"
                    "素材中同时提到 DRAM现货价格上涨，说明内存和封装不再只是配套变量，而是会直接影响服务器交付节奏、整机报价和客户采购窗口。\n\n"
                    "这件事真正重要的地方，在于算力基础设施已经进入系统性竞争阶段。企业不只是在比较 GPU，也在比较 HBM3E、CoWoS、DRAM 和整机交付的协同能力。\n\n"
                    "对产业链来说，上游产能紧张会推高议价能力，但也会放大排期风险。下游客户如果继续加速部署 AI 服务器，就必须更早锁定关键器件和封装资源。\n\n"
                    "后续需要继续观察三点：CoWoS 排期是否继续拉长，DRAM现货价格是否传导到模组报价，以及 HBM3E 供给能否跟上大模型训练和推理集群需求。\n\n"
                    "以上内容基于公开素材改写，涉及价格、产能和交付判断，发布前仍需人工复核来源与时间线。"
                ),
                "tags": ["AI", "HBM3E", "CoWoS", "DRAM现货价格"],
                "fact_check_notes": ["核查 HBM3E 需求、CoWoS 排期和 DRAM 价格时间线。"],
            },
        },
    )
    assert result.status_code == 200

    pipeline = client.get("/api/pipeline").json()
    draft = pipeline["items"][0]["draft"]
    assert draft["title"] == "HBM3E升温，算力供应链进入再平衡"
    assert draft["status"] == "awaiting_review"
