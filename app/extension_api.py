from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, joinedload

from .database import get_db
from .extension_security import ExtensionAuth
from .models import (
    BacklinkTask,
    BacklinkTaskStatus,
    Opportunity,
    OpportunityType,
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


@router.get("/health", response_model=HealthResponse)
def health(_token: ExtensionAuth) -> HealthResponse:
    return HealthResponse()


@router.get("/projects", response_model=list[ProjectResponse])
def projects(_token: ExtensionAuth, db: Db) -> list[ProjectResponse]:
    sites = db.scalars(select(TargetSite).order_by(TargetSite.name)).all()
    return [ProjectResponse(id=site.id, name=site.name, website=site.url) for site in sites]


@router.post("/tasks/next/claim", response_model=TaskResponse)
def claim_next_task(payload: ClaimTaskRequest, token: ExtensionAuth, db: Db) -> TaskResponse:
    if payload.projectId <= 0 or db.get(TargetSite, payload.projectId) is None:
        raise HTTPException(404, "项目不存在")
    now = now_local()
    active = db.scalar(
        select(BacklinkTask)
        .options(joinedload(BacklinkTask.opportunity))
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
                .options(joinedload(BacklinkTask.opportunity))
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
            BacklinkTaskStatus.prepared,
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
        .options(joinedload(BacklinkTask.opportunity))
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
    )
