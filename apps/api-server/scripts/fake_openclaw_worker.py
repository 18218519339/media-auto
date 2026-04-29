from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


API_BASE = "http://127.0.0.1:8000"


def request(method: str, path: str, payload: dict | None = None) -> dict | None:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def complete_task(task: dict) -> None:
    task_id = task["id"]
    task_type = task["task_type"]
    request(
        "POST",
        f"/api/openclaw/tasks/{task_id}/events",
        {"stage": "fake_worker_started", "message": f"fake worker started {task_type}"},
    )
    if task_type == "rewrite_external_site":
        request(
            "POST",
            f"/api/openclaw/tasks/{task_id}/result",
            {
                "status": "succeeded",
                "result": {
                    "title": "OpenClaw 回传的行业解读草稿",
                    "summary": "由 fake worker 模拟外部改写网站生成。",
                    "body_markdown": "## 行业解读\n\nfake worker 已完成改写回传，可进入人工审核。",
                    "tags": ["AI", "半导体", "OpenClaw"],
                },
            },
        )
    elif task_type in {"publish_wechat_draft", "publish_xhs_note"}:
        request(
            "POST",
            f"/api/openclaw/tasks/{task_id}/result",
            {"status": "succeeded", "result": {"published_url": "https://example.com/fake-published"}},
        )


def main() -> None:
    print("fake OpenClaw worker started")
    while True:
        task = request("GET", "/api/openclaw/tasks/next")
        if task:
            complete_task(task)
            print(f"completed task {task['id']} {task['task_type']}")
        time.sleep(3)


if __name__ == "__main__":
    main()
