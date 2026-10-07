from __future__ import annotations

import enum
import json
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now_local() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


class ChannelType(str, enum.Enum):
    forum = "forum"
    directory = "directory"
    blog_comment = "blog_comment"
    advertorial = "advertorial"
    other = "other"


class ChannelStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    banned = "banned"


class LinkType(str, enum.Enum):
    dofollow = "dofollow"
    nofollow = "nofollow"


class PublishMethod(str, enum.Enum):
    manual = "manual"
    auto = "auto"


class BacklinkOrigin(str, enum.Enum):
    manual = "manual"
    batch = "batch"
    automation = "automation"
    extension_verified = "extension_verified"


class RecordStatus(str, enum.Enum):
    pending = "pending"
    live = "live"
    removed = "removed"


class SubmissionBatchStatus(str, enum.Enum):
    planned = "planned"
    partial = "partial"
    completed = "completed"
    cancelled = "cancelled"


class SubmissionItemStatus(str, enum.Enum):
    planned = "planned"
    completed = "completed"
    cancelled = "cancelled"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    needs_attention = "needs_attention"


class OpportunityType(str, enum.Enum):
    blog_comment = "blog_comment"
    article = "article"
    guest_post = "guest_post"
    directory = "directory"
    forum = "forum"
    other = "other"
    unknown = "unknown"


class OpportunitySource(str, enum.Enum):
    manual = "manual"
    csv = "csv"
    semrush = "semrush"
    page_discovery = "page_discovery"
    competitor_backlink = "competitor_backlink"


class OpportunityStatus(str, enum.Enum):
    new = "new"
    scanned = "scanned"
    eligible = "eligible"
    maybe = "maybe"
    unsupported = "unsupported"
    processed = "processed"


class BacklinkTaskStatus(str, enum.Enum):
    ready = "ready"
    processing = "processing"
    prepared = "prepared"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class SubmissionStatus(str, enum.Enum):
    prepared = "prepared"
    submitted = "submitted"
    pending = "pending"
    published = "published"
    duplicate = "duplicate"
    rejected = "rejected"
    failed = "failed"
    removed = "removed"
    unknown = "unknown"


class VerificationOutcome(str, enum.Enum):
    active = "active"
    pending = "pending"
    removed = "removed"
    page_404 = "page_404"
    link_missing = "link_missing"
    unknown = "unknown"


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class TargetSite(Base):
    __tablename__ = "target_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    author_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    tagline: Mapped[str | None] = mapped_column(String(300))
    short_description: Mapped[str | None] = mapped_column(Text)
    medium_description: Mapped[str | None] = mapped_column(Text)
    long_description: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    records: Mapped[list[BacklinkRecord]] = relationship(back_populates="target_site", cascade="all, delete-orphan")
    tasks: Mapped[list[AutomationTask]] = relationship(back_populates="target_site", cascade="all, delete-orphan")
    backlink_tasks: Mapped[list[BacklinkTask]] = relationship(
        back_populates="target_site", cascade="all, delete-orphan"
    )
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="target_site", cascade="all, delete-orphan"
    )


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    channel_type: Mapped[ChannelType] = mapped_column(Enum(ChannelType), index=True)
    channel_type_other: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[ChannelStatus] = mapped_column(Enum(ChannelStatus), default=ChannelStatus.active, index=True)
    requires_login: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    link_type: Mapped[LinkType | None] = mapped_column(Enum(LinkType), index=True)
    dr_value: Mapped[int | None] = mapped_column(Integer)
    monthly_traffic: Mapped[int | None] = mapped_column(Integer)
    supports_automation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    adapter_key: Mapped[str | None] = mapped_column(String(80))
    adapter_config: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    records: Mapped[list[BacklinkRecord]] = relationship(back_populates="channel", cascade="all, delete-orphan")
    credential: Mapped[ChannelCredential | None] = relationship(
        back_populates="channel", cascade="all, delete-orphan", uselist=False
    )
    tasks: Mapped[list[AutomationTask]] = relationship(back_populates="channel", cascade="all, delete-orphan")
    submission_batches: Mapped[list[SubmissionBatch]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    opportunities: Mapped[list[Opportunity]] = relationship(back_populates="channel")


class ExtensionToken(Base):
    __tablename__ = "extension_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    token_prefix: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    claimed_tasks: Mapped[list[BacklinkTask]] = relationship(back_populates="claimed_by_token")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    url: Mapped[str] = mapped_column(String(2048), index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    opportunity_type: Mapped[OpportunityType] = mapped_column(
        Enum(OpportunityType), default=OpportunityType.unknown, index=True
    )
    source: Mapped[OpportunitySource] = mapped_column(
        Enum(OpportunitySource), default=OpportunitySource.manual, index=True
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(OpportunityStatus), default=OpportunityStatus.new, index=True
    )
    page_title: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(20))
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    has_comment_form: Mapped[bool | None] = mapped_column(Boolean)
    has_website_field: Mapped[bool | None] = mapped_column(Boolean)
    requires_login: Mapped[bool | None] = mapped_column(Boolean)
    has_captcha: Mapped[bool | None] = mapped_column(Boolean)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    channel: Mapped[Channel | None] = relationship(back_populates="opportunities")
    tasks: Mapped[list[BacklinkTask]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )


class BacklinkTask(Base):
    __tablename__ = "backlink_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_site_id: Mapped[int] = mapped_column(
        ForeignKey("target_sites.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    target_url: Mapped[str] = mapped_column(String(2048))
    workflow: Mapped[OpportunityType] = mapped_column(Enum(OpportunityType), index=True)
    status: Mapped[BacklinkTaskStatus] = mapped_column(
        Enum(BacklinkTaskStatus), default=BacklinkTaskStatus.ready, index=True
    )
    anchor_text: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)
    claimed_by_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("extension_tokens.id", ondelete="SET NULL"), index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    target_site: Mapped[TargetSite] = relationship(back_populates="backlink_tasks")
    opportunity: Mapped[Opportunity] = relationship(back_populates="tasks")
    claimed_by_token: Mapped[ExtensionToken | None] = relationship(back_populates="claimed_tasks")
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("backlink_tasks.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    target_site_id: Mapped[int] = mapped_column(
        ForeignKey("target_sites.id", ondelete="CASCADE"), index=True
    )
    backlink_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("backlink_records.id", ondelete="SET NULL"), index=True
    )
    target_url: Mapped[str] = mapped_column(String(2048))
    target_domain: Mapped[str] = mapped_column(String(255), index=True)
    source_url: Mapped[str] = mapped_column(String(2048), index=True)
    source_domain: Mapped[str] = mapped_column(String(255), index=True)
    workflow: Mapped[OpportunityType] = mapped_column(Enum(OpportunityType), index=True)
    submitted_content: Mapped[str | None] = mapped_column(Text)
    submitted_website: Mapped[str | None] = mapped_column(String(2048))
    anchor_text: Mapped[str | None] = mapped_column(String(500))
    submission_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus), default=SubmissionStatus.prepared, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    result_message: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    prepared_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    task: Mapped[BacklinkTask] = relationship(back_populates="submissions")
    opportunity: Mapped[Opportunity] = relationship(back_populates="submissions")
    target_site: Mapped[TargetSite] = relationship(back_populates="submissions")
    backlink_record: Mapped[BacklinkRecord | None] = relationship(foreign_keys=[backlink_record_id])
    verifications: Mapped[list[BacklinkVerification]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="BacklinkVerification.id"
    )


class BacklinkVerification(Base):
    __tablename__ = "backlink_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("backlink_tasks.id", ondelete="CASCADE"), index=True
    )
    target_site_id: Mapped[int] = mapped_column(
        ForeignKey("target_sites.id", ondelete="CASCADE"), index=True
    )
    backlink_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("backlink_records.id", ondelete="SET NULL"), index=True
    )
    verified_by_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("extension_tokens.id", ondelete="SET NULL"), index=True
    )
    source_url: Mapped[str] = mapped_column(String(2048))
    target_url: Mapped[str] = mapped_column(String(2048))
    outcome: Mapped[VerificationOutcome] = mapped_column(Enum(VerificationOutcome), index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    anchor_text: Mapped[str | None] = mapped_column(String(500))
    link_rel: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    submission: Mapped[Submission] = relationship(back_populates="verifications")
    backlink_record: Mapped[BacklinkRecord | None] = relationship(foreign_keys=[backlink_record_id])


class ChannelBlacklist(Base):
    __tablename__ = "channel_blacklist"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)


