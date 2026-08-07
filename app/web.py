from __future__ import annotations

import json
from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .config import BASE_DIR, get_settings
from .database import get_db
from .channel_blacklist import available_channels, is_channel_blacklisted, matching_blacklist_entry, normalize_blacklist_domain
from .models import (
    AutomationTask,
    BacklinkRecord,
    Channel,
    ChannelBlacklist,
    ChannelCredential,
    ChannelStatus,
    ChannelType,
    LinkType,
    PublishMethod,
    RecordStatus,
    SubmissionBatch,
    SubmissionBatchItem,
    SubmissionBatchStatus,
    SubmissionItemStatus,
    KeywordCandidateStatus,
    KeywordFetchStatus,
    KeywordSourceType,
    TargetSite,
    TaskStatus,
    now_local,
)
from .security import (
    SESSION_COOKIE,
    CredentialCipher,
    authenticate,
    create_session,
    delete_session,
    is_authenticated,
    require_auth,
)


CHANNEL_TYPE_LABELS = {
    ChannelType.forum: "论坛",
    ChannelType.directory: "目录",
    ChannelType.blog_comment: "博客评论",
    ChannelType.advertorial: "软文平台",
    ChannelType.other: "其它",
}


def channel_type_display(channel) -> str:
    """渠道类型展示文案：自定义类型优先返回用户填写的内容。"""
    if channel.channel_type == ChannelType.other and channel.channel_type_other:
        return channel.channel_type_other
    return CHANNEL_TYPE_LABELS.get(channel.channel_type, channel.channel_type.value)


templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
templates.env.globals.update(
    channel_type_labels=CHANNEL_TYPE_LABELS,
    channel_type_display=channel_type_display,
    channel_status_labels={
        ChannelStatus.active: "正常",
        ChannelStatus.inactive: "失效",
        ChannelStatus.banned: "已被封禁",
    },
    record_status_labels={
        RecordStatus.pending: "待确认",
        RecordStatus.live: "正常",
        RecordStatus.removed: "已失效",
    },
    task_status_labels={
        TaskStatus.pending: "等待中",
        TaskStatus.running: "执行中",
        TaskStatus.success: "成功",
        TaskStatus.failed: "等待重试",
        TaskStatus.needs_attention: "需人工介入",
    },
    submission_batch_status_labels={
        SubmissionBatchStatus.planned: "待提交",
        SubmissionBatchStatus.partial: "部分完成",
        SubmissionBatchStatus.completed: "已完成",
        SubmissionBatchStatus.cancelled: "已取消",
    },
    submission_item_status_labels={
        SubmissionItemStatus.planned: "待提交",
        SubmissionItemStatus.completed: "已完成",
        SubmissionItemStatus.cancelled: "已取消",
    },
   ChannelType=ChannelType,
   ChannelStatus=ChannelStatus,
    LinkType=LinkType,
    link_type_labels={
        LinkType.dofollow: "Dofollow",
        LinkType.nofollow: "Nofollow",
    },
   PublishMethod=PublishMethod,
    RecordStatus=RecordStatus,
    SubmissionBatchStatus=SubmissionBatchStatus,
    SubmissionItemStatus=SubmissionItemStatus,
    TaskStatus=TaskStatus,
    KeywordCandidateStatus=KeywordCandidateStatus,
    KeywordFetchStatus=KeywordFetchStatus,
    KeywordSourceType=KeywordSourceType,
    keyword_status_labels={
        KeywordCandidateStatus.discovered: "待分析",
        KeywordCandidateStatus.hot: "HOT",
        KeywordCandidateStatus.hold: "HOLD",
        KeywordCandidateStatus.ignore: "IGNORE",
    },
    keyword_source_type_labels={
        KeywordSourceType.sitemap: "Sitemap",
        KeywordSourceType.trends_rss: "趋势 RSS",
        KeywordSourceType.manual: "人工导入",
    },
    keyword_fetch_status_labels={
        KeywordFetchStatus.running: "运行中",
        KeywordFetchStatus.success: "成功",
        KeywordFetchStatus.failed: "失败",
    },
)

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_auth)])
Db = Annotated[Session, Depends(get_db)]


def render(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name=name, context=context)


def redirect(path: str, message: str | None = None) -> RedirectResponse:
    if message:
        separator = "&" if "?" in path else "?"
        path = f"{path}{separator}message={quote(message)}"
    return RedirectResponse(path, status_code=303)


def get_or_404(db: Session, model, object_id: int):
    value = db.get(model, object_id)
    if value is None:
        raise HTTPException(404, "记录不存在")
    return value


