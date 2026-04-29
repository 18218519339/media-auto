from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.content_generator import ContentValidationError, generate_grounded_draft, normalize_rewrite_result
from app.llm_rewrite_adapter import LLMRewriteError, rewrite_wechat_article
from app.link_reader import LinkReadError, LinkReader, LinkSnapshot, extract_keywords
from app.models import Draft, ImageAsset, OpenClawTask, PublishJob, SourceItem, TaskLog, WechatAccount
from app.schemas import DraftOut, ImageOut, OpenClawTaskOut, PipelineItemOut, PublishJobOut, SourceOut, TaskLogOut
from app.security import encrypt_secret, mask_secret
from app.state_machine import InvalidTransitionError, ensure_transition
from app.wechat_rewrite_policy import WechatArticle, WechatArticleValidationError, validate_wechat_article


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def log_event(
    db: Session,
    *,
    stage: str,
    message: str,
    source_id: int | None = None,
    draft_id: int | None = None,
    publish_job_id: int | None = None,
    openclaw_task_id: int | None = None,
    attachment_url: str | None = None,
    error_code: str | None = None,
) -> TaskLog:
    item = TaskLog(
        stage=stage,
        message=message,
        source_id=source_id,
        draft_id=draft_id,
        publish_job_id=publish_job_id,
        openclaw_task_id=openclaw_task_id,
        attachment_url=attachment_url,
        error_code=error_code,
    )
    db.add(item)
    return item


def transition_status(entity: Any, target: str) -> None:
    try:
        ensure_transition(entity.status, target)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entity.status = target


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "weixin.qq.com" in host or "mp.weixin.qq.com" in host:
        return "wechat"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xhs"
    return host or "unknown"


def read_url_snapshot(url: str) -> LinkSnapshot:
    return LinkReader().read(url)


def snapshot_from_source(source: SourceItem) -> LinkSnapshot:
    body = source.original_body_snapshot or ""
    title = source.original_title or "未命名素材"
    return LinkSnapshot(
        url=source.url,
        title=title,
        body=body,
        source_platform=source.source_platform or detect_platform(source.url),
        published_at=None,
        keywords=extract_keywords(f"{title} {body}"),
    )


def create_source(db: Session, payload: Any) -> SourceItem:
    source = SourceItem(
        url=str(payload.url),
        style_reference_url=str(payload.style_reference_url) if payload.style_reference_url else None,
        target_platform=payload.target_platform,
        rewrite_strength=payload.rewrite_strength,
        image_mode=payload.image_mode,
        source_platform=detect_platform(str(payload.url)),
    )
    db.add(source)
    db.flush()
    log_event(db, stage="created", message="素材链接已提交", source_id=source.id)
    db.commit()
    db.refresh(source)
    return source


def read_source_snapshot(db: Session, source: SourceItem) -> None:
    transition_status(source, "reading")
    try:
        snapshot = read_url_snapshot(source.url)
    except LinkReadError as exc:
        transition_status(source, "failed")
        log_event(
            db,
            stage="read_failed",
            message=f"素材链接读取失败：{exc}",
            source_id=source.id,
            error_code="READ_FAILED",
        )
        db.commit()
        raise HTTPException(status_code=422, detail=f"素材链接读取失败：{exc}") from exc

    source.source_platform = snapshot.source_platform
    source.original_title = snapshot.title
    source.original_body_snapshot = snapshot.body
    log_event(
        db,
        stage="reading",
        message=f"已读取素材正文并保存快照：{snapshot.word_count} 字，关键词：{'、'.join(snapshot.keywords) or '无'}",
        source_id=source.id,
    )


def create_openclaw_task(
    db: Session,
    *,
    task_type: str,
    payload: dict[str, Any],
    source_id: int | None = None,
    draft_id: int | None = None,
    publish_job_id: int | None = None,
) -> OpenClawTask:
    task = OpenClawTask(
        task_type=task_type,
        payload_json=_json_dumps(payload),
        source_id=source_id,
        draft_id=draft_id,
        publish_job_id=publish_job_id,
    )
    db.add(task)
    db.flush()
    log_event(
        db,
        stage="openclaw_task_created",
        message=f"已创建 OpenClaw 任务：{task_type}",
        source_id=source_id,
        draft_id=draft_id,
        publish_job_id=publish_job_id,
        openclaw_task_id=task.id,
    )
    return task


