from __future__ import annotations

import enum
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


class PublishMethod(str, enum.Enum):
    manual = "manual"
    auto = "auto"


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


class KeywordSourceType(str, enum.Enum):
    sitemap = "sitemap"
    trends_rss = "trends_rss"
    manual = "manual"


class KeywordCandidateStatus(str, enum.Enum):
    discovered = "discovered"
    hot = "hot"
    hold = "hold"
    ignore = "ignore"


class KeywordFetchStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


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
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    records: Mapped[list[BacklinkRecord]] = relationship(back_populates="target_site", cascade="all, delete-orphan")
    tasks: Mapped[list[AutomationTask]] = relationship(back_populates="target_site", cascade="all, delete-orphan")


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    channel_type: Mapped[ChannelType] = mapped_column(Enum(ChannelType), index=True)
    channel_type_other: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[ChannelStatus] = mapped_column(Enum(ChannelStatus), default=ChannelStatus.active, index=True)
    requires_login: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    login_username: Mapped[str | None] = mapped_column(String(255))
    login_password: Mapped[str | None] = mapped_column(String(255))
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
    anchor_text: Mapped[str] = mapped_column(String(500))
    published_at: Mapped[date] = mapped_column(Date, index=True)
    method: Mapped[PublishMethod] = mapped_column(Enum(PublishMethod), index=True)
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


class KeywordSource(Base):
    __tablename__ = "keyword_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    source_type: Mapped[KeywordSourceType] = mapped_column(Enum(KeywordSourceType), index=True)
    url: Mapped[str | None] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    terms_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(20), default="en")
    country: Mapped[str] = mapped_column(String(10), default="US")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    config_json: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    items: Mapped[list[KeywordSourceItem]] = relationship(back_populates="source", cascade="all, delete-orphan")
    runs: Mapped[list[KeywordFetchRun]] = relationship(back_populates="source", cascade="all, delete-orphan")
    signals: Mapped[list[KeywordSignalSnapshot]] = relationship(back_populates="source")


class KeywordSourceItem(Base):
    __tablename__ = "keyword_source_items"
    __table_args__ = (UniqueConstraint("source_id", "fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("keyword_sources.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    raw_title: Mapped[str] = mapped_column(String(1000))
    item_url: Mapped[str | None] = mapped_column(String(2048))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    source: Mapped[KeywordSource] = relationship(back_populates="items")


class KeywordCandidate(Base):
    __tablename__ = "keyword_candidates"
    __table_args__ = (UniqueConstraint("normalized_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(300), index=True)
    normalized_key: Mapped[str] = mapped_column(String(300), index=True)
    language: Mapped[str] = mapped_column(String(20), default="en")
    country: Mapped[str] = mapped_column(String(10), default="US")
    status: Mapped[KeywordCandidateStatus] = mapped_column(
        Enum(KeywordCandidateStatus), default=KeywordCandidateStatus.discovered, index=True
    )
    heat_score: Mapped[float] = mapped_column(Float, default=0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0)
    intent_score: Mapped[float] = mapped_column(Float, default=0)
    competition_score: Mapped[float] = mapped_column(Float, default=0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    ignored_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    signals: Mapped[list[KeywordSignalSnapshot]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="KeywordSignalSnapshot.captured_at.desc()"
    )


class KeywordSignalSnapshot(Base):
    __tablename__ = "keyword_signal_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("keyword_candidates.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_sources.id", ondelete="SET NULL"), index=True)
    signal_type: Mapped[str] = mapped_column(String(80), index=True)
    numeric_value: Mapped[float | None] = mapped_column(Float)
    payload_json: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)

    candidate: Mapped[KeywordCandidate] = relationship(back_populates="signals")
    source: Mapped[KeywordSource | None] = relationship(back_populates="signals")


class KeywordFetchRun(Base):
    __tablename__ = "keyword_fetch_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("keyword_sources.id", ondelete="CASCADE"), index=True)
    status: Mapped[KeywordFetchStatus] = mapped_column(Enum(KeywordFetchStatus), index=True)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    new_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    source: Mapped[KeywordSource] = relationship(back_populates="runs")


class SerpApiPool(Base):
    __tablename__ = "serpapi_pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    quota_limit: Mapped[int | None] = mapped_column(Integer)
    quota_remaining: Mapped[int | None] = mapped_column(Integer, index=True)
    renewal_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)