def optional_int(value: str | int | None, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"{field_name} 必须是有效整数") from exc


def optional_positive_int(value: str | int | None, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"{field_name} 必须是有效整数") from exc
    if parsed < 0:
        raise HTTPException(422, f"{field_name} 不能为负数")
    return parsed


def reject_blacklisted_channel(db: Session, channel: Channel) -> None:
    blocked = matching_blacklist_entry(db, channel.url)
    if blocked:
        raise HTTPException(422, f"渠道域名 {blocked.domain} 已在外链黑名单中")


@public_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Db, next: str = "/"):
    if is_authenticated(request, db):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", next=next, error=None)


@public_router.post("/login", response_class=HTMLResponse)
def login(request: Request, db: Db, username: Annotated[str, Form()], password: Annotated[str, Form()], next: Annotated[str, Form()] = "/"):
    if not authenticate(username, password):
        return render(request, "login.html", next=next, error="用户名或密码错误", status_code=401)
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(safe_next, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session(db),
        max_age=get_settings().session_days * 24 * 60 * 60,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Db):
    delete_session(db, request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=get_settings().cookie_secure, samesite="lax")
    return response


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Db):
    sites = db.scalars(select(TargetSite).order_by(TargetSite.name)).all()
    channels = db.scalars(select(Channel).order_by(Channel.name)).all()
    recent_records = db.scalars(
        select(BacklinkRecord)
        .options(joinedload(BacklinkRecord.target_site), joinedload(BacklinkRecord.channel))
        .order_by(BacklinkRecord.published_at.desc(), BacklinkRecord.id.desc())
        .limit(10)
    ).all()
    pending_tasks = db.scalars(
        select(AutomationTask)
        .options(joinedload(AutomationTask.target_site), joinedload(AutomationTask.channel))
        .where(AutomationTask.status.in_([TaskStatus.pending, TaskStatus.failed, TaskStatus.needs_attention]))
        .order_by(AutomationTask.created_at.desc())
        .limit(8)
    ).all()
    pending_batches = db.scalars(
        select(SubmissionBatch)
        .options(joinedload(SubmissionBatch.channel), joinedload(SubmissionBatch.items))
        .where(SubmissionBatch.status.in_([SubmissionBatchStatus.planned, SubmissionBatchStatus.partial]))
        .order_by(SubmissionBatch.scheduled_for.asc(), SubmissionBatch.id.asc())
    ).unique().all()
    return render(
        request,
        "dashboard.html",
        sites=sites,
        channels=channels,
        recent_records=recent_records,
        pending_tasks=pending_tasks,
        pending_batches=pending_batches,
    )


@router.get("/sites", response_class=HTMLResponse)
def sites_list(request: Request, db: Db, q: str = ""):
    stmt = select(TargetSite).order_by(TargetSite.name)
    if q:
        stmt = stmt.where(TargetSite.name.contains(q) | TargetSite.url.contains(q))
    return render(request, "sites/list.html", sites=db.scalars(stmt).all(), q=q)


@router.get("/sites/new", response_class=HTMLResponse)
def site_new(request: Request):
    return render(request, "sites/form.html", site=None)


@router.post("/sites")
def site_create(db: Db, name: Annotated[str, Form()], url: Annotated[str, Form()], notes: Annotated[str, Form()] = ""):
    site = TargetSite(name=name.strip(), url=url.strip(), notes=notes.strip() or None)
    db.add(site)
    db.commit()
    return redirect("/sites", "目标网站已创建")


@router.get("/sites/{site_id}/edit", response_class=HTMLResponse)
def site_edit(request: Request, site_id: int, db: Db):
    return render(request, "sites/form.html", site=get_or_404(db, TargetSite, site_id))


@router.post("/sites/{site_id}")
def site_update(site_id: int, db: Db, name: Annotated[str, Form()], url: Annotated[str, Form()], notes: Annotated[str, Form()] = ""):
    site = get_or_404(db, TargetSite, site_id)
    site.name, site.url, site.notes = name.strip(), url.strip(), notes.strip() or None
    db.commit()
    return redirect("/sites", "目标网站已更新")


@router.post("/sites/{site_id}/delete")
def site_delete(site_id: int, db: Db):
    db.delete(get_or_404(db, TargetSite, site_id))
    db.commit()
    return redirect("/sites", "目标网站及其关联数据已删除")