def _wechat_article_to_content(article: WechatArticle, *, engine: str) -> dict[str, Any]:
    return {
        "title": article.title,
        "summary": article.summary,
        "body_markdown": article.body_markdown,
        "tags": article.tags,
        "rewrite_metadata": {
            "generation_engine": engine,
            "quality_checks": article.quality_checks,
            "fact_check_notes": article.fact_check_notes,
        },
    }


def build_draft_content(
    source: SourceItem,
    result: dict[str, Any] | None = None,
    *,
    use_local_fallback: bool = False,
) -> dict[str, Any]:
    snapshot = snapshot_from_source(source)
    if result:
        if source.target_platform == "wechat":
            try:
                article = validate_wechat_article(result, snapshot)
            except WechatArticleValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return _wechat_article_to_content(article, engine="external_rewrite")
        try:
            content = normalize_rewrite_result(result, snapshot)
        except ContentValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "title": content.title,
            "summary": content.summary,
            "body_markdown": content.body_markdown,
            "tags": content.tags,
        }

    if source.target_platform == "wechat" and not use_local_fallback:
        try:
            article = rewrite_wechat_article(
                snapshot,
                rewrite_strength=source.rewrite_strength,
                style_reference_url=source.style_reference_url,
            )
        except LLMRewriteError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"模型改写失败：{exc}。请配置 LLM_API_KEY，或使用本地兜底稿。",
            ) from exc
        return _wechat_article_to_content(article, engine="llm")

    content = generate_grounded_draft(
        snapshot,
        target_platform=source.target_platform,
        rewrite_strength=source.rewrite_strength,
        style_reference_url=source.style_reference_url,
    )
    return {
        "title": content.title,
        "summary": content.summary,
        "body_markdown": content.body_markdown,
        "tags": content.tags,
        "rewrite_metadata": {
            "generation_engine": "local_fallback" if source.target_platform == "wechat" else "local_simulation",
        },
    }


def markdown_to_html(markdown: str) -> str:
    html = escape(markdown)
    html = html.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f"<p>{html}</p>"


def serialize_draft(draft: Draft) -> DraftOut:
    return DraftOut(
        id=draft.id,
        source_id=draft.source_id,
        target_platform=draft.target_platform,
        status=draft.status,
        title=draft.title,
        summary=draft.summary,
        body_markdown=draft.body_markdown,
        body_html=draft.body_html,
        tags=_json_loads(draft.tags_json, []),
        rewrite_params=_json_loads(draft.rewrite_params_json, {}),
        wechat_draft_media_id=draft.wechat_draft_media_id,
        images=[ImageOut.model_validate(image) for image in draft.images],
    )


def create_image_assets(db: Session, draft: Draft, source: SourceItem) -> None:
    if source.image_mode == "none":
        log_event(db, stage="image_skipped", message="已选择不自动生成配图", source_id=source.id, draft_id=draft.id)
        return

    transition_status(source, "image_generating")
    count = 3 if draft.target_platform == "xhs" else 1
    usage = "xhs_note_image" if draft.target_platform == "xhs" else "wechat_cover"
    for index in range(count):
        prompt = f"{draft.title}，行业科技媒体风格，清晰、克制、适合{draft.target_platform}发布"
        image = ImageAsset(
            draft_id=draft.id,
            usage=usage,
            prompt=prompt,
            url=f"/static/generated/{draft.target_platform}-{draft.id}-{index + 1}.png",
        )
        db.add(image)
    log_event(db, stage="image_generating", message=f"已生成 {count} 个图片占位资产", source_id=source.id, draft_id=draft.id)


def create_draft_from_result(
    db: Session,
    source: SourceItem,
    result: dict[str, Any] | None = None,
    *,
    use_local_fallback: bool = False,
) -> Draft:
    content = build_draft_content(source, result, use_local_fallback=use_local_fallback)
    rewrite_metadata = content.get("rewrite_metadata", {})
    draft = Draft(
        source_id=source.id,
        target_platform=source.target_platform,
        title=content["title"],
        summary=content["summary"],
        body_markdown=content["body_markdown"],
        body_html=markdown_to_html(content["body_markdown"]),
        tags_json=_json_dumps(content["tags"]),
        rewrite_params_json=_json_dumps(
            {
                "rewrite_strength": source.rewrite_strength,
                "style_reference_url": source.style_reference_url,
                "positioning": "基于素材的原创行业解读",
                **rewrite_metadata,
            }
        ),
    )
    db.add(draft)
    db.flush()
    create_image_assets(db, draft, source)
    source.status = "awaiting_review"
    log_event(db, stage="awaiting_review", message="草稿已生成，等待人工审核", source_id=source.id, draft_id=draft.id)
    return draft


