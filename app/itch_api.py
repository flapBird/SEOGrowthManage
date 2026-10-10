"""PlayBloo 等游戏聚合站的回写接口：聚合站批量建页后，把对应游戏标记为「已用于 PlayBloo」。

鉴权：环境变量 ITCH_RADAR_API_KEY 配置静态密钥；请求携带 X-API-Key 头（或
Authorization: Bearer <key>）。服务端未配置密钥时整个接口返回 403 不可用，
不影响 /itch 页面的正常使用。

用法：
    POST /api/itch/mark-used
    X-API-Key: <key>
    {"date": "2026-10-07"}                                    # 标记当日全部游戏
    {"date": "2026-10-07", "urls": ["https://x.itch.io/a"]}   # 标记当日中指定的游戏
    {"urls": ["https://x.itch.io/a", ...]}                    # 按 URL 标记（不限日期）

返回 {"marked": <新标记数量>, "not_found": [...]}（not_found 仅在传 urls 时返回）。
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