@router.get("/channels", response_class=HTMLResponse)
def channels_list(request: Request, db: Db, q: str = "", channel_type: str = "", status: str = ""):
    stmt = select(Channel).options(joinedload(Channel.credential)).order_by(Channel.name)
    if q:
        stmt = stmt.where(Channel.name.contains(q) | Channel.url.contains(q))
    if channel_type:
        stmt = stmt.where(Channel.channel_type == ChannelType(channel_type))
    if status:
        stmt = stmt.where(Channel.status == ChannelStatus(status))
    channels = db.scalars(stmt).unique().all()
    blacklisted_channel_ids = {channel.id for channel in channels if is_channel_blacklisted(db, channel)}
    return render(
        request,
        "channels/list.html",
        channels=channels,
        blacklist=db.scalars(select(ChannelBlacklist).order_by(ChannelBlacklist.domain)).all(),
        blacklisted_channel_ids=blacklisted_channel_ids,
        q=q,
        selected_type=channel_type,
        selected_status=status,
    )


@router.get("/channels/new", response_class=HTMLResponse)
def channel_new(request: Request):
    return render(request, "channels/form.html", channel=None)


def apply_channel_form(channel: Channel, name: str, url: str, channel_type: str, status: str, supports_automation: str | None, adapter_key: str, adapter_config: str, notes: str, requires_login: str | None = None, channel_type_other: str = "", login_username: str = "", login_password: str = "", link_type: str = "", dr_value: str = "", monthly_traffic: str = "") -> None:
    if adapter_config.strip():
        try:
            json.loads(adapter_config)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, f"适配器配置不是合法 JSON: {exc.msg}") from exc
    channel.name = name.strip()
    channel.url = url.strip()
    channel.channel_type = ChannelType(channel_type)
    channel.channel_type_other = channel_type_other.strip() if channel.channel_type == ChannelType.other else None
    if channel.channel_type == ChannelType.other and not channel.channel_type_other:
        raise HTTPException(422, "选择「其它」类型时必须填写自定义类型名称")
    channel.status = ChannelStatus(status)
    channel.requires_login = requires_login == "on"
    channel.login_username = login_username.strip() or None
    channel.login_password = login_password.strip() or None
    channel.link_type = LinkType(link_type) if link_type else None
    channel.dr_value = optional_positive_int(dr_value, "DR 数值")
    channel.monthly_traffic = optional_positive_int(monthly_traffic, "月度流量")
    channel.supports_automation = supports_automation == "on"
    channel.adapter_key = adapter_key.strip() or None
    channel.adapter_config = adapter_config.strip() or None
    channel.notes = notes.strip() or None


@router.post("/channels")
def channel_create(
    db: Db,
    name: Annotated[str, Form()],
    url: Annotated[str, Form()],
    channel_type: Annotated[str, Form()],
    status: Annotated[str, Form()],
    supports_automation: Annotated[str | None, Form()] = None,
    adapter_key: Annotated[str, Form()] = "",
    adapter_config: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    requires_login: Annotated[str | None, Form()] = None,
    channel_type_other: Annotated[str, Form()] = "",
    login_username: Annotated[str, Form()] = "",
    login_password: Annotated[str, Form()] = "",
    link_type: Annotated[str, Form()] = "",
    dr_value: Annotated[str, Form()] = "",
    monthly_traffic: Annotated[str, Form()] = "",
):
    channel = Channel(name="", url="", channel_type=ChannelType.forum)
    apply_channel_form(channel, name, url, channel_type, status, supports_automation, adapter_key, adapter_config, notes, requires_login, channel_type_other, login_username, login_password, link_type, dr_value, monthly_traffic)
    reject_blacklisted_channel(db, channel)
    db.add(channel)
    db.commit()
    return redirect("/channels", "外链渠道已创建")


@router.get("/channels/{channel_id}", response_class=HTMLResponse)
def channel_detail(request: Request, channel_id: int, db: Db):
    channel = db.scalar(
        select(Channel).options(joinedload(Channel.credential)).where(Channel.id == channel_id)
    )
    if channel is None:
        raise HTTPException(404, "渠道不存在")
    batches = db.scalars(
        select(SubmissionBatch)
        .options(joinedload(SubmissionBatch.items))
        .where(SubmissionBatch.channel_id == channel_id)
        .order_by(SubmissionBatch.scheduled_for.desc(), SubmissionBatch.id.desc())
        .limit(10)
    ).unique().all()
    return render(request, "channels/detail.html", channel=channel, batches=batches)


@router.get("/channels/{channel_id}/edit", response_class=HTMLResponse)
def channel_edit(request: Request, channel_id: int, db: Db):
    return render(request, "channels/form.html", channel=get_or_404(db, Channel, channel_id))