def generate_source(
    db: Session,
    source_id: int,
    simulate: bool = True,
    use_local_fallback: bool = False,
) -> tuple[Draft | None, OpenClawTask]:
    source = db.get(SourceItem, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="素材不存在")
    if source.status == "created":
        read_source_snapshot(db, source)
    transition_status(source, "rewriting")
    snapshot = snapshot_from_source(source)
    task = create_openclaw_task(
        db,
        task_type="rewrite_external_site",
        source_id=source.id,
        payload={
            "source_url": source.url,
            "style_reference_url": source.style_reference_url,
            "source_title": snapshot.title,
            "source_snapshot": snapshot.body,
            "source_keywords": snapshot.keywords,
            "target_platform": source.target_platform,
            "rewrite_strength": source.rewrite_strength,
            "image_mode": source.image_mode,
            "rewrite_engine": (
                "local_fallback"
                if use_local_fallback
                else "llm"
                if source.target_platform == "wechat" and simulate
                else "openclaw"
                if not simulate
                else "local_simulation"
            ),
        },
    )
    draft = None
    if simulate:
        try:
            draft = create_draft_from_result(db, source, use_local_fallback=use_local_fallback)
        except HTTPException as exc:
            transition_status(source, "failed")
            task.status = "failed"
            task.failure_reason = str(exc.detail)
            task.result_json = _json_dumps({"error": exc.detail})
            log_event(
                db,
                stage="rewrite_failed",
                message=str(exc.detail),
                source_id=source.id,
                openclaw_task_id=task.id,
                error_code="REWRITE_FAILED",
            )
            db.commit()
            raise
        task.status = "succeeded"
        task.result_json = _json_dumps(
            {
                "mode": "local_fallback" if use_local_fallback else "llm_rewrite_adapter",
            }
        )
        log_event(db, stage="rewriting", message="公众号草稿已完成质量校验", source_id=source.id, openclaw_task_id=task.id)
    db.commit()
    if draft:
        db.refresh(draft)
    db.refresh(task)
    return draft, task


def update_draft(db: Session, draft_id: int, payload: Any) -> Draft:
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    data = payload.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    for key, value in data.items():
        setattr(draft, key, value)
    if tags is not None:
        draft.tags_json = _json_dumps(tags)
    if "body_markdown" in data and "body_html" not in data:
        draft.body_html = markdown_to_html(draft.body_markdown)
    log_event(db, stage="draft_updated", message="草稿已人工编辑", source_id=draft.source_id, draft_id=draft.id)
    db.commit()
    db.refresh(draft)
    return draft


def approve_draft(db: Session, draft_id: int) -> Draft:
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    transition_status(draft, "approved")
    if draft.source:
        draft.source.status = "approved"
    log_event(db, stage="approved", message="草稿已审核通过", source_id=draft.source_id, draft_id=draft.id)
    db.commit()
    db.refresh(draft)
    return draft


def upsert_wechat_account(db: Session, payload: Any) -> tuple[WechatAccount, str]:
    name = payload.name.strip() if hasattr(payload, 'name') else payload.name
    app_id = payload.app_id.strip() if hasattr(payload, 'app_id') else payload.app_id
    app_secret = payload.app_secret.strip() if hasattr(payload, 'app_secret') else payload.app_secret

    existing = db.execute(select(WechatAccount).where(WechatAccount.app_id == app_id)).scalar_one_or_none()
    encrypted = encrypt_secret(app_secret)
    if existing:
        existing.name = name
        existing.encrypted_app_secret = encrypted
        existing.ip_allowlist_status = payload.ip_allowlist_status
        existing.connection_status = "configured"
        account = existing
    else:
        account = WechatAccount(
            name=name,
            app_id=app_id,
            encrypted_app_secret=encrypted,
            ip_allowlist_status=payload.ip_allowlist_status,
            connection_status="configured",
        )
        db.add(account)
    db.flush()
    log_event(db, stage="wechat_account_configured", message=f"公众号配置已保存：{name}")
    db.commit()
    db.refresh(account)
    return account, mask_secret(app_secret)


def get_default_wechat_account(db: Session) -> WechatAccount:
    account = db.execute(
        select(WechatAccount)
        .where(WechatAccount.connection_status == "configured")
        .order_by(WechatAccount.created_at.desc())
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=400, detail="请先配置公众号 AppID/AppSecret")
    return account


