from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .database import get_db
from .keyword_discovery.pipeline import enrich_candidate, ingest_entries, run_source
from .keyword_discovery.notify import notify, notify_one
from .keyword_discovery.serpapi import SerpApiClient
from .keyword_discovery.sources import SourceEntry
from .models import KeywordCandidate, KeywordCandidateStatus, KeywordFetchRun, KeywordSource, KeywordSourceType, NotifyChannel, NotifyChannelType, SerpApiPool
from .security import CredentialCipher, require_auth
from .web import get_or_404, redirect, render


router = APIRouter(dependencies=[Depends(require_auth)])
Db = Annotated[Session, Depends(get_db)]


@router.get("/keywords", response_class=HTMLResponse)
def keyword_list(request: Request, db: Db, q: str = "", status: str = ""):
    stmt = select(KeywordCandidate).order_by(KeywordCandidate.total_score.desc(), KeywordCandidate.first_seen_at.desc())
    if q:
        stmt = stmt.where(KeywordCandidate.keyword.contains(q))
    if status:
        stmt = stmt.where(KeywordCandidate.status == KeywordCandidateStatus(status))
    return render(request, "keywords/list.html", candidates=db.scalars(stmt.limit(500)).all(), q=q, selected_status=status)


@router.get("/keywords/{candidate_id}", response_class=HTMLResponse)
def keyword_detail(request: Request, candidate_id: int, db: Db):
    candidate = db.execute(
        select(KeywordCandidate).options(joinedload(KeywordCandidate.signals)).where(KeywordCandidate.id == candidate_id)
    ).unique().scalar_one_or_none()
    if candidate is None:
        raise HTTPException(404, "关键词候选不存在")
    return render(request, "keywords/detail.html", candidate=candidate)


@router.post("/keywords/{candidate_id}/status")
def keyword_status(candidate_id: int, db: Db, status: Annotated[str, Form()], reason: Annotated[str, Form()] = ""):
    candidate = get_or_404(db, KeywordCandidate, candidate_id)
    candidate.status = KeywordCandidateStatus(status)
    candidate.decision_reason = reason.strip() or "管理员人工调整"
    candidate.next_review_at = None
    candidate.ignored_until = None
    db.commit()
    return redirect(f"/keywords/{candidate_id}", "候选状态已更新")


@router.post("/keywords/{candidate_id}/enrich")
async def keyword_enrich(candidate_id: int, db: Db):
    candidate = get_or_404(db, KeywordCandidate, candidate_id)
    try:
        calls, _became_hot = await enrich_candidate(db, candidate)
        return redirect(f"/keywords/{candidate_id}", f"信号分析完成，使用 {calls} 次 SerpAPI 查询")
    except Exception as exc:
        return redirect(f"/keywords/{candidate_id}", f"分析失败: {type(exc).__name__}: {exc}")


@router.get("/keyword-sources", response_class=HTMLResponse)
def source_list(request: Request, db: Db):
    sources = db.scalars(select(KeywordSource).order_by(KeywordSource.created_at.desc())).all()
    runs = db.scalars(select(KeywordFetchRun).options(joinedload(KeywordFetchRun.source)).order_by(KeywordFetchRun.started_at.desc()).limit(30)).all()
    return render(request, "keywords/sources.html", sources=sources, runs=runs)


def _validate_source_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(422, "来源 URL 必须是有效的 HTTP/HTTPS 地址")


@router.post("/keyword-sources")
def source_create(
    db: Db, name: Annotated[str, Form()], source_type: Annotated[str, Form()], url: Annotated[str, Form()],
    language: Annotated[str, Form()] = "en", country: Annotated[str, Form()] = "US",
    interval_minutes: Annotated[int, Form()] = 360, terms_confirmed: Annotated[str | None, Form()] = None,
    config_json: Annotated[str, Form()] = "",
):
    if terms_confirmed != "on":
        raise HTTPException(422, "必须确认该来源允许自动访问")
    _validate_source_url(url.strip())
    if config_json.strip():
        try:
            json.loads(config_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, f"来源配置不是合法 JSON: {exc.msg}") from exc
    db.add(KeywordSource(
        name=name.strip(), source_type=KeywordSourceType(source_type), url=url.strip(), enabled=True,
        terms_confirmed=True, language=language.strip() or "en", country=country.strip().upper() or "US",
        interval_minutes=max(15, min(interval_minutes, 10080)), config_json=config_json.strip() or None,
    ))
    db.commit()
    return redirect("/keyword-sources", "关键词来源已创建")