@router.post("/channels/{channel_id}")
def channel_update(
    channel_id: int,
    db: Db,
    name: Annotated[str, Form()],
    url: Annotated[str, Form()],
    channel_type: Annotated[str, Form()],
    status: Annotated[str, Form()],
    supports_automation: Annotated[str | None, Form()] = None,
    adapter_key: Annotated[str, Form()] = "",
    adapter_config: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    requires_login: Annotated[str | None, Form()] = None,
    channel_type_other: Annotated[str, Form()] = "",
    login_username: Annotated[str, Form()] = "",
    login_password: Annotated[str, Form()] = "",
):
    channel = get_or_404(db, Channel, channel_id)
    apply_channel_form(channel, name, url, channel_type, status, supports_automation, adapter_key, adapter_config, notes, requires_login, channel_type_other, login_username, login_password)
    reject_blacklisted_channel(db, channel)
    db.commit()
    return redirect(f"/channels/{channel_id}", "渠道已更新")


@router.post("/channels/{channel_id}/delete")
def channel_delete(channel_id: int, db: Db):
    db.delete(get_or_404(db, Channel, channel_id))
    db.commit()
    return redirect("/channels", "渠道及其关联数据已删除")


@router.post("/channels/{channel_id}/credential")
def credential_save(
    channel_id: int,
    db: Db,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
):
    channel = get_or_404(db, Channel, channel_id)
    credential = channel.credential or ChannelCredential(channel=channel)
    cipher = CredentialCipher()
    credential.username = username.strip() or None
    if password:
        credential.encrypted_password = cipher.encrypt(password)
    if api_key:
        credential.encrypted_extra_fields = cipher.encrypt_json({"api_key": api_key})
    db.add(credential)
    db.commit()
    return redirect(f"/channels/{channel_id}", "凭据已加密保存")


@router.post("/channels/{channel_id}/credential/delete")
def credential_delete(channel_id: int, db: Db):
    channel = get_or_404(db, Channel, channel_id)
    if channel.credential:
        db.delete(channel.credential)
        db.commit()
    return redirect(f"/channels/{channel_id}", "凭据已删除")


@router.post("/channel-blacklist/import")
def channel_blacklist_import(
    db: Db,
    entries: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
):
    added = 0
    skipped = 0
    errors: list[str] = []
    existing = set(db.scalars(select(ChannelBlacklist.domain)).all())
    for line_number, raw_value in enumerate(entries.splitlines(), start=1):
        if not raw_value.strip():
            continue
        try:
            domain = normalize_blacklist_domain(raw_value)
        except ValueError as exc:
            errors.append(f"第 {line_number} 行：{exc}")
            continue
        if domain in existing:
            skipped += 1
            continue
        db.add(ChannelBlacklist(domain=domain, notes=notes.strip() or None))
        existing.add(domain)
        added += 1
    db.commit()
    message = f"黑名单新增 {added} 条，跳过重复 {skipped} 条"
    if errors:
        message += f"，无效 {len(errors)} 条：{'；'.join(errors[:3])}"
    return redirect("/channels", message)


@router.post("/channel-blacklist/{entry_id}/update")
def channel_blacklist_update(
    entry_id: int,
    db: Db,
    domain: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
):
    entry = get_or_404(db, ChannelBlacklist, entry_id)
    try:
        entry.domain = normalize_blacklist_domain(domain)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    duplicate = db.scalar(select(ChannelBlacklist).where(
        ChannelBlacklist.domain == entry.domain,
        ChannelBlacklist.id != entry.id,
    ))
    if duplicate:
        raise HTTPException(422, "该域名已存在于黑名单")
    entry.notes = notes.strip() or None
    db.commit()
    return redirect("/channels", "黑名单已更新")


@router.post("/channel-blacklist/{entry_id}/delete")
def channel_blacklist_delete(entry_id: int, db: Db):
    db.delete(get_or_404(db, ChannelBlacklist, entry_id))
    db.commit()
    return redirect("/channels", "黑名单条目已删除")


def submission_batch_or_404(db: Session, batch_id: int) -> SubmissionBatch:
    batch = db.execute(
        select(SubmissionBatch)
        .options(
            joinedload(SubmissionBatch.channel),
            joinedload(SubmissionBatch.items).joinedload(SubmissionBatchItem.target_site),
            joinedload(SubmissionBatch.items).joinedload(SubmissionBatchItem.record),
        )
        .where(SubmissionBatch.id == batch_id)
    ).unique().scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, "提交批次不存在")
    return batch