def save_wechat_draft(db: Session, draft_id: int) -> Draft:
    from app.wechat_client import WeChatAPIError as WeChatErr, WeChatClient
    from app.security import decrypt_secret

    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if draft.target_platform != "wechat":
        raise HTTPException(status_code=400, detail="只有公众号草稿支持保存到公众号草稿箱")
    account = get_default_wechat_account(db)
    if draft.status != "approved":
        raise HTTPException(status_code=400, detail="公众号草稿必须先审核通过")
    transition_status(draft, "wechat_draft_saving")
    try:
        client = WeChatClient(account.app_id, decrypt_secret(account.encrypted_app_secret))
        thumb_media_id = client.upload_cover_image()
        media_id = client.add_draft(
            title=draft.title,
            author=None,
            digest=draft.summary[:54],
            content=draft.body_html,
            thumb_media_id=thumb_media_id,
        )
    except WeChatErr as exc:
        transition_status(draft, "failed")
        log_event(
            db,
            stage="wechat_draft_failed",
            message=f"保存公众号草稿失败：{exc.errmsg}",
            source_id=draft.source_id,
            draft_id=draft.id,
            error_code=f"WECHAT_{exc.errcode}",
        )
        db.commit()
        raise HTTPException(status_code=502, detail=f"微信接口调用失败：{exc.errmsg}") from exc
    draft.wechat_draft_media_id = media_id
    transition_status(draft, "wechat_draft_saved")
    if draft.source:
        draft.source.status = "wechat_draft_saved"
    log_event(
        db,
        stage="wechat_draft_saved",
        message=f"公众号草稿已保存到草稿箱，media_id：{media_id}",
        source_id=draft.source_id,
        draft_id=draft.id,
    )
    db.commit()
    db.refresh(draft)
    return draft


