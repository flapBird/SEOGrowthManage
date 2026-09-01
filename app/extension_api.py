from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, joinedload

from .channel_blacklist import channel_host
from .database import get_db
from .extension_security import ExtensionAuth
from .models import (
    BacklinkTask,
    BacklinkTaskStatus,
    BacklinkRecord,
    Channel,
    Opportunity,
    OpportunityType,
    Submission,
    SubmissionStatus,
    TargetSite,
    now_local,
)


router = APIRouter(prefix="/api/v1", tags=["extension-api"])
Db = Annotated[Session, Depends(get_db)]
LEASE_MINUTES = 20


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    service: str = "seo-growth-console"
    api_version: str = "v1"


class ProjectResponse(ApiModel):
    id: int
    name: str
    website: str
    author_name: str | None = None
    email: str | None = None
    tagline: str | None = None
    short_description: str | None = None
    medium_description: str | None = None
    long_description: str | None = None
    keywords: list[str] = Field(default_factory=list)


class ClaimTaskRequest(BaseModel):
    projectId: int


class UpdateTaskRequest(BaseModel):
    status: BacklinkTaskStatus
    note: str | None = None


class TaskResponse(ApiModel):
    id: int
    project_id: int
    opportunity_id: int
    workflow: OpportunityType
    status: BacklinkTaskStatus
    source_url: str
    source_domain: str
    target_url: str
    anchor_text: str | None = None
    note: str | None = None
    lease_expires_at: str | None = None
    created_at: str
    updated_at: str
    project: ProjectResponse


class CreateSubmissionRequest(BaseModel):
    taskId: int
    status: Literal["prepared"]
    targetUrl: str
    sourceUrl: str
    workflow: OpportunityType
    submittedContent: str | None = None
    submittedWebsite: str | None = None
    anchorText: str | None = None
    resultMessage: str | None = None
    note: str | None = None


class SubmissionResponse(ApiModel):
    id: int
    task_id: int
    opportunity_id: int
    project_id: int
    target_url: str
    target_domain: str
    source_url: str
    source_domain: str
    workflow: OpportunityType
    submitted_content: str | None = None
    submitted_website: str | None = None
    anchor_text: str | None = None
    submission_url: str | None = None
    status: SubmissionStatus
    submitted_at: str | None = None
    verified_at: str | None = None
    result_message: str | None = None
    note: str | None = None
    prepared_at: str
    created_at: str
    updated_at: str


class SubmissionCheckResponse(ApiModel):
    exact_submission_count: int
    domain_submission_count: int
    domain_backlink_count: int
    latest_status: SubmissionStatus | None = None


@router.get("/health", response_model=HealthResponse)
def health(_token: ExtensionAuth) -> HealthResponse:
    return HealthResponse()


@router.get("/projects", response_model=list[ProjectResponse])
def projects(_token: ExtensionAuth, db: Db) -> list[ProjectResponse]:
    sites = db.scalars(select(TargetSite).order_by(TargetSite.name)).all()
    return [project_response(site) for site in sites]


