"""PlayBloo 等游戏聚合站的对接接口：外部 skill/程序可以拉取每日游戏清单，
并在建页完成后把游戏标记为「已用于 PlayBloo」，全程无需人工在页面上操作。

鉴权：环境变量 ITCH_RADAR_API_KEY 配置静态密钥；请求携带 X-API-Key 头（或
Authorization: Bearer <key>）。服务端未配置密钥时整个接口返回 403 不可用，
不影响 /itch 页面的正常使用。

两个端点：
    GET  /api/itch/games?date=YYYY-MM-DD&status=ready&limit=300
         按收录日拉取游戏清单（字段含 URL/标题/简介/标签/关键词/质量结论），
         供 skill 挑选游戏、生成 PlayBloo 页面。
    POST /api/itch/mark-used
         {"date": "..."} / {"urls": [...]} / {"date": "...", "urls": [...]}
         把对应游戏标记为已用；返回 {"marked": n, "not_found": [...]}。

典型 skill 流程：GET games(status=ready) → 挑选并建页 → POST mark-used(urls=...)。
"""
from __future__ import annotations

import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .itch_radar.parse import normalize_game_url
from .itch_web import _day_expression
from .models import ItchGame, ItchGameStatus


router = APIRouter(prefix="/api/itch")
Db = Annotated[Session, Depends(get_db)]


class MarkUsedPayload(BaseModel):
    date: str | None = None
    urls: list[str] = []


def _verify_key(
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    settings = get_settings()
    if not settings.itch_radar_api_key:
        raise HTTPException(403, "服务端未配置 ITCH_RADAR_API_KEY，回写接口不可用")
    provided = x_api_key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization.strip()[len("bearer "):].strip()
    if not provided or not secrets.compare_digest(provided, settings.itch_radar_api_key):
        raise HTTPException(401, "API Key 无效")


@router.get("/games", dependencies=[Depends(_verify_key)])
def list_games(db: Db, date: str = "", status: str = "", limit: int = 300):
    """按日期拉取收录的游戏清单（供外部 skill 程序化取用，替代人工导出 Markdown）。

    date 缺省为今天（东八区）；status 可选 new/ready/used/skipped；limit 上限 300。
    """
    from .itch_web import _day_query, _parse_day, STATUS_LABELS

    day = _parse_day(date)
    selected = status if status in [s.value for s in ItchGameStatus] else ""
    games = _day_query(db, day, selected, "")
    payload = []
    for game in games[: max(0, min(limit, 300))]:
        payload.append({
            "id": game.id,
            "url": game.url,
            "title": game.title,
            "author": game.author,
            "cover_url": game.cover_url,
            "description": game.description,
            "price": game.price,
            "status": game.status.value,
            "status_label": STATUS_LABELS[game.status],
            "itch_published_at": game.itch_published_at.strftime("%Y-%m-%d %H:%M") if game.itch_published_at else None,
            "discovered_at": game.discovered_at.strftime("%Y-%m-%d %H:%M"),
            "genres": game.genres,
            "tags": game.tags,
            "platforms": game.platforms,
            "screenshots": game.screenshots,
            "keywords": game.keywords,
            "quality_ok": game.quality_ok,
            "quality_notes": game.quality_notes,
        })
    return {"date": day.isoformat(), "count": len(payload), "games": payload}


@router.post("/mark-used", dependencies=[Depends(_verify_key)])
def mark_used(payload: MarkUsedPayload, db: Db):
    if not payload.date and not payload.urls:
        raise HTTPException(422, "请提供 date（标记当日全部游戏）或 urls（标记指定游戏），也可两者同时提供")

    day: date | None = None
    if payload.date:
        try:
            day = date.fromisoformat(payload.date.strip())
        except ValueError as exc:
            raise HTTPException(422, f"date 格式应为 YYYY-MM-DD，收到 {payload.date!r}") from exc

    normalized: list[str] = []
    stmt = select(ItchGame)
    if payload.urls:
        normalized = [u for u in (normalize_game_url(u) for u in payload.urls) if u]
        if not normalized:
            raise HTTPException(422, "urls 全部为空或无法解析")
        stmt = stmt.where(ItchGame.url.in_(normalized))
    if day is not None:
        stmt = stmt.where(_day_expression() == day.isoformat())

    games = db.scalars(stmt).all()
    changed = 0
    for game in games:
        if game.status != ItchGameStatus.used:
            game.status = ItchGameStatus.used
            changed += 1
    db.commit()

    result: dict = {"marked": changed}
    if payload.urls:
        found = {game.url for game in games}
        result["not_found"] = [u for u in normalized if u not in found]
    return result
