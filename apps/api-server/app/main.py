from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.schemas import (
    DraftOut,
    DraftUpdate,
    GenerateRequest,
    GenerateResponse,
    OpenClawEventCreate,
    OpenClawResultCreate,
    OpenClawTaskOut,
    PipelineResponse,
    PublishJobCreate,
    PublishJobOut,
    SchedulerRunResponse,
    SourceCreate,
    SourceOut,
    WechatAccountCreate,
    WechatAccountOut,
)
from app.services import (
    approve_draft,
    complete_openclaw_task,
    create_source,
    generate_source,
    get_next_openclaw_task,
    get_pipeline,
    record_openclaw_event,
    run_due_publish_jobs,
    save_wechat_draft,
    schedule_publish_job,
    serialize_draft,
    serialize_openclaw_task,
    serialize_source,
    upsert_wechat_account,
    update_draft,
)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        yield

    app = FastAPI(title="Media Automation MVP", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/sources", response_model=SourceOut, status_code=201)
    def create_source_endpoint(payload: SourceCreate, db: Session = Depends(get_db)) -> SourceOut:
        return serialize_source(create_source(db, payload))

    @app.post("/api/sources/{source_id}/generate", response_model=GenerateResponse)
    def generate_source_endpoint(
        source_id: int, payload: GenerateRequest | None = None, db: Session = Depends(get_db)
    ) -> GenerateResponse:
        request = payload or GenerateRequest()
        draft, task = generate_source(
            db,
            source_id,
            simulate=request.simulate,
            use_local_fallback=request.use_local_fallback,
        )
        return GenerateResponse(draft=serialize_draft(draft) if draft else None, openclaw_task_id=task.id)

    @app.patch("/api/drafts/{draft_id}", response_model=DraftOut)
    def update_draft_endpoint(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)) -> DraftOut:
        return serialize_draft(update_draft(db, draft_id, payload))

    @app.post("/api/drafts/{draft_id}/approve", response_model=DraftOut)
    def approve_draft_endpoint(draft_id: int, db: Session = Depends(get_db)) -> DraftOut:
        return serialize_draft(approve_draft(db, draft_id))

    @app.post("/api/wechat/accounts", response_model=WechatAccountOut, status_code=201)
    def upsert_wechat_account_endpoint(
        payload: WechatAccountCreate, db: Session = Depends(get_db)
    ) -> WechatAccountOut:
        account, masked = upsert_wechat_account(db, payload)
        return WechatAccountOut(
            id=account.id,
            name=account.name,
            app_id=account.app_id,
            app_secret_masked=masked,
            ip_allowlist_status=account.ip_allowlist_status,
            connection_status=account.connection_status,
        )

    @app.post("/api/drafts/{draft_id}/save-wechat-draft", response_model=DraftOut)
    def save_wechat_draft_endpoint(draft_id: int, db: Session = Depends(get_db)) -> DraftOut:
        return serialize_draft(save_wechat_draft(db, draft_id))

    @app.post("/api/publish-jobs", response_model=PublishJobOut, status_code=201)
    def schedule_publish_job_endpoint(payload: PublishJobCreate, db: Session = Depends(get_db)) -> PublishJobOut:
        return PublishJobOut.model_validate(schedule_publish_job(db, payload))

    @app.get("/api/pipeline", response_model=PipelineResponse)
    def pipeline_endpoint(db: Session = Depends(get_db)) -> PipelineResponse:
        return PipelineResponse(items=get_pipeline(db))

    @app.post("/api/scheduler/run-due", response_model=SchedulerRunResponse)
    def scheduler_run_due_endpoint(db: Session = Depends(get_db)) -> SchedulerRunResponse:
        count, task_ids = run_due_publish_jobs(db)
        return SchedulerRunResponse(triggered_count=count, task_ids=task_ids)

    @app.get("/api/openclaw/tasks/next", response_model=OpenClawTaskOut | None)
    def openclaw_next_task_endpoint(db: Session = Depends(get_db)) -> OpenClawTaskOut | None:
        task = get_next_openclaw_task(db)
        return serialize_openclaw_task(task) if task else None

    @app.post("/api/openclaw/tasks/{task_id}/events", response_model=OpenClawTaskOut)
    def openclaw_event_endpoint(
        task_id: int, payload: OpenClawEventCreate, db: Session = Depends(get_db)
    ) -> OpenClawTaskOut:
        return serialize_openclaw_task(record_openclaw_event(db, task_id, payload))

    @app.post("/api/openclaw/tasks/{task_id}/result", response_model=OpenClawTaskOut)
    def openclaw_result_endpoint(
        task_id: int, payload: OpenClawResultCreate, db: Session = Depends(get_db)
    ) -> OpenClawTaskOut:
        return serialize_openclaw_task(complete_openclaw_task(db, task_id, payload))

    return app


app = create_app()