@router.post("/tasks/next/claim", response_model=TaskResponse)
def claim_next_task(payload: ClaimTaskRequest, token: ExtensionAuth, db: Db) -> TaskResponse:
    if payload.projectId <= 0 or db.get(TargetSite, payload.projectId) is None:
        raise HTTPException(404, "项目不存在")
    now = now_local()
    active = db.scalar(
        select(BacklinkTask)
        .options(joinedload(BacklinkTask.opportunity), joinedload(BacklinkTask.target_site))
        .where(
            BacklinkTask.target_site_id == payload.projectId,
            BacklinkTask.status == BacklinkTaskStatus.processing,
            BacklinkTask.claimed_by_token_id == token.id,
            BacklinkTask.lease_expires_at > now,
        )
        .order_by(BacklinkTask.updated_at, BacklinkTask.id)
    )
    if active is not None:
        return task_response(active)

    candidate_ids = db.scalars(
        select(BacklinkTask.id)
        .where(
            BacklinkTask.target_site_id == payload.projectId,
            or_(
                BacklinkTask.status == BacklinkTaskStatus.ready,
                and_(
                    BacklinkTask.status == BacklinkTaskStatus.processing,
                    or_(
                        BacklinkTask.lease_expires_at.is_(None),
                        BacklinkTask.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .order_by(BacklinkTask.created_at, BacklinkTask.id)
        .limit(10)
    ).all()
    lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    for task_id in candidate_ids:
        claimed = db.execute(
            update(BacklinkTask)
            .where(
                BacklinkTask.id == task_id,
                or_(
                    BacklinkTask.status == BacklinkTaskStatus.ready,
                    and_(
                        BacklinkTask.status == BacklinkTaskStatus.processing,
                        or_(
                            BacklinkTask.lease_expires_at.is_(None),
                            BacklinkTask.lease_expires_at <= now,
                        ),
                    ),
                ),
            )
            .values(
                status=BacklinkTaskStatus.processing,
                claimed_by_token_id=token.id,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
        )
        if claimed.rowcount == 1:
            db.commit()
            task = db.scalar(
                select(BacklinkTask)
                .options(joinedload(BacklinkTask.opportunity), joinedload(BacklinkTask.target_site))
                .where(BacklinkTask.id == task_id)
            )
            if task is not None:
                return task_response(task)
        db.rollback()
    raise HTTPException(404, "当前项目没有可领取的插件任务")


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def task_detail(task_id: int, token: ExtensionAuth, db: Db) -> TaskResponse:
    task = load_task(db, task_id)
    if task.claimed_by_token_id != token.id:
        raise HTTPException(409, "该任务未由当前 Extension Token 领取")
    return task_response(task)


@router.get("/submissions/check", response_model=SubmissionCheckResponse)
def submission_check(
    projectId: int,
    sourceUrl: str,
    _token: ExtensionAuth,
    db: Db,
) -> SubmissionCheckResponse:
    if db.get(TargetSite, projectId) is None:
        raise HTTPException(404, "项目不存在")
    source_url = normalize_http_url(sourceUrl)
    source_domain = channel_host(source_url)
    exact = db.scalars(
        select(Submission).where(
            Submission.target_site_id == projectId,
            Submission.source_url == source_url,
        )
    ).all()
    domain_submissions = db.scalars(
        select(Submission).where(
            Submission.target_site_id == projectId,
            Submission.source_domain == source_domain,
        )
    ).all()
    latest = max(domain_submissions, key=lambda item: item.created_at) if domain_submissions else None
    channels = {
        channel.id
        for channel in db.scalars(select(Channel)).all()
        if channel_host(channel.url) == source_domain
    }
    backlink_count = len(db.scalars(
        select(BacklinkRecord).where(
            BacklinkRecord.target_site_id == projectId,
            BacklinkRecord.channel_id.in_(channels),
        )
    ).all()) if channels else 0
    return SubmissionCheckResponse(
        exact_submission_count=len(exact),
        domain_submission_count=len(domain_submissions),
        domain_backlink_count=backlink_count,
        latest_status=latest.status if latest else None,
    )


@router.get("/submissions", response_model=list[SubmissionResponse])
def submissions_list(
    _token: ExtensionAuth,
    db: Db,
    taskId: int | None = None,
    projectId: int | None = None,
    limit: int = 50,
) -> list[SubmissionResponse]:
    if limit < 1 or limit > 200:
        raise HTTPException(422, "limit 必须在 1 到 200 之间")
    stmt = select(Submission)
    if taskId is not None:
        stmt = stmt.where(Submission.task_id == taskId)
    if projectId is not None:
        stmt = stmt.where(Submission.target_site_id == projectId)
    records = db.scalars(
        stmt.order_by(Submission.created_at.desc(), Submission.id.desc()).limit(limit)
    ).all()
    return [submission_response(record) for record in records]


@router.post("/submissions", response_model=SubmissionResponse)
def submission_create(
    payload: CreateSubmissionRequest,
    token: ExtensionAuth,
    db: Db,
    _idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmissionResponse:
    task = load_task(db, payload.taskId)
    if task.claimed_by_token_id != token.id:
        raise HTTPException(409, "该任务未由当前 Extension Token 领取")
    if task.status not in {BacklinkTaskStatus.processing, BacklinkTaskStatus.prepared}:
        raise HTTPException(409, f"任务状态 {task.status.value} 不能创建 prepared Submission")
    if payload.workflow != task.workflow:
        raise HTTPException(422, "Submission 工作流与任务不一致")
    source_url = normalize_http_url(payload.sourceUrl)
    source_domain = channel_host(source_url)
    if source_domain != task.opportunity.domain:
        raise HTTPException(422, "当前页面域名与任务来源域名不一致")
    target_url = normalize_http_url(payload.targetUrl)
    if target_url != normalize_http_url(task.target_url):
        raise HTTPException(422, "Submission Target URL 与任务不一致")

    submission = db.scalar(
        select(Submission)
        .where(
            Submission.task_id == task.id,
            Submission.source_url == source_url,
            Submission.status == SubmissionStatus.prepared,
        )
        .order_by(Submission.created_at.desc())
    )
    if submission is None:
        submission = Submission(
            task_id=task.id,
            opportunity_id=task.opportunity_id,
            target_site_id=task.target_site_id,
            target_url=task.target_url,
            target_domain=channel_host(task.target_url),
            source_url=source_url,
            source_domain=source_domain,
            workflow=task.workflow,
            status=SubmissionStatus.prepared,
        )
        db.add(submission)
    submission.submitted_content = clean_optional(payload.submittedContent)
    submission.submitted_website = clean_optional(payload.submittedWebsite)
    submission.anchor_text = clean_optional(payload.anchorText)
    submission.result_message = clean_optional(payload.resultMessage)
    submission.note = clean_optional(payload.note)
    submission.updated_at = now_local()
    task.status = BacklinkTaskStatus.prepared
    task.lease_expires_at = None
    task.updated_at = now_local()
    db.commit()
    db.refresh(submission)
    return submission_response(submission)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def task_update(
    task_id: int,
    payload: UpdateTaskRequest,
    token: ExtensionAuth,
    db: Db,
) -> TaskResponse:
    task = load_task(db, task_id)
    if task.claimed_by_token_id != token.id:
        raise HTTPException(409, "该任务未由当前 Extension Token 领取")
    allowed = {
        BacklinkTaskStatus.processing: {
            BacklinkTaskStatus.processing,
            BacklinkTaskStatus.completed,
            BacklinkTaskStatus.failed,
            BacklinkTaskStatus.skipped,
        },
        BacklinkTaskStatus.prepared: {
            BacklinkTaskStatus.processing,
            BacklinkTaskStatus.completed,
            BacklinkTaskStatus.failed,
            BacklinkTaskStatus.skipped,
        },
    }
    if payload.status not in allowed.get(task.status, set()):
        raise HTTPException(409, f"不允许从 {task.status.value} 转为 {payload.status.value}")
    task.status = payload.status
    if payload.note is not None:
        task.note = payload.note.strip() or None
    task.updated_at = now_local()
    if payload.status == BacklinkTaskStatus.processing:
        task.lease_expires_at = now_local() + timedelta(minutes=LEASE_MINUTES)
    else:
        task.lease_expires_at = None
    db.commit()
    db.refresh(task)
    return task_response(task)


def load_task(db: Session, task_id: int) -> BacklinkTask:
    task = db.scalar(
        select(BacklinkTask)
        .options(joinedload(BacklinkTask.opportunity), joinedload(BacklinkTask.target_site))
        .where(BacklinkTask.id == task_id)
    )
    if task is None:
        raise HTTPException(404, "插件任务不存在")
    return task


def task_response(task: BacklinkTask) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        project_id=task.target_site_id,
        opportunity_id=task.opportunity_id,
        workflow=task.workflow,
        status=task.status,
        source_url=task.opportunity.url,
        source_domain=task.opportunity.domain,
        target_url=task.target_url,
        anchor_text=task.anchor_text,
        note=task.note,
        lease_expires_at=task.lease_expires_at.isoformat() if task.lease_expires_at else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        project=project_response(task.target_site),
    )


def project_response(site: TargetSite) -> ProjectResponse:
    return ProjectResponse(
        id=site.id,
        name=site.name,
        website=site.url,
        author_name=site.author_name,
        email=site.email,
        tagline=site.tagline,
        short_description=site.short_description,
        medium_description=site.medium_description,
        long_description=site.long_description,
        keywords=[item.strip() for item in (site.keywords or "").split(",") if item.strip()],
    )


def submission_response(submission: Submission) -> SubmissionResponse:
    return SubmissionResponse(
        id=submission.id,
        task_id=submission.task_id,
        opportunity_id=submission.opportunity_id,
        project_id=submission.target_site_id,
        target_url=submission.target_url,
        target_domain=submission.target_domain,
        source_url=submission.source_url,
        source_domain=submission.source_domain,
        workflow=submission.workflow,
        submitted_content=submission.submitted_content,
        submitted_website=submission.submitted_website,
        anchor_text=submission.anchor_text,
        submission_url=submission.submission_url,
        status=submission.status,
        submitted_at=submission.submitted_at.isoformat() if submission.submitted_at else None,
        verified_at=submission.verified_at.isoformat() if submission.verified_at else None,
        result_message=submission.result_message,
        note=submission.note,
        prepared_at=submission.prepared_at.isoformat(),
        created_at=submission.created_at.isoformat(),
        updated_at=submission.updated_at.isoformat(),
    )


def normalize_http_url(value: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(422, "URL 必须是有效的 HTTP/HTTPS 地址")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
