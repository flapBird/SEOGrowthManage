"""itch.io 新游雷达的 Web 界面：每日新游列表、详情补全、状态流转、Markdown 导出。

页面是"发现 → 人工 → 交给外部 AI 做 PlayBloo 页面"工作流的起点：
- 默认展示今天（东八区）发现/上架的游戏；
- 每个游戏可一键导出为 Markdown（列表页整体导出，粘贴给任意 AI 即可建页）；
- 状态流转 new → ready → used/skipped 全部人工驱动，不做自动发布。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .itch_radar.fetcher import enrich_game, _make_client, run_radar_cycle
from .models import ItchGame, ItchGameStatus, now_local
from .security import require_auth
from .web import get_or_404, redirect, render


router = APIRouter(dependencies=[Depends(require_auth)])
Db = Annotated[Session, Depends(get_db)]

STATUS_LABELS: dict[str, str] = {
    ItchGameStatus.new.value: "待补全",
    ItchGameStatus.ready.value: "已就绪",
    ItchGameStatus.used.value: "已用于 PlayBloo",
    ItchGameStatus.skipped.value: "已忽略",
}


def _shanghai_now() -> datetime:
    from .itch_radar.parse import SHANGHAI

    return datetime.now(SHANGHAI)


def _parse_day(value: str) -> date:
    if value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    return _shanghai_now().date()


def _day_expression():
    """上架日（缺则发现日）作为"每日一批"的归组依据。"""
    return func.coalesce(
        func.date(ItchGame.itch_published_at), func.date(ItchGame.discovered_at)
    )


def _published_expression():
    """排序用：上架时间（缺则发现时间）。"""
    return func.coalesce(ItchGame.itch_published_at, ItchGame.discovered_at)


def _day_query(db: Session, day: date, status: str, q: str):
    stmt = select(ItchGame).where(_day_expression() == day.isoformat())
    if status:
        stmt = stmt.where(ItchGame.status == ItchGameStatus(status))
    if q:
        stmt = stmt.where(ItchGame.title.contains(q) | ItchGame.url.contains(q))
    return db.scalars(
        stmt.order_by(_published_expression().desc(), ItchGame.id.desc()).limit(300)
    ).all()


@router.get("/itch", response_class=HTMLResponse)
def itch_list(request: Request, db: Db, date: str = "", status: str = "", q: str = ""):
    day = _parse_day(date)
    selected_status = status if status in [s.value for s in ItchGameStatus] else ""
    games = _day_query(db, day, selected_status, q)
    prev_day = (day - timedelta(days=1)).isoformat()
    next_day = (day + timedelta(days=1)).isoformat()
    return render(
        request,
        "itch/list.html",
        games=games,
        day=day.isoformat(),
        prev_day=prev_day,
        next_day=next_day,
        q=q,
        selected_status=selected_status,
        status_labels=STATUS_LABELS,
        statuses=[s.value for s in ItchGameStatus],
        today=_shanghai_now().date().isoformat(),
        query_suffix=f"date={day.isoformat()}" + (f"&q={q}" if q else "") + (f"&status={selected_status}" if selected_status else ""),
    )


@router.post("/itch/run")
async def itch_run():
    summary = await run_radar_cycle()
    message = f"本轮扫描 {summary['feeds']} 个源、看到 {summary['seen']} 条，新入库 {summary['created']} 款，补全详情 {summary['enriched']} 款"
    if summary["errors"]:
        message += f"；失败 {len(summary['errors'])} 个源: {summary['errors'][0][:120]}"
    return redirect("/itch", message)


@router.post("/itch/{game_id}/detail")
async def itch_detail(game_id: int, db: Db):
    game = get_or_404(db, ItchGame, game_id)
    async with _make_client() as client:
        ok = await enrich_game(db, game, client)
    if ok:
        return redirect(f"/itch?date={game.effective_published_at.date().isoformat()}", "详情已补全")
    return redirect(
        f"/itch?date={game.effective_published_at.date().isoformat()}",
        f"详情抓取失败：{game.last_error or '未知错误'}",
    )


@router.post("/itch/{game_id}/status")
def itch_status(game_id: int, db: Db, status: Annotated[str, Form()], back: Annotated[str, Form()] = ""):
    game = get_or_404(db, ItchGame, game_id)
    if status not in [s.value for s in ItchGameStatus]:
        raise HTTPException(422, "未知的游戏状态")
    game.status = ItchGameStatus(status)
    db.commit()
    target = f"/itch?{back}" if back else "/itch"
    return redirect(target, f"《{game.title}》已标记为 {STATUS_LABELS[game.status]}")


@router.get("/itch/export")
def itch_export(db: Db, date: str = ""):
    day = _parse_day(date)
    games = _day_query(db, day, "", "")
    lines: list[str] = [
        f"# itch.io 新游戏速递 · {day.isoformat()}（共 {len(games)} 款）",
        "",
        f"抓取时间：{now_local().strftime('%Y-%m-%d %H:%M')}，来源：{get_settings().itch_radar_feeds}",
        "以下材料可直接交给 AI，为每款游戏在 PlayBloo 生成独立详情页。",
    ]
    for game in games:
        published = game.effective_published_at.strftime("%Y-%m-%d %H:%M")
        lines += [
            "",
            f"## {game.title}",
            f"- 游戏页面：{game.url}",
            f"- 作者：{game.author or '未知'}",
            f"- 上架时间：{published}（UTC+8）",
            f"- 价格：{game.price or 'Free'}",
            f"- 状态：{STATUS_LABELS.get(game.status, game.status.value)}；平台：{'、'.join(game.platforms) or 'HTML5（浏览器可玩）'}",
        ]
        if game.genres:
            lines.append(f"- 类型：{'、'.join(game.genres)}")
        if game.tags:
            lines.append(f"- 标签：{'、'.join(game.tags)}")
        description = game.description or "（无简介）"
        lines.append(f"- 简介：{description}")
        if game.cover_url:
            lines.append(f"- 封面图：{game.cover_url}")
        for index, shot in enumerate(game.screenshots, 1):
            lines.append(f"- 截图{index}：{shot}")
        if game.keywords:
            lines.append(f"- 建议关键词：{'、'.join(game.keywords)}")
        if game.quality_notes:
            lines.append(f"- 质量提醒：{'；'.join(game.quality_notes)}")
        if game.last_error:
            lines.append(f"- 抓取备注：{game.last_error}")
    text = "\n".join(lines) + "\n"
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"inline; filename=itch-games-{day.isoformat()}.md"},
    )
