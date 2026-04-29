from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.getenv("OPENCLAW_API_BASE", "http://127.0.0.1:8000")
POLL_INTERVAL = int(os.getenv("OPENCLAW_POLL_INTERVAL", "10"))
PUBLISH_TIMEOUT = int(os.getenv("OPENCLAW_PUBLISH_TIMEOUT", "120"))


def request(method: str, path: str, payload: dict | None = None) -> dict | None:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        print(f"[ERROR] {method} {path} failed: {exc.code} {body}", file=sys.stderr)
        return None


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def ensure_due_tasks() -> list[int]:
    result = request("POST", "/api/scheduler/run-due")
    if result:
        count = result.get("triggered_count", 0)
        task_ids = result.get("task_ids", [])
        if count > 0:
            log(f"Scheduler triggered {count} publish jobs: {task_ids}")
        return task_ids
    return []


def claim_task() -> dict | None:
    task = request("GET", "/api/openclaw/tasks/next?task_type=publish_wechat_draft")
    if task:
        log(f"Claimed task {task['id']} ({task['task_type']})")
    return task


def report_event(task_id: int, stage: str, message: str, **kwargs) -> None:
    payload = {"stage": stage, "message": message}
    for k, v in kwargs.items():
        if v is not None:
            payload[k] = v
    request("POST", f"/api/openclaw/tasks/{task_id}/events", payload)


def report_result(task_id: int, status: str, result: dict | None = None, failure_reason: str | None = None) -> None:
    payload: dict = {"status": status}
    if result:
        payload["result"] = result
    if failure_reason:
        payload["failure_reason"] = failure_reason
    request("POST", f"/api/openclaw/tasks/{task_id}/result", payload)


def main() -> None:
    log(f"WeChat OpenClaw worker started (API: {API_BASE}, poll interval: {POLL_INTERVAL}s)")

    while True:
        try:
            ensure_due_tasks()

            task = claim_task()
            if not task:
                time.sleep(POLL_INTERVAL)
                continue

            task_id = task["id"]
            payload = task.get("payload", {})
            media_id = payload.get("wechat_draft_media_id")

            if not media_id:
                failure = "Task missing wechat_draft_media_id"
                log(f"Task {task_id} failed: {failure}")
                report_event(task_id, "failed", failure, error_code="MISSING_MEDIA_ID")
                report_result(task_id, "failed", failure_reason=failure)
                time.sleep(POLL_INTERVAL)
                continue

            report_event(task_id, "publishing", f"开始发布公众号草稿，media_id：{media_id}")

            publish_result = wechat_publish(media_id)
            if publish_result["status"] == "succeeded":
                log(f"Task {task_id} succeeded: {publish_result}")
                report_result(
                    task_id,
                    "succeeded",
                    result={
                        "publish_id": publish_result.get("publish_id"),
                        "article_id": publish_result.get("article_id"),
                        "url": publish_result.get("url"),
                    },
                    attachment_url=publish_result.get("url"),
                )
            else:
                failure = publish_result.get("error", "Unknown publish error")
                log(f"Task {task_id} failed: {failure}")
                report_event(task_id, "failed", failure, error_code="PUBLISH_FAILED")
                report_result(task_id, "failed", failure_reason=failure)

        except Exception as exc:
            log(f"[ERROR] Worker exception: {exc}")
            time.sleep(POLL_INTERVAL)


def wechat_publish(media_id: str) -> dict:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app.security import decrypt_secret
    from app.wechat_client import WeChatAPIError as WeChatErr, WeChatClient
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import WechatAccount

    db = SessionLocal()
    try:
        account = db.execute(
            select(WechatAccount).where(WechatAccount.connection_status == "configured")
        ).scalar_one_or_none()
        if not account:
            return {"status": "failed", "error": "No configured WeChat account"}
        client = WeChatClient(account.app_id, decrypt_secret(account.encrypted_app_secret))
        result = client.publish_draft(media_id, timeout=PUBLISH_TIMEOUT)
        return {"status": "succeeded", **result}
    except WeChatErr as exc:
        return {"status": "failed", "error": f"WeChat API error {exc.errcode}: {exc.errmsg}"}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


if __name__ == "__main__":
    main()