def refresh_submission_batch_status(batch: SubmissionBatch) -> None:
    planned = sum(item.status == SubmissionItemStatus.planned for item in batch.items)
    completed = sum(item.status == SubmissionItemStatus.completed for item in batch.items)
    if planned:
        batch.status = SubmissionBatchStatus.partial if completed else SubmissionBatchStatus.planned
        batch.completed_at = None
    else:
        batch.status = SubmissionBatchStatus.completed if completed else SubmissionBatchStatus.cancelled
        batch.completed_at = batch.completed_at or now_local()


def complete_submission_items(
    db: Session,
    batch: SubmissionBatch,
    item_ids: list[int],
    actual_url: str,
    anchor_text: str,
    published_at: date,
    record_status: RecordStatus,
) -> int:
    actual_url = actual_url.strip()
    if not actual_url:
        raise HTTPException(422, "完成提交时必须填写统一查看地址")
    selected_ids = set(item_ids)
    selected_items = [
        item for item in batch.items
        if item.id in selected_ids and item.status == SubmissionItemStatus.planned
    ]
    if not selected_items:
        raise HTTPException(422, "请至少选择一个尚未完成的网站")
    if len(selected_items) != len(selected_ids):
        raise HTTPException(422, "选择中包含无效或已经处理的网站")
    for item in selected_items:
        record = BacklinkRecord(
            target_site_id=item.target_site_id,
            channel_id=batch.channel_id,
            actual_url=actual_url,
            anchor_text=anchor_text.strip(),
            published_at=published_at,
            method=PublishMethod.manual,
            status=record_status,
        )
        db.add(record)
        db.flush()
        item.record_id = record.id
        item.status = SubmissionItemStatus.completed
        item.completed_at = now_local()
    batch.shared_url = actual_url
    batch.anchor_text = anchor_text.strip() or None
    batch.record_status = record_status
    refresh_submission_batch_status(batch)
    return len(selected_items)


def latest_live_dates_for_channel(db: Session, channel_id: int) -> dict[int, date]:
    records = db.scalars(
        select(BacklinkRecord)
        .where(BacklinkRecord.channel_id == channel_id, BacklinkRecord.status == RecordStatus.live)
        .order_by(BacklinkRecord.published_at.desc(), BacklinkRecord.id.desc())
    ).all()
    result: dict[int, date] = {}
    for record in records:
        result.setdefault(record.target_site_id, record.published_at)
    return result


@router.get("/submission-batches", response_class=HTMLResponse)
def submission_batches_list(request: Request, db: Db, channel_id: str = "", status: str = ""):
    selected_channel_id = optional_int(channel_id, "外链渠道")
    stmt = select(SubmissionBatch).options(
        joinedload(SubmissionBatch.channel), joinedload(SubmissionBatch.items)
    )
    if selected_channel_id:
        stmt = stmt.where(SubmissionBatch.channel_id == selected_channel_id)
    if status:
        stmt = stmt.where(SubmissionBatch.status == SubmissionBatchStatus(status))
    stmt = stmt.order_by(SubmissionBatch.scheduled_for.desc(), SubmissionBatch.id.desc())
    return render(
        request,
        "submission_batches/list.html",
        batches=db.scalars(stmt).unique().all(),
        channels=available_channels(db),
        selected_channel_id=selected_channel_id,
        selected_status=status,
    )


@router.get("/submission-batches/new", response_class=HTMLResponse)
def submission_batch_new(request: Request, db: Db, channel_id: str = ""):
    selected_channel_id = optional_int(channel_id, "外链渠道")
    channel = get_or_404(db, Channel, selected_channel_id) if selected_channel_id else None
    if channel:
        reject_blacklisted_channel(db, channel)
    return render(
        request,
        "submission_batches/form.html",
        channels=available_channels(db),
        selected_channel_id=selected_channel_id,
        sites=db.scalars(select(TargetSite).order_by(TargetSite.name)).all(),
        duplicate_dates=latest_live_dates_for_channel(db, selected_channel_id) if selected_channel_id else {},
        today=date.today().isoformat(),
    )


@router.get("/submission-batches/site-options", response_class=HTMLResponse)
def submission_batch_site_options(request: Request, db: Db, channel_id: str = ""):
    selected_channel_id = optional_int(channel_id, "外链渠道")
    return render(
        request,
        "submission_batches/_site_options.html",
        sites=db.scalars(select(TargetSite).order_by(TargetSite.name)).all(),
        duplicate_dates=latest_live_dates_for_channel(db, selected_channel_id) if selected_channel_id else {},
    )


