from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceItem(TimestampMixin, Base):
    __tablename__ = "source_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    style_reference_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    target_platform: Mapped[str] = mapped_column(String(24), nullable=False)
    rewrite_strength: Mapped[int] = mapped_column(Integer, default=6)
    image_mode: Mapped[str] = mapped_column(String(24), default="ai")
    source_platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_body_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="created", nullable=False)

    drafts: Mapped[list["Draft"]] = relationship(back_populates="source", cascade="all, delete-orphan")
    logs: Mapped[list["TaskLog"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Draft(TimestampMixin, Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source_items.id"), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="awaiting_review", nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    rewrite_params_json: Mapped[str] = mapped_column(Text, default="{}")
    wechat_draft_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    source: Mapped[SourceItem] = relationship(back_populates="drafts")
    images: Mapped[list["ImageAsset"]] = relationship(back_populates="draft", cascade="all, delete-orphan")
    publish_jobs: Mapped[list["PublishJob"]] = relationship(back_populates="draft", cascade="all, delete-orphan")
    logs: Mapped[list["TaskLog"]] = relationship(back_populates="draft", cascade="all, delete-orphan")


class ImageAsset(TimestampMixin, Base):
    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    usage: Mapped[str] = mapped_column(String(48), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)

    draft: Mapped[Draft] = relationship(back_populates="images")


class WechatAccount(TimestampMixin, Base):
    __tablename__ = "wechat_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    app_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    encrypted_app_secret: Mapped[str] = mapped_column(Text, nullable=False)
    ip_allowlist_status: Mapped[str] = mapped_column(String(48), default="unknown")
    connection_status: Mapped[str] = mapped_column(String(48), default="unchecked")


class PublishJob(TimestampMixin, Base):
    __tablename__ = "publish_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(24), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(32), default="openclaw")
    status: Mapped[str] = mapped_column(String(40), default="scheduled", nullable=False)
    openclaw_task_id: Mapped[int | None] = mapped_column(ForeignKey("openclaw_tasks.id"), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    draft: Mapped[Draft] = relationship(back_populates="publish_jobs")
    logs: Mapped[list["TaskLog"]] = relationship(back_populates="publish_job", cascade="all, delete-orphan")


class OpenClawTask(TimestampMixin, Base):
    __tablename__ = "openclaw_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_items.id"), nullable=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True)
    publish_job_id: Mapped[int | None] = mapped_column(ForeignKey("publish_jobs.id"), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    logs: Mapped[list["TaskLog"]] = relationship(back_populates="openclaw_task", cascade="all, delete-orphan")


class TaskLog(TimestampMixin, Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_items.id"), nullable=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True)
    publish_job_id: Mapped[int | None] = mapped_column(ForeignKey("publish_jobs.id"), nullable=True)
    openclaw_task_id: Mapped[int | None] = mapped_column(ForeignKey("openclaw_tasks.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    source: Mapped[SourceItem | None] = relationship(back_populates="logs")
    draft: Mapped[Draft | None] = relationship(back_populates="logs")
    publish_job: Mapped[PublishJob | None] = relationship(back_populates="logs")
    openclaw_task: Mapped[OpenClawTask | None] = relationship(back_populates="logs")