def schedule_publish_job(db: Session, payload: Any) -> PublishJob:
    draft = db.get(Draft, payload.draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    allowed = {"approved", "wechat_draft_saved", "scheduled"}
    if draft.status not in allowed:
        raise HTTPException(status_code=400, detail="草稿需要先通过审核后才能排期")
    if draft.target_platform == "wechat" and draft.status != "wechat_draft_saved":
        raise HTTPException(status_code=400, detail="公众号需要先保存草稿后才能排期")

    job = PublishJob(
        draft_id=draft.id,
        platform=draft.target_platform,
        scheduled_at=payload.scheduled_at,
        execution_mode=payload.execution_mode,
        status="scheduled",
    )
    db.add(job)
    db.flush()
    if draft.status != "scheduled":
        transition_status(draft, "scheduled")
    if draft.source:
        draft.source.status = "scheduled"
    log_event(db, stage="scheduled", message="发布计划已创建", source_id=draft.source_id, draft_id=draft.id, publish_job_id=job.id)
    db.commit()
    db.refresh(job)
    return job


def run_due_publish_jobs(db: Session, now: datetime | None = None) -> tuple[int, list[int]]:
    current_time = now or datetime.now(UTC)
    due_jobs = db.execute(
        select(PublishJob)
        .where(PublishJob.status == "scheduled")
        .where(PublishJob.openclaw_task_id.is_(None))
        .where(PublishJob.scheduled_at <= current_time)
        .order_by(PublishJob.scheduled_at)
    ).scalars()

    task_ids: list[int] = []
    for job in due_jobs:
        draft = job.draft
        task_type = "publish_xhs_note" if draft.target_platform == "xhs" else "publish_wechat_draft"
        task = create_openclaw_task(
            db,
            task_type=task_type,
            draft_id=draft.id,
            publish_job_id=job.id,
            payload={
                "draft_id": draft.id,
                "platform": draft.target_platform,
                "scheduled_at": job.scheduled_at.isoformat(),
                "wechat_draft_media_id": draft.wechat_draft_media_id,
            },
        )
        job.openclaw_task_id = task.id
        job.status = "publishing"
        if draft.status == "scheduled":
            transition_status(draft, "publishing")
        if draft.source:
            draft.source.status = "publishing"
        log_event(
            db,
            stage="publishing",
            message="调度器已到点创建 OpenClaw 发布任务",
            source_id=draft.source_id,
            draft_id=draft.id,
            publish_job_id=job.id,
            openclaw_task_id=task.id,
        )
        task_ids.append(task.id)
    db.commit()
    return len(task_ids), task_ids


def get_next_openclaw_task(db: Session, task_type: str | None = None) -> OpenClawTask | None:
    query = select(OpenClawTask).where(OpenClawTask.status == "pending")
    if task_type:
        query = query.where(OpenClawTask.task_type == task_type)
    task = db.execute(query.order_by(OpenClawTask.created_at).limit(1)).scalar_one_or_none()
    if not task:
        return None
    task.status = "running"
    task.attempts += 1
    log_event(db, stage="openclaw_task_claimed", message=f"OpenClaw worker 已领取任务（{task.task_type}）", openclaw_task_id=task.id)
    db.commit()
    db.refresh(task)
    return task


def record_openclaw_event(db: Session, task_id: int, payload: Any) -> OpenClawTask:
    task = db.get(OpenClawTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="OpenClaw 任务不存在")
    if payload.status:
        task.status = payload.status
    log_event(
        db,
        stage=payload.stage,
        message=payload.message,
        source_id=task.source_id,
        draft_id=task.draft_id,
        publish_job_id=task.publish_job_id,
        openclaw_task_id=task.id,
        attachment_url=payload.attachment_url,
        error_code=payload.error_code,
    )
    db.commit()
    db.refresh(task)
    return task


def complete_openclaw_task(db: Session, task_id: int, payload: Any) -> OpenClawTask:
    task = db.get(OpenClawTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="OpenClaw 任务不存在")
    if task.status == "succeeded" and payload.status == "succeeded":
        return task

    if payload.status == "failed":
        task.status = "failed"
        task.result_json = _json_dumps(payload.result)
        task.failure_reason = payload.failure_reason
        if task.publish_job_id:
            job = db.get(PublishJob, task.publish_job_id)
            if job:
                job.status = "failed"
                job.failure_reason = payload.failure_reason
        log_event(db, stage="failed", message=payload.failure_reason or "OpenClaw 任务失败", openclaw_task_id=task.id)
    elif task.task_type == "rewrite_external_site" and task.source_id:
        source = db.get(SourceItem, task.source_id)
        if source and not source.drafts:
            try:
                create_draft_from_result(db, source, payload.result)
            except HTTPException as exc:
                task.status = "failed"
                task.result_json = _json_dumps(payload.result)
                task.failure_reason = str(exc.detail)
                if source:
                    source.status = "failed"
                log_event(
                    db,
                    stage="rewrite_result_rejected",
                    message=f"OpenClaw 改写结果被拒绝：{exc.detail}",
                    source_id=task.source_id,
                    openclaw_task_id=task.id,
                    error_code="REWRITE_RESULT_INVALID",
                )
                db.commit()
                raise
        task.status = "succeeded"
        task.result_json = _json_dumps(payload.result)
    elif task.publish_job_id:
        task.status = payload.status
        task.result_json = _json_dumps(payload.result)
        job = db.get(PublishJob, task.publish_job_id)
        if job:
            job.status = "succeeded"
            draft = job.draft
            transition_status(draft, "publishing")
            transition_status(draft, "succeeded")
            if draft.source:
                draft.source.status = "succeeded"
            log_event(
                db,
                stage="succeeded",
                message="OpenClaw 已回传发布成功",
                source_id=draft.source_id,
                draft_id=draft.id,
                publish_job_id=job.id,
                openclaw_task_id=task.id,
            )
    db.commit()
    db.refresh(task)
    return task


def serialize_openclaw_task(task: OpenClawTask) -> OpenClawTaskOut:
    return OpenClawTaskOut(
        id=task.id,
        task_type=task.task_type,
        status=task.status,
        payload=_json_loads(task.payload_json, {}),
        attempts=task.attempts,
    )


def serialize_source(source: SourceItem) -> SourceOut:
    return SourceOut.model_validate(source)


def serialize_publish_job(job: PublishJob) -> PublishJobOut:
    return PublishJobOut.model_validate(job)


def get_pipeline(db: Session) -> list[PipelineItemOut]:
    sources = db.execute(
        select(SourceItem)
        .options(
            selectinload(SourceItem.drafts).selectinload(Draft.images),
            selectinload(SourceItem.drafts).selectinload(Draft.publish_jobs),
            selectinload(SourceItem.logs),
        )
        .order_by(SourceItem.created_at.desc())
    ).scalars()

    items: list[PipelineItemOut] = []
    for source in sources:
        draft = source.drafts[-1] if source.drafts else None
        logs = list(source.logs)
        if draft:
            logs.extend(draft.logs)
            for job in draft.publish_jobs:
                logs.extend(job.logs)
        logs = sorted({log.id: log for log in logs}.values(), key=lambda item: item.created_at)
        items.append(
            PipelineItemOut(
                source=serialize_source(source),
                draft=serialize_draft(draft) if draft else None,
                publish_jobs=[serialize_publish_job(job) for job in draft.publish_jobs] if draft else [],
                logs=[TaskLogOut.model_validate(log) for log in logs],
            )
        )
    return items