@router.post("/submission-batches")
def submission_batch_create(
    db: Db,
    channel_id: Annotated[int, Form()],
    target_site_ids: Annotated[list[int], Form()],
    scheduled_for: Annotated[date, Form()],
    submit_action: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    shared_url: Annotated[str, Form()] = "",
    anchor_text: Annotated[str, Form()] = "",
    record_status: Annotated[str, Form()] = "live",
    notes: Annotated[str, Form()] = "",
):
    channel = get_or_404(db, Channel, channel_id)
    reject_blacklisted_channel(db, channel)
    site_ids = list(dict.fromkeys(target_site_ids))
    sites = db.scalars(select(TargetSite).where(TargetSite.id.in_(site_ids))).all()
    if not site_ids or len(sites) != len(site_ids):
        raise HTTPException(422, "请选择有效的目标网站")
    if submit_action not in {"plan", "complete"}:
        raise HTTPException(422, "未知的保存方式")
    parsed_record_status = RecordStatus(record_status)
    if parsed_record_status == RecordStatus.removed:
        raise HTTPException(422, "新批次不能登记为已失效")
    batch = SubmissionBatch(
        channel_id=channel_id,
        title=title.strip() or None,
        scheduled_for=scheduled_for,
        shared_url=shared_url.strip() or None,
        anchor_text=anchor_text.strip() or None,
        record_status=parsed_record_status,
        notes=notes.strip() or None,
    )
    db.add(batch)
    db.flush()
    items: list[SubmissionBatchItem] = []
    for site_id in site_ids:
        item = SubmissionBatchItem(batch=batch, target_site_id=site_id)
        db.add(item)
        items.append(item)
    db.flush()
    if submit_action == "complete":
        complete_submission_items(
            db,
            batch,
            [item.id for item in items],
            shared_url,
            anchor_text,
            scheduled_for,
            parsed_record_status,
        )
    db.commit()
    message = "批量发布记录已生成" if submit_action == "complete" else "提交计划已创建"
    return redirect(f"/submission-batches/{batch.id}", message)


@router.get("/submission-batches/{batch_id}", response_class=HTMLResponse)
def submission_batch_detail(request: Request, batch_id: int, db: Db):
    batch = submission_batch_or_404(db, batch_id)
    return render(request, "submission_batches/detail.html", batch=batch, today=date.today().isoformat())


@router.post("/submission-batches/{batch_id}")
def submission_batch_update(
    batch_id: int,
    db: Db,
    scheduled_for: Annotated[date, Form()],
    title: Annotated[str, Form()] = "",
    shared_url: Annotated[str, Form()] = "",
    anchor_text: Annotated[str, Form()] = "",
    record_status: Annotated[str, Form()] = "live",
    notes: Annotated[str, Form()] = "",
):
    batch = submission_batch_or_404(db, batch_id)
    if not any(item.status == SubmissionItemStatus.planned for item in batch.items):
        raise HTTPException(422, "该批次已经结束，不能再修改计划信息")
    batch.title = title.strip() or None
    batch.scheduled_for = scheduled_for
    batch.shared_url = shared_url.strip() or None
    batch.anchor_text = anchor_text.strip() or None
    parsed_record_status = RecordStatus(record_status)
    if parsed_record_status == RecordStatus.removed:
        raise HTTPException(422, "提交计划不能预设为已失效")
    batch.record_status = parsed_record_status
    batch.notes = notes.strip() or None
    db.commit()
    return redirect(f"/submission-batches/{batch_id}", "提交计划已更新")


@router.post("/submission-batches/{batch_id}/complete")
def submission_batch_complete(
    batch_id: int,
    db: Db,
    item_ids: Annotated[list[int], Form()],
    actual_url: Annotated[str, Form()],
    anchor_text: Annotated[str, Form()],
    published_at: Annotated[date, Form()],
    record_status: Annotated[str, Form()] = "live",
):
    batch = submission_batch_or_404(db, batch_id)
    reject_blacklisted_channel(db, batch.channel)
    parsed_record_status = RecordStatus(record_status)
    if parsed_record_status == RecordStatus.removed:
        raise HTTPException(422, "完成提交不能直接登记为已失效")
    completed = complete_submission_items(
        db, batch, item_ids, actual_url, anchor_text, published_at, parsed_record_status
    )
    db.commit()
    return redirect(f"/submission-batches/{batch_id}", f"已完成 {completed} 个网站并生成发布记录")


@router.post("/submission-batches/{batch_id}/cancel-remaining")
def submission_batch_cancel_remaining(batch_id: int, db: Db):
    batch = submission_batch_or_404(db, batch_id)
    cancelled = 0
    for item in batch.items:
        if item.status == SubmissionItemStatus.planned:
            item.status = SubmissionItemStatus.cancelled
            cancelled += 1
    if not cancelled:
        raise HTTPException(422, "该批次没有待取消的网站")
    refresh_submission_batch_status(batch)
    db.commit()
    return redirect(f"/submission-batches/{batch_id}", f"已取消剩余 {cancelled} 个计划")