class ChannelCredential(Base):
    __tablename__ = "channel_credentials"
    __table_args__ = (UniqueConstraint("channel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    username: Mapped[str | None] = mapped_column(String(255))
    encrypted_password: Mapped[str | None] = mapped_column(Text)
    encrypted_extra_fields: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    channel: Mapped[Channel] = relationship(back_populates="credential")


class BacklinkRecord(Base):
    __tablename__ = "backlink_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_site_id: Mapped[int] = mapped_column(ForeignKey("target_sites.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    actual_url: Mapped[str] = mapped_column(String(2048))
    target_url: Mapped[str | None] = mapped_column(String(2048))
    anchor_text: Mapped[str] = mapped_column(String(500))
    link_rel: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[date] = mapped_column(Date, index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    method: Mapped[PublishMethod] = mapped_column(Enum(PublishMethod), index=True)
    origin: Mapped[BacklinkOrigin] = mapped_column(
        Enum(BacklinkOrigin), default=BacklinkOrigin.manual, index=True
    )
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    target_site: Mapped[TargetSite] = relationship(back_populates="records")
    channel: Mapped[Channel] = relationship(back_populates="records")
    submission_item: Mapped[SubmissionBatchItem | None] = relationship(back_populates="record", uselist=False)


class SubmissionBatch(Base):
    __tablename__ = "submission_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    scheduled_for: Mapped[date] = mapped_column(Date, index=True)
    shared_url: Mapped[str | None] = mapped_column(String(2048))
    anchor_text: Mapped[str | None] = mapped_column(String(500))
    record_status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.live)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SubmissionBatchStatus] = mapped_column(
        Enum(SubmissionBatchStatus), default=SubmissionBatchStatus.planned, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    channel: Mapped[Channel] = relationship(back_populates="submission_batches")
    items: Mapped[list[SubmissionBatchItem]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="SubmissionBatchItem.id",
    )


class SubmissionBatchItem(Base):
    __tablename__ = "submission_batch_items"
    __table_args__ = (UniqueConstraint("batch_id", "target_site_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("submission_batches.id", ondelete="CASCADE"), index=True)
    target_site_id: Mapped[int] = mapped_column(ForeignKey("target_sites.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int | None] = mapped_column(
        ForeignKey("backlink_records.id", ondelete="SET NULL"), unique=True, index=True
    )
    status: Mapped[SubmissionItemStatus] = mapped_column(
        Enum(SubmissionItemStatus), default=SubmissionItemStatus.planned, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    batch: Mapped[SubmissionBatch] = relationship(back_populates="items")
    target_site: Mapped[TargetSite] = relationship()
    record: Mapped[BacklinkRecord | None] = relationship(back_populates="submission_item")


class AutomationTask(Base):
    __tablename__ = "automation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_site_id: Mapped[int] = mapped_column(ForeignKey("target_sites.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    anchor_text: Mapped[str] = mapped_column(String(500))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    actual_url: Mapped[str | None] = mapped_column(String(2048))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    target_site: Mapped[TargetSite] = relationship(back_populates="tasks")
    channel: Mapped[Channel] = relationship(back_populates="tasks")
    logs: Mapped[list[AutomationTaskLog]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="AutomationTaskLog.created_at.desc()"
    )


class AutomationTaskLog(Base):
    __tablename__ = "automation_task_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("automation_tasks.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    task: Mapped[AutomationTask] = relationship(back_populates="logs")


class ItchGameStatus(str, enum.Enum):
    new = "new"          # 已从 RSS 入库，详情未补全
    ready = "ready"      # 详情已补全，可导出交给 AI 制作页面
    used = "used"        # 已用于 PlayBloo 建页
    skipped = "skipped"  # 人工判定不采用


class ItchGame(Base):
    """itch.io 新游戏雷达的入库记录：RSS 提供基础字段，详情页按需补全。"""

    __tablename__ = "itch_games"
    __table_args__ = (UniqueConstraint("url", name="uq_itch_games_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    author: Mapped[str | None] = mapped_column(String(200))
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(String(60))
    source_feed: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[ItchGameStatus] = mapped_column(
        Enum(ItchGameStatus), default=ItchGameStatus.new, index=True
    )
    # itch 侧的精确上架时间（东八区 naive）；RSS 缺失时由详情页 Published 补充。
    itch_published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    genre_json: Mapped[str | None] = mapped_column(Text)
    tags_json: Mapped[str | None] = mapped_column(Text)
    platforms_json: Mapped[str | None] = mapped_column(Text)
    screenshots_json: Mapped[str | None] = mapped_column(Text)
    keywords_json: Mapped[str | None] = mapped_column(Text)
    quality_json: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    def _json_list(self, raw: str | None) -> list:
        try:
            return json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []

    @property
    def genres(self) -> list[str]:
        return self._json_list(self.genre_json)

    @property
    def tags(self) -> list[str]:
        return self._json_list(self.tags_json)

    @property
    def platforms(self) -> list[str]:
        return self._json_list(self.platforms_json)

    @property
    def screenshots(self) -> list[str]:
        return self._json_list(self.screenshots_json)

    @property
    def keywords(self) -> list[str]:
        return self._json_list(self.keywords_json)

    @property
    def quality(self) -> dict:
        try:
            return json.loads(self.quality_json or "{}")
        except json.JSONDecodeError:
            return {}

    @property
    def quality_ok(self) -> bool:
        return bool(self.quality.get("ok", False)) if self.quality else True

    @property
    def quality_notes(self) -> list[str]:
        return self.quality.get("notes", [])

    @property
    def effective_published_at(self) -> datetime:
        return self.itch_published_at or self.discovered_at
