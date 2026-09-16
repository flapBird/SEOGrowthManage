from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .channel_blacklist import channel_host, matching_blacklist_entry
from .database import get_db
from .extension_security import issue_extension_token
from .models import (
    BacklinkTask,
    BacklinkTaskStatus,
    Channel,
    ExtensionToken,
    Opportunity,
    OpportunitySource,
    OpportunityStatus,
    OpportunityType,
    Submission,
    SubmissionStatus,
    TargetSite,
    now_local,
)
from .security import require_auth
from .web import get_or_404, redirect, render


router = APIRouter(dependencies=[Depends(require_auth)])
Db = Annotated[Session, Depends(get_db)]


def extension_context(db: Session, issued_token: str | None = None) -> dict:
    tasks = db.scalars(
        select(BacklinkTask)
        .options(
            joinedload(BacklinkTask.target_site),
            joinedload(BacklinkTask.opportunity),
            joinedload(BacklinkTask.claimed_by_token),
        )
        .order_by(BacklinkTask.created_at.desc(), BacklinkTask.id.desc())
        .limit(100)
    ).all()
    return {
        "tokens": db.scalars(
            select(ExtensionToken).order_by(ExtensionToken.created_at.desc())
        ).all(),
        "tasks": tasks,
        "submissions": db.scalars(
            select(Submission)
            .options(
                joinedload(Submission.target_site),
                joinedload(Submission.opportunity),
                joinedload(Submission.backlink_record),
                joinedload(Submission.verifications),
            )
            .order_by(Submission.created_at.desc(), Submission.id.desc())
            .limit(100)
        ).unique().all(),
        "sites": db.scalars(select(TargetSite).order_by(TargetSite.name)).all(),
        "issued_token": issued_token,
        "OpportunityType": OpportunityType,
        "BacklinkTaskStatus": BacklinkTaskStatus,
        "SubmissionStatus": SubmissionStatus,
    }


@router.get("/extension", response_class=HTMLResponse)
def extension_dashboard(request: Request, db: Db):
    return render(request, "extension/index.html", **extension_context(db))


@router.post("/extension/tokens", response_class=HTMLResponse)
def extension_token_create(
    request: Request,
    db: Db,
    name: Annotated[str, Form()] = "Chrome Extension",
    expires_days: Annotated[int, Form()] = 365,
):
    days = max(1, min(expires_days, 3650))
    _model, plaintext = issue_extension_token(
        db,
        name=name,
        expires_at=now_local() + timedelta(days=days),
    )
    return render(
        request,
        "extension/index.html",
        **extension_context(db, issued_token=plaintext),
    )


@router.post("/extension/tokens/{token_id}/revoke")
def extension_token_revoke(token_id: int, db: Db):
    token = get_or_404(db, ExtensionToken, token_id)
    if token.revoked_at is None:
        token.revoked_at = now_local()
        active_tasks = db.scalars(
            select(BacklinkTask).where(
                BacklinkTask.claimed_by_token_id == token.id,
                BacklinkTask.status == BacklinkTaskStatus.processing,
            )
        ).all()
        for task in active_tasks:
            task.status = BacklinkTaskStatus.ready
            task.claimed_by_token_id = None
            task.lease_expires_at = None
        db.commit()
    return redirect("/extension", "Extension Token 已撤销")


@router.post("/extension/tasks")
def extension_task_create(
    db: Db,
    target_site_id: Annotated[int, Form()],
    source_url: Annotated[str, Form()],
    workflow: Annotated[str, Form()],
    target_url: Annotated[str, Form()] = "",
    anchor_text: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
):
    site = get_or_404(db, TargetSite, target_site_id)
    normalized_url, domain = validate_source_url(source_url)
    blocked = matching_blacklist_entry(db, normalized_url)
    if blocked:
        raise HTTPException(422, f"来源域名 {blocked.domain} 已在外链黑名单中")
    try:
        parsed_workflow = OpportunityType(workflow)
    except ValueError as exc:
        raise HTTPException(422, "不支持的插件工作流") from exc
    if parsed_workflow == OpportunityType.unknown:
        raise HTTPException(422, "新任务不能使用 unknown 工作流")

    opportunity = db.scalar(select(Opportunity).where(Opportunity.url == normalized_url))
    if opportunity is None:
        matching_channel = next(
            (
                channel
                for channel in db.scalars(select(Channel)).all()
                if channel_host(channel.url) == domain
            ),
            None,
        )
        opportunity = Opportunity(
            channel_id=matching_channel.id if matching_channel else None,
            url=normalized_url,
            domain=domain,
            opportunity_type=parsed_workflow,
            source=OpportunitySource.manual,
            status=OpportunityStatus.eligible,
        )
        db.add(opportunity)
        db.flush()
    task = BacklinkTask(
        target_site_id=site.id,
        opportunity_id=opportunity.id,
        target_url=target_url.strip() or site.url,
        workflow=parsed_workflow,
        status=BacklinkTaskStatus.ready,
        anchor_text=anchor_text.strip() or None,
        note=note.strip() or None,
    )
    db.add(task)
    db.commit()
    return redirect("/extension", f"插件任务 #{task.id} 已加入队列")


@router.post("/extension/tasks/{task_id}/skip")
def extension_task_skip(task_id: int, db: Db):
    task = get_or_404(db, BacklinkTask, task_id)
    if task.status == BacklinkTaskStatus.completed:
        raise HTTPException(422, "已完成任务不能跳过")
    task.status = BacklinkTaskStatus.skipped
    task.lease_expires_at = None
    task.updated_at = now_local()
    db.commit()
    return redirect("/extension", f"插件任务 #{task.id} 已跳过")


def validate_source_url(value: str) -> tuple[str, str]:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(422, "任务来源 URL 必须是有效的 HTTP/HTTPS 地址")
    parsed = parsed._replace(fragment="")
    return parsed.geturl(), channel_host(parsed.geturl())