@router.post("/keyword-sources/{source_id}/run")
async def source_run(source_id: int, db: Db):
    get_or_404(db, KeywordSource, source_id)
    await run_source(source_id)
    return redirect("/keyword-sources", "来源抓取完成，请查看运行日志")


@router.post("/keyword-sources/{source_id}/toggle")
def source_toggle(source_id: int, db: Db):
    source = get_or_404(db, KeywordSource, source_id)
    source.enabled = not source.enabled
    db.commit()
    return redirect("/keyword-sources", "来源状态已更新")


@router.post("/keyword-sources/{source_id}/delete")
def source_delete(source_id: int, db: Db):
    db.delete(get_or_404(db, KeywordSource, source_id))
    db.commit()
    return redirect("/keyword-sources", "来源及抓取历史已删除，候选历史仍保留")


@router.post("/keywords/manual-import")
def manual_import(db: Db, keywords: Annotated[str, Form()], language: Annotated[str, Form()] = "en"):
    source = db.scalar(select(KeywordSource).where(KeywordSource.source_type == KeywordSourceType.manual, KeywordSource.name == "人工导入"))
    if source is None:
        source = KeywordSource(name="人工导入", source_type=KeywordSourceType.manual, enabled=True, terms_confirmed=True, language=language.strip() or "en", interval_minutes=10080)
        db.add(source)
        db.commit()
    entries = [SourceEntry(line.strip()) for line in keywords.splitlines() if line.strip()]
    discovered, new_candidates = ingest_entries(db, source, entries)
    return redirect("/keywords", f"导入 {discovered} 个新条目，生成 {new_candidates} 个新候选")


@router.get("/serpapi-pools", response_class=HTMLResponse)
def pool_list(request: Request, db: Db):
    pools = db.scalars(select(SerpApiPool).order_by(SerpApiPool.priority, SerpApiPool.name)).all()
    return render(request, "keywords/pools.html", pools=pools, daily_budget=get_settings().keyword_serpapi_daily_budget)


@router.post("/serpapi-pools")
def pool_create(db: Db, name: Annotated[str, Form()], api_key: Annotated[str, Form()], priority: Annotated[int, Form()] = 100):
    if not api_key.strip():
        raise HTTPException(422, "API Key 不能为空")
    db.add(SerpApiPool(name=name.strip(), encrypted_api_key=CredentialCipher().encrypt(api_key.strip()), priority=max(0, min(priority, 10000)), enabled=True))
    db.commit()
    return redirect("/serpapi-pools", "SerpAPI Key 已加密加入额度池")


@router.post("/serpapi-pools/{pool_id}/update")
def pool_update(pool_id: int, db: Db, name: Annotated[str, Form()], priority: Annotated[int, Form()] = 100, api_key: Annotated[str, Form()] = ""):
    pool = get_or_404(db, SerpApiPool, pool_id)
    pool.name = name.strip()
    pool.priority = max(0, min(priority, 10000))
    if api_key.strip():
        pool.encrypted_api_key = CredentialCipher().encrypt(api_key.strip())
        pool.quota_remaining = None
        pool.last_error = None
    db.commit()
    return redirect("/serpapi-pools", "额度池已更新")


@router.post("/serpapi-pools/{pool_id}/toggle")
def pool_toggle(pool_id: int, db: Db):
    pool = get_or_404(db, SerpApiPool, pool_id)
    pool.enabled = not pool.enabled
    db.commit()
    return redirect("/serpapi-pools", "额度池状态已更新")


@router.post("/serpapi-pools/{pool_id}/delete")
def pool_delete(pool_id: int, db: Db):
    db.delete(get_or_404(db, SerpApiPool, pool_id))
    db.commit()
    return redirect("/serpapi-pools", "额度池已删除")


@router.post("/serpapi-pools/refresh")
async def pools_refresh(db: Db):
    await SerpApiClient(db).refresh_all()
    return redirect("/serpapi-pools", "额度信息同步完成；Account API 查询不消耗搜索额度")


# ---------------------------------------------------------------------------
# 通知通道（关键词发现的新增/异常/HOT 推送）
# ---------------------------------------------------------------------------

