from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


Platform = Literal["wechat", "xhs"]


class SourceCreate(BaseModel):
    url: HttpUrl
    style_reference_url: HttpUrl | None = None
    target_platform: Platform
    rewrite_strength: int = Field(default=6, ge=1, le=10)
    image_mode: Literal["none", "ai"] = "ai"


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    style_reference_url: str | None
    target_platform: str
    rewrite_strength: int
    image_mode: str
    source_platform: str | None
    original_title: str | None
    original_body_snapshot: str | None
    status: str
    created_at: datetime


class GenerateRequest(BaseModel):
    simulate: bool = True
    use_local_fallback: bool = False


class DraftUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    body_markdown: str | None = None
    body_html: str | None = None
    tags: list[str] | None = None


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usage: str
    prompt: str
    url: str


class DraftOut(BaseModel):
    id: int
    source_id: int
    target_platform: str
    status: str
    title: str
    summary: str
    body_markdown: str
    body_html: str
    tags: list[str]
    rewrite_params: dict[str, Any]
    wechat_draft_media_id: str | None
    images: list[ImageOut] = []


class GenerateResponse(BaseModel):
    draft: DraftOut | None
    openclaw_task_id: int | None = None


class WechatAccountCreate(BaseModel):
    name: str
    app_id: str
    app_secret: str
    ip_allowlist_status: str = "unknown"


class WechatAccountOut(BaseModel):
    id: int
    name: str
    app_id: str
    app_secret_masked: str
    ip_allowlist_status: str
    connection_status: str


class PublishJobCreate(BaseModel):
    draft_id: int
    scheduled_at: datetime
    execution_mode: Literal["openclaw"] = "openclaw"


class PublishJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    draft_id: int
    platform: str
    scheduled_at: datetime
    execution_mode: str
    status: str
    openclaw_task_id: int | None
    failure_reason: str | None


class OpenClawEventCreate(BaseModel):
    stage: str
    message: str
    attachment_url: str | None = None
    error_code: str | None = None
    status: str | None = None


class OpenClawResultCreate(BaseModel):
    status: Literal["succeeded", "failed"] = "succeeded"
    result: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None


class OpenClawTaskOut(BaseModel):
    id: int
    task_type: str
    status: str
    payload: dict[str, Any]
    attempts: int


class TaskLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    message: str
    attachment_url: str | None
    error_code: str | None
    created_at: datetime


class PipelineItemOut(BaseModel):
    source: SourceOut
    draft: DraftOut | None
    publish_jobs: list[PublishJobOut]
    logs: list[TaskLogOut]


class PipelineResponse(BaseModel):
    items: list[PipelineItemOut]


class SchedulerRunResponse(BaseModel):
    triggered_count: int
    task_ids: list[int]