@router.post("/submission-batches/{batch_id}/delete")
def submission_batch_delete(batch_id: int, db: Db):
    batch = submission_batch_or_404(db, batch_id)
    db.delete(batch)
    db.commit()
    return redirect("/submission-batches", "提交批次已删除；已经生成的正式发布记录仍然保留")


@router.get("/records", response_class=HTMLResponse)
def records_list(
    request: Request,
    db: Db,
    target_site_id: str = "",
    channel_id: str = "",
    status: str = "",
    method: str = "",
):
    selected_site_id = optional_int(target_site_id, "目标网站")
    selected_channel_id = optional_int(channel_id, "外链渠道")
    stmt = select(BacklinkRecord).options(
        joinedload(BacklinkRecord.target_site),
        joinedload(BacklinkRecord.channel),
        joinedload(BacklinkRecord.submission_item),
    )
    if selected_site_id:
        stmt = stmt.where(BacklinkRecord.target_site_id == selected_site_id)
    if selected_channel_id:
        stmt = stmt.where(BacklinkRecord.channel_id == selected_channel_id)
    if status:
        stmt = stmt.where(BacklinkRecord.status == RecordStatus(status))
    if method:
        stmt = stmt.where(BacklinkRecord.method == PublishMethod(method))
    stmt = stmt.order_by(BacklinkRecord.published_at.desc(), BacklinkRecord.id.desc())
    return render(
        request,
        "records/list.html",
        records=db.scalars(stmt).all(),
        sites=db.scalars(select(TargetSite).order_by(TargetSite.name)).all(),
        channels=available_channels(db),
        selected_site_id=selected_site_id,
        selected_channel_id=selected_channel_id,
        selected_status=status,
        selected_method=method,
    )


@router.get("/records/new", response_class=HTMLResponse)
def record_new(request: Request, db: Db, target_site_id: str = "", channel_id: str = ""):
    return render(
        request,
        "records/form.html",
        record=None,
        sites=db.scalars(select(TargetSite).order_by(TargetSite.name)).all(),
        channels=available_channels(db),
        selected_site_id=optional_int(target_site_id, "目标网站"),
        selected_channel_id=optional_int(channel_id, "外链渠道"),
        today=date.today().isoformat(),
    )


@router.get("/records/duplicate-check", response_class=HTMLResponse)
def duplicate_check(request: Request, db: Db, target_site_id: str = "", channel_id: str = "", exclude_id: str = ""):
    target_site = optional_int(target_site_id, "目标网站")
    channel = optional_int(channel_id, "外链渠道")
    excluded = optional_int(exclude_id, "排除记录")
    if not target_site or not channel:
        return HTMLResponse("")
    stmt = select(BacklinkRecord).where(
        BacklinkRecord.target_site_id == target_site,
        BacklinkRecord.channel_id == channel,
        BacklinkRecord.status == RecordStatus.live,
    ).order_by(BacklinkRecord.published_at.desc())
    if excluded:
        stmt = stmt.where(BacklinkRecord.id != excluded)
    existing = db.scalar(stmt)
    return render(request, "records/_duplicate_warning.html", existing=existing)


@router.post("/records")
def record_create(
    db: Db,
    target_site_id: Annotated[int, Form()],
    channel_id: Annotated[int, Form()],
    actual_url: Annotated[str, Form()],
    anchor_text: Annotated[str, Form()],
    published_at: Annotated[date, Form()],
    method: Annotated[str, Form()],
    status: Annotated[str, Form()],
):
    get_or_404(db, TargetSite, target_site_id)
    channel = get_or_404(db, Channel, channel_id)
    reject_blacklisted_channel(db, channel)
    db.add(BacklinkRecord(
        target_site_id=target_site_id,
        channel_id=channel_id,
        actual_url=actual_url.strip(),
        anchor_text=anchor_text.strip(),
        published_at=published_at,
        method=PublishMethod(method),
        status=RecordStatus(status),
    ))
    db.commit()
    return redirect("/records", "发布记录已登记")


@router.get("/records/{record_id}/edit", response_class=HTMLResponse)
def record_edit(request: Request, record_id: int, db: Db):
    return render(
        request,
        "records/form.html",
        record=get_or_404(db, BacklinkRecord, record_id),
        sites=db.scalars(select(TargetSite).order_by(TargetSite.name)).all(),
        channels=available_channels(db),
        selected_site_id=None,
        selected_channel_id=None,
        today=date.today().isoformat(),
    )