def _notify_config_fields(channel_type: NotifyChannelType) -> dict[str, str]:
    """每种通道类型对应的配置字段表（键 -> 字段说明），仅用于模板渲染。"""
    if channel_type == NotifyChannelType.serverchan:
        return {"sendkey": "Server酱 SendKey（SCTxxxxx）"}
    if channel_type == NotifyChannelType.wecom_bot:
        return {"webhook": "企业微信群机器人 Webhook URL"}
    return {  # email
        "smtp_host": "SMTP 服务器（如 smtp.qq.com）",
        "smtp_port": "SMTP 端口（SSL 通常 465）",
        "smtp_user": "邮箱账号",
        "smtp_password": "邮箱授权码（非登录密码）",
        "mail_from": "发件地址",
        "mail_to": "收件地址",
    }


def _build_notify_config(channel_type: NotifyChannelType, form_fields: dict[str, str]) -> dict[str, str]:
    """按通道类型从表单字段组装配置 dict，并做必填校验。"""
    expected = _notify_config_fields(channel_type)
    config: dict[str, str] = {}
    missing: list[str] = []
    for field in expected:
        value = (form_fields.get(field) or "").strip()
        if not value:
            missing.append(field)
        config[field] = value
    if missing:
        raise HTTPException(422, f"缺少通知配置字段: {', '.join(missing)}")
    return config


@router.get("/notify-channels", response_class=HTMLResponse)
def notify_channel_list(request: Request, db: Db):
    channels = db.scalars(select(NotifyChannel).order_by(NotifyChannel.channel_type, NotifyChannel.name)).all()
    return render(
        request,
        "keywords/notify.html",
        channels=channels,
        config_fields={t: _notify_config_fields(t) for t in NotifyChannelType},
    )


async def _form_to_dict(request: Request) -> dict[str, str]:
    """把表单全部字段收集成 dict（配置字段随通道类型变化，无法在签名里静态声明）。"""
    return {key: (value if isinstance(value, str) else "") for key, value in (await request.form()).items()}


@router.post("/notify-channels")
async def notify_channel_create(
    db: Db, name: Annotated[str, Form()], channel_type: Annotated[str, Form()], request: Request,
):
    try:
        notify_type = NotifyChannelType(channel_type)
    except ValueError as exc:
        raise HTTPException(422, "不支持的通知通道类型") from exc
    form_fields = await _form_to_dict(request)
    config = _build_notify_config(notify_type, form_fields)
    db.add(NotifyChannel(
        name=name.strip(),
        channel_type=notify_type,
        config_json=CredentialCipher().encrypt_json(config),
        enabled=True,
    ))
    db.commit()
    return redirect("/notify-channels", "通知通道已加密保存")


@router.post("/notify-channels/{channel_id}/update")
async def notify_channel_update(
    channel_id: int, db: Db, name: Annotated[str, Form()], request: Request,
):
    channel = get_or_404(db, NotifyChannel, channel_id)
    channel.name = name.strip()
    # 任一配置字段非空即视为要更新；全部留空则保留原密文。
    form_fields = await _form_to_dict(request)
    expected = _notify_config_fields(channel.channel_type)
    provided = {field: (form_fields.get(field) or "").strip() for field in expected}
    if any(provided.values()):
        config = _build_notify_config(channel.channel_type, {k: v for k, v in provided.items() if v})
        channel.config_json = CredentialCipher().encrypt_json(config)
        channel.last_error = None
    db.commit()
    return redirect("/notify-channels", "通知通道已更新")


@router.post("/notify-channels/{channel_id}/toggle")
def notify_channel_toggle(channel_id: int, db: Db):
    channel = get_or_404(db, NotifyChannel, channel_id)
    channel.enabled = not channel.enabled
    db.commit()
    return redirect("/notify-channels", "通知通道状态已更新")


@router.post("/notify-channels/{channel_id}/delete")
def notify_channel_delete(channel_id: int, db: Db):
    db.delete(get_or_404(db, NotifyChannel, channel_id))
    db.commit()
    return redirect("/notify-channels", "通知通道已删除")


@router.post("/notify-channels/{channel_id}/test")
async def notify_channel_test(channel_id: int, db: Db):
    channel = get_or_404(db, NotifyChannel, channel_id)
    ok = await notify_one(channel, "关键词发现测试通知", "这是一条来自 SEO 工作台的测试消息，收到说明通道配置正确。")
    db.commit()
    return redirect("/notify-channels", "测试通知已发出" if ok else f"测试推送失败：{channel.last_error or '未知错误'}")


