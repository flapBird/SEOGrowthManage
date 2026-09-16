from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, joinedload

from .channel_blacklist import channel_host, matching_blacklist_entry
from .database import get_db
from .extension_security import ExtensionAuth
from .models import (
    BacklinkTask,
    BacklinkTaskStatus,
    BacklinkOrigin,
    BacklinkVerification,
    BacklinkRecord,
    Channel,
    ChannelStatus,
    ChannelType,
    Opportunity,
    OpportunitySource,
    OpportunityStatus,
    OpportunityType,
    PublishMethod,
    RecordStatus,
    Submission,
    SubmissionStatus,
    TargetSite,
    VerificationOutcome,
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


class CreateTaskRequest(BaseModel):
    projectId: int
    sourceUrl: str
    workflow: OpportunityType = OpportunityType.directory
    targetUrl: str | None = None
    anchorText: str | None = None
    note: str | None = None


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
    backlink_record_id: int | None = None
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


class UpdateSubmissionRequest(BaseModel):
    status: Literal["submitted", "pending", "duplicate", "rejected", "failed", "unknown"]
    submissionUrl: str | None = None
    resultMessage: str | None = None
    note: str | None = None


class CreateVerificationRequest(BaseModel):
    taskId: int
    submissionId: int
    sourceUrl: str
    targetUrl: str
    outcome: VerificationOutcome
    httpStatus: int | None = None
    anchorText: str | None = None
    linkRel: list[str] = Field(default_factory=list)
    checkedAt: datetime
    message: str | None = None


class VerificationResponse(ApiModel):
    id: int
    submission_id: int
    task_id: int
    project_id: int
    backlink_record_id: int | None = None
    source_url: str
    target_url: str
    outcome: VerificationOutcome
    http_status: int | None = None
    anchor_text: str | None = None
    link_rel: list[str] = Field(default_factory=list)
    message: str | None = None
    checked_at: str
    created_at: str


class VerificationResultResponse(ApiModel):
    verification: VerificationResponse
    submission: SubmissionResponse
    task: TaskResponse


class BacklinkHistoryResponse(ApiModel):
    id: int
    project_id: int
    project_name: str
    channel_id: int
    channel_name: str
    channel_url: str
    actual_url: str
    target_url: str
    anchor_text: str
    link_rel: list[str] = Field(default_factory=list)
    status: RecordStatus
    origin: BacklinkOrigin
    published_at: str
    first_seen_at: str | None = None
    last_verified_at: str | None = None
    submission_id: int | None = None


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


@router.post("/tasks", response_model=TaskResponse)
def task_create(payload: CreateTaskRequest, token: ExtensionAuth, db: Db) -> TaskResponse:
    """按来源 URL 直建任务并认领给当前 Token。

    与 /tasks/next/claim 的排队语义不同：调用方明确指定来源 URL（如外链
    技能按渠道清单提交），服务端按 URL 找或建 Opportunity 与任务，自动
    认领后返回；同一来源已有本项目有效任务时直接返回该任务，保证重试幂等。
    """
    site = db.get(TargetSite, payload.projectId)
    if payload.projectId <= 0 or site is None:
        raise HTTPException(404, "项目不存在")
    if payload.workflow == OpportunityType.unknown:
        raise HTTPException(422, "新任务不能使用 unknown 工作流")
    source_url = normalize_http_url(payload.sourceUrl)
    source_domain = channel_host(source_url)
    blocked = matching_blacklist_entry(db, source_url)
    if blocked:
        raise HTTPException(422, f"来源域名 {blocked.domain} 已在外链黑名单中")
    target_url = (
        normalize_http_url(payload.targetUrl)
        if payload.targetUrl and payload.targetUrl.strip()
        else normalize_http_url(site.url)
    )
    now = now_local()
    lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)

    opportunity = db.scalar(select(Opportunity).where(Opportunity.url == source_url))
    if opportunity is None:
        matching_channel = next(
            (
                channel for channel in db.scalars(select(Channel)).all()
                if channel_host(channel.url) == source_domain
            ),
            None,
        )
        opportunity = Opportunity(
            channel_id=matching_channel.id if matching_channel else None,
            url=source_url,
            domain=source_domain,
            opportunity_type=payload.workflow,
            source=OpportunitySource.manual,
            status=OpportunityStatus.eligible,
        )
        db.add(opportunity)
        db.flush()

    active = db.scalar(
        select(BacklinkTask)
        .where(
            BacklinkTask.opportunity_id == opportunity.id,
            BacklinkTask.target_site_id == site.id,
            BacklinkTask.status.in_((
                BacklinkTaskStatus.ready,
                BacklinkTaskStatus.processing,
                BacklinkTaskStatus.prepared,
            )),
        )
        .order_by(BacklinkTask.id.desc())
    )
    if active is not None:
        if (
            active.claimed_by_token_id not in (None, token.id)
            and active.status in (BacklinkTaskStatus.processing, BacklinkTaskStatus.prepared)
            and (active.lease_expires_at is None or active.lease_expires_at > now)
        ):
            raise HTTPException(409, "该任务已由其他 Extension Token 领取")
        active.status = BacklinkTaskStatus.processing
        active.claimed_by_token_id = token.id
        active.lease_expires_at = lease_expires_at
        active.updated_at = now
        db.commit()
        db.refresh(active)
        return task_response(active)

    task = BacklinkTask(
        target_site_id=site.id,
        opportunity_id=opportunity.id,
        target_url=target_url,
        workflow=payload.workflow,
        status=BacklinkTaskStatus.processing,
        claimed_by_token_id=token.id,
        lease_expires_at=lease_expires_at,
        anchor_text=clean_optional(payload.anchorText),
        note=clean_optional(payload.note),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task_response(task)


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


@router.patch("/submissions/{submission_id}", response_model=SubmissionResponse)
def submission_update(
    submission_id: int,
    payload: UpdateSubmissionRequest,
    token: ExtensionAuth,
    db: Db,
) -> SubmissionResponse:
    submission = load_submission(db, submission_id)
    assert_submission_owner(submission, token)
    desired = SubmissionStatus(payload.status)
    allowed = {
        SubmissionStatus.prepared: {
            SubmissionStatus.submitted,
            SubmissionStatus.pending,
            SubmissionStatus.duplicate,
            SubmissionStatus.rejected,
            SubmissionStatus.failed,
            SubmissionStatus.unknown,
        },
        SubmissionStatus.submitted: {
            SubmissionStatus.pending,
            SubmissionStatus.rejected,
            SubmissionStatus.failed,
            SubmissionStatus.unknown,
        },
        SubmissionStatus.pending: {
            SubmissionStatus.submitted,
            SubmissionStatus.rejected,
            SubmissionStatus.failed,
            SubmissionStatus.unknown,
        },
        SubmissionStatus.unknown: {
            SubmissionStatus.submitted,
            SubmissionStatus.pending,
            SubmissionStatus.duplicate,
            SubmissionStatus.rejected,
            SubmissionStatus.failed,
        },
        SubmissionStatus.duplicate: {SubmissionStatus.submitted, SubmissionStatus.pending},
        SubmissionStatus.rejected: {SubmissionStatus.submitted, SubmissionStatus.pending},
        SubmissionStatus.failed: {SubmissionStatus.submitted, SubmissionStatus.pending},
    }
    if desired != submission.status and desired not in allowed.get(submission.status, set()):
        raise HTTPException(409, f"不允许从 {submission.status.value} 转为 {desired.value}")
    if payload.submissionUrl:
        submission_url = normalize_http_url(payload.submissionUrl, keep_fragment=True)
        if channel_host(submission_url) != submission.source_domain:
            raise HTTPException(422, "提交结果 URL 与任务来源域名不一致")
        submission.submission_url = submission_url
    elif submission.submission_url is None:
        submission.submission_url = submission.source_url
    submission.status = desired
    if desired in {SubmissionStatus.submitted, SubmissionStatus.pending}:
        submission.submitted_at = submission.submitted_at or now_local()
    if payload.resultMessage is not None:
        submission.result_message = clean_optional(payload.resultMessage)
    if payload.note is not None:
        submission.note = clean_optional(payload.note)
    submission.updated_at = now_local()
    finish_task_for_submission(submission)
    submission.opportunity.status = OpportunityStatus.processed
    db.commit()
    db.refresh(submission)
    return submission_response(submission)


@router.get("/verifications", response_model=list[VerificationResponse])
def verifications_list(
    _token: ExtensionAuth,
    db: Db,
    submissionId: int | None = None,
    limit: int = 50,
) -> list[VerificationResponse]:
    if limit < 1 or limit > 200:
        raise HTTPException(422, "limit 必须在 1 到 200 之间")
    stmt = select(BacklinkVerification)
    if submissionId is not None:
        stmt = stmt.where(BacklinkVerification.submission_id == submissionId)
    records = db.scalars(
        stmt.order_by(BacklinkVerification.checked_at.desc(), BacklinkVerification.id.desc()).limit(limit)
    ).all()
    return [verification_response(record) for record in records]


@router.post("/verifications", response_model=VerificationResultResponse)
def verification_create(
    payload: CreateVerificationRequest,
    token: ExtensionAuth,
    db: Db,
    _idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> VerificationResultResponse:
    submission = load_submission(db, payload.submissionId)
    assert_submission_owner(submission, token)
    if payload.taskId != submission.task_id:
        raise HTTPException(422, "Verification 任务与 Submission 不一致")
    if submission.status == SubmissionStatus.prepared:
        raise HTTPException(409, "请先确认网页已经提交，再执行 Backlink 验证")
    source_url = normalize_http_url(payload.sourceUrl, keep_fragment=True)
    if channel_host(source_url) != submission.source_domain:
        raise HTTPException(422, "验证页面与 Submission 来源域名不一致")
    target_url = normalize_http_url(payload.targetUrl)
    if target_url != normalize_http_url(submission.target_url):
        raise HTTPException(422, "Verification Target URL 与 Submission 不一致")
    if payload.httpStatus is not None and not 100 <= payload.httpStatus <= 599:
        raise HTTPException(422, "HTTP 状态码必须在 100 到 599 之间")

    checked_at = now_local()
    verification = BacklinkVerification(
        submission_id=submission.id,
        task_id=submission.task_id,
        target_site_id=submission.target_site_id,
        verified_by_token_id=token.id,
        source_url=source_url,
        target_url=target_url,
        outcome=payload.outcome,
        http_status=payload.httpStatus,
        anchor_text=clean_optional(payload.anchorText),
        link_rel=json.dumps(payload.linkRel, ensure_ascii=False) if payload.linkRel else None,
        message=clean_optional(payload.message),
        checked_at=checked_at,
    )
    db.add(verification)

    if payload.outcome == VerificationOutcome.active:
        if matching_blacklist_entry(db, source_url):
            raise HTTPException(422, "来源域名已进入外链黑名单，不能创建正式 Backlink")
        channel = ensure_submission_channel(db, submission, source_url)
        record = submission.backlink_record
        if record is None:
            record = db.scalar(
                select(BacklinkRecord).where(
                    BacklinkRecord.target_site_id == submission.target_site_id,
                    BacklinkRecord.channel_id == channel.id,
                    BacklinkRecord.actual_url == source_url,
                )
            )
        if record is None:
            record = BacklinkRecord(
                target_site_id=submission.target_site_id,
                channel_id=channel.id,
                actual_url=source_url,
                target_url=target_url,
                anchor_text=clean_optional(payload.anchorText) or submission.anchor_text or submission.target_site.name,
                link_rel=json.dumps(payload.linkRel, ensure_ascii=False) if payload.linkRel else None,
                published_at=checked_at.date(),
                first_seen_at=checked_at,
                last_verified_at=checked_at,
                method=PublishMethod.manual,
                origin=BacklinkOrigin.extension_verified,
                status=RecordStatus.live,
            )
            db.add(record)
            db.flush()
        else:
            existing_page = urlsplit(record.actual_url)
            verified_page = urlsplit(source_url)
            if verified_page.fragment or (
                existing_page.scheme,
                existing_page.netloc,
                existing_page.path,
                existing_page.query,
            ) != (
                verified_page.scheme,
                verified_page.netloc,
                verified_page.path,
                verified_page.query,
            ):
                record.actual_url = source_url
            record.anchor_text = clean_optional(payload.anchorText) or record.anchor_text
            record.target_url = target_url
            record.link_rel = json.dumps(payload.linkRel, ensure_ascii=False) if payload.linkRel else record.link_rel
            record.first_seen_at = record.first_seen_at or checked_at
            record.last_verified_at = checked_at
            record.origin = BacklinkOrigin.extension_verified
            record.status = RecordStatus.live
        submission.backlink_record_id = record.id
        submission.status = SubmissionStatus.published
        submission.verified_at = checked_at
        submission.submission_url = source_url
        submission.task.status = BacklinkTaskStatus.completed
        verification.backlink_record_id = record.id
    elif payload.outcome in {
        VerificationOutcome.removed,
        VerificationOutcome.page_404,
        VerificationOutcome.link_missing,
    } and submission.backlink_record is not None:
        submission.backlink_record.status = RecordStatus.removed
        submission.backlink_record.last_verified_at = checked_at
        submission.status = SubmissionStatus.removed
        submission.verified_at = checked_at
        verification.backlink_record_id = submission.backlink_record.id
    elif payload.outcome == VerificationOutcome.pending:
        submission.status = SubmissionStatus.pending

    submission.result_message = clean_optional(payload.message) or submission.result_message
    submission.updated_at = checked_at
    submission.task.lease_expires_at = None
    submission.task.updated_at = checked_at
    submission.opportunity.status = OpportunityStatus.processed
    db.commit()
    db.refresh(verification)
    db.refresh(submission)
    return VerificationResultResponse(
        verification=verification_response(verification),
        submission=submission_response(submission),
        task=task_response(submission.task),
    )


@router.get("/backlinks/history", response_model=list[BacklinkHistoryResponse])
def backlink_history(
    _token: ExtensionAuth,
    db: Db,
    projectId: int | None = None,
    limit: int = 50,
) -> list[BacklinkHistoryResponse]:
    if limit < 1 or limit > 200:
        raise HTTPException(422, "limit 必须在 1 到 200 之间")
    stmt = select(BacklinkRecord).options(
        joinedload(BacklinkRecord.target_site), joinedload(BacklinkRecord.channel)
    )
    if projectId is not None:
        stmt = stmt.where(BacklinkRecord.target_site_id == projectId)
    records = db.scalars(
        stmt.order_by(BacklinkRecord.published_at.desc(), BacklinkRecord.id.desc()).limit(limit)
    ).all()
    result: list[BacklinkHistoryResponse] = []
    for record in records:
        submission_id = db.scalar(
            select(Submission.id).where(Submission.backlink_record_id == record.id)
        )
        result.append(BacklinkHistoryResponse(
            id=record.id,
            project_id=record.target_site_id,
            project_name=record.target_site.name,
            channel_id=record.channel_id,
            channel_name=record.channel.name,
            channel_url=record.channel.url,
            actual_url=record.actual_url,
            target_url=record.target_url or record.target_site.url,
            anchor_text=record.anchor_text,
            link_rel=decode_json_list(record.link_rel),
            status=record.status,
            origin=record.origin,
            published_at=record.published_at.isoformat(),
            first_seen_at=record.first_seen_at.isoformat() if record.first_seen_at else None,
            last_verified_at=record.last_verified_at.isoformat() if record.last_verified_at else None,
            submission_id=submission_id,
        ))
    return result


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


def load_submission(db: Session, submission_id: int) -> Submission:
    submission = db.scalar(
        select(Submission)
        .options(
            joinedload(Submission.task),
            joinedload(Submission.opportunity),
            joinedload(Submission.target_site),
            joinedload(Submission.backlink_record),
        )
        .where(Submission.id == submission_id)
    )
    if submission is None:
        raise HTTPException(404, "Submission 不存在")
    return submission


def assert_submission_owner(submission: Submission, token: ExtensionAuth) -> None:
    if submission.task.claimed_by_token_id != token.id:
        raise HTTPException(409, "该 Submission 不属于当前 Extension Token 领取的任务")


def finish_task_for_submission(submission: Submission) -> None:
    if submission.status in {SubmissionStatus.failed, SubmissionStatus.rejected}:
        submission.task.status = BacklinkTaskStatus.failed
    else:
        submission.task.status = BacklinkTaskStatus.completed
    submission.task.lease_expires_at = None
    submission.task.updated_at = now_local()


def ensure_submission_channel(db: Session, submission: Submission, source_url: str) -> Channel:
    if submission.opportunity.channel is not None:
        return submission.opportunity.channel
    channel = next(
        (
            item for item in db.scalars(select(Channel)).all()
            if channel_host(item.url) == submission.source_domain
        ),
        None,
    )
    if channel is None:
        parsed = urlsplit(source_url)
        channel = Channel(
            name=submission.source_domain,
            url=urlunsplit((parsed.scheme, parsed.netloc, "", "", "")),
            channel_type=channel_type_for_workflow(submission.workflow),
            status=ChannelStatus.active,
            requires_login=bool(submission.opportunity.requires_login),
            supports_automation=False,
        )
        db.add(channel)
        db.flush()
    submission.opportunity.channel_id = channel.id
    submission.opportunity.channel = channel
    return channel


def channel_type_for_workflow(workflow: OpportunityType) -> ChannelType:
    return {
        OpportunityType.blog_comment: ChannelType.blog_comment,
        OpportunityType.directory: ChannelType.directory,
        OpportunityType.forum: ChannelType.forum,
        OpportunityType.article: ChannelType.advertorial,
        OpportunityType.guest_post: ChannelType.advertorial,
    }.get(workflow, ChannelType.other)


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
        backlink_record_id=submission.backlink_record_id,
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


def verification_response(verification: BacklinkVerification) -> VerificationResponse:
    try:
        link_rel = json.loads(verification.link_rel) if verification.link_rel else []
    except json.JSONDecodeError:
        link_rel = []
    return VerificationResponse(
        id=verification.id,
        submission_id=verification.submission_id,
        task_id=verification.task_id,
        project_id=verification.target_site_id,
        backlink_record_id=verification.backlink_record_id,
        source_url=verification.source_url,
        target_url=verification.target_url,
        outcome=verification.outcome,
        http_status=verification.http_status,
        anchor_text=verification.anchor_text,
        link_rel=link_rel,
        message=verification.message,
        checked_at=verification.checked_at.isoformat(),
        created_at=verification.created_at.isoformat(),
    )


def decode_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def normalize_http_url(value: str, keep_fragment: bool = False) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(422, "URL 必须是有效的 HTTP/HTTPS 地址")
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path or "/",
        parsed.query,
        parsed.fragment if keep_fragment else "",
    ))


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