@router.post("/records/{record_id}")
def record_update(
    record_id: int,
    db: Db,
    target_site_id: Annotated[int, Form()],
    channel_id: Annotated[int, Form()],
    actual_url: Annotated[str, Form()],
    anchor_text: Annotated[str, Form()],
    published_at: Annotated[date, Form()],
    method: Annotated[str, Form()],
    status: Annotated[str, Form()],
):
    record = get_or_404(db, BacklinkRecord, record_id)
    channel = get_or_404(db, Channel, channel_id)
    reject_blacklisted_channel(db, channel)
    record.target_site_id, record.channel_id = target_site_id, channel_id
    record.actual_url, record.anchor_text, record.published_at = actual_url.strip(), anchor_text.strip(), published_at
    record.method, record.status = PublishMethod(method), RecordStatus(status)
    db.commit()
    return redirect("/records", "发布记录已更新")


@router.post("/records/{record_id}/delete")
def record_delete(record_id: int, db: Db):
    db.delete(get_or_404(db, BacklinkRecord, record_id))
    db.commit()
    return redirect("/records", "发布记录已删除")


@router.get("/tasks", response_class=HTMLResponse)
def tasks_list(request: Request, db: Db, status: str = ""):
    stmt = select(AutomationTask).options(joinedload(AutomationTask.target_site), joinedload(AutomationTask.channel))
    if status:
        stmt = stmt.where(AutomationTask.status == TaskStatus(status))
    stmt = stmt.order_by(AutomationTask.created_at.desc())
    return render(request, "tasks/list.html", tasks=db.scalars(stmt).all(), selected_status=status)


@router.get("/tasks/new", response_class=HTMLResponse)
def task_new(request: Request, db: Db):
    eligible_channels = db.scalars(
        select(Channel).where(Channel.status == ChannelStatus.active, Channel.supports_automation.is_(True)).order_by(Channel.name)
    ).all()
    eligible_channels = [channel for channel in eligible_channels if not is_channel_blacklisted(db, channel)]
    return render(
        request,
        "tasks/form.html",
        sites=db.scalars(select(TargetSite).order_by(TargetSite.name)).all(),
        channels=eligible_channels,
        default_retries=get_settings().automation_max_retries,
    )


@router.post("/tasks")
def task_create(
    db: Db,
    target_site_id: Annotated[int, Form()],
    channel_id: Annotated[int, Form()],
    anchor_text: Annotated[str, Form()],
    max_retries: Annotated[int, Form()],
):
    get_or_404(db, TargetSite, target_site_id)
    channel = get_or_404(db, Channel, channel_id)
    reject_blacklisted_channel(db, channel)
    if channel.status != ChannelStatus.active or not channel.supports_automation:
        raise HTTPException(422, "只能为状态正常且支持自动化的渠道创建任务")
    db.add(AutomationTask(
        target_site_id=target_site_id,
        channel_id=channel_id,
        anchor_text=anchor_text.strip(),
        max_retries=max(0, min(max_retries, 20)),
    ))
    db.commit()
    return redirect("/tasks", "自动发布任务已创建，将由调度器执行")


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: int, db: Db):
    task = db.execute(
        select(AutomationTask)
        .options(joinedload(AutomationTask.target_site), joinedload(AutomationTask.channel), joinedload(AutomationTask.logs))
        .where(AutomationTask.id == task_id)
    ).unique().scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "任务不存在")
    return render(request, "tasks/detail.html", task=task)


@router.post("/tasks/{task_id}/retry")
def task_retry(task_id: int, db: Db):
    task = get_or_404(db, AutomationTask, task_id)
    if task.status not in (TaskStatus.failed, TaskStatus.needs_attention):
        raise HTTPException(422, "只有失败或需人工介入的任务可以重试")
    task.status = TaskStatus.pending
    task.retry_count = 0
    task.last_error = None
    db.commit()
    return redirect(f"/tasks/{task_id}", "任务已重置，等待调度器重试")


@router.post("/tasks/{task_id}/run")
async def task_run_now(task_id: int, db: Db):
    from .automation.engine import execute_task

    task = get_or_404(db, AutomationTask, task_id)
    if task.status in (TaskStatus.running, TaskStatus.success):
        raise HTTPException(422, "当前任务不可执行")
    task.status = TaskStatus.pending
    db.commit()
    await execute_task(task.id)
    return redirect(f"/tasks/{task_id}", "任务已执行，请查看最新状态与日志")
