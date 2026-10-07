"""itch.io 新游雷达的网络层：轮询 RSS 发现新游戏（ upsert 入库），限量补全详情页。

设计取舍：
- RSS 轮询每次只有 1 个请求，可以放心高频跑；详情页才是限流（429）风险所在，
  所以每轮限量 + 请求间隔 + 失败退避，状态留在 new 下轮再试。
- 数据形状与关键词候选差异太大（游戏有封面/标签/平台/作者），不复用
  KeywordCandidate，而是独立 ItchGame 表；只复用 sources.py 的下载重试。
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import ItchGame, ItchGameStatus, now_local
from .parse import (
    DEFAULT_USER_AGENT,
    ItchFeedItem,
    derive_keywords,
    evaluate_quality,
    normalize_game_url,
    parse_game_page,
    parse_itch_rss,
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _download_with_retry(client: httpx.AsyncClient, url: str, retries: int = 2) -> bytes:
    """RSS 抓取的指数退避重试：失败后 2/4 秒再试，兜底 itch 偶发 429/瞬时错误。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = await client.get(url, follow_redirects=True, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            await asyncio.sleep(2 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def configured_feeds() -> list[str]:
    settings = get_settings()
    feeds = [f.strip() for f in settings.itch_radar_feeds.replace("\n", ",").split(",")]
    return [f for f in feeds if f]


def _make_client() -> httpx.AsyncClient:
    settings = get_settings()
    proxy = settings.itch_radar_proxy or None
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # itch 的 Cloudflare 防护会对"不像浏览器的请求"返回 403（尤其数据中心 IP）；
        # 带上 Referer 与 Sec-Fetch 系列头可以降低被拦截概率，但无法完全绕过。
        "Referer": "https://itch.io/games/newest/free/html5/platform-web",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-User": "?1",
    }
    return httpx.AsyncClient(headers=headers, proxy=proxy, timeout=30, follow_redirects=True)


async def _get_polite(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """详情页专用 GET：429 时退避重试，其余非 2xx 直接抛错由调用方记录。"""
    settings = get_settings()
    last_response: httpx.Response | None = None
    for attempt in range(settings.itch_radar_max_retries + 1):
        response = await client.get(url)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        last_response = response
        if attempt < settings.itch_radar_max_retries:
            await asyncio.sleep(10 * (attempt + 1))
    assert last_response is not None
    last_response.raise_for_status()
    raise RuntimeError("unreachable")  # pragma: no cover


async def poll_feeds(db: Session) -> dict:
    """抓取全部配置的 RSS feed，把新游戏 upsert 进 itch_games。"""
    feeds = configured_feeds()
    seen = 0
    created = 0
    errors: list[str] = []
    async with _make_client() as client:
        for feed_url in feeds:
            try:
                content = await _download_with_retry(client, feed_url, retries=2)
                items = parse_itch_rss(content)
            except Exception as exc:
                errors.append(f"{feed_url}: {type(exc).__name__}: {exc}")
                continue
            for item in items:
                seen += 1
                game = db.scalar(select(ItchGame).where(ItchGame.url == item.url))
                if game is None:
                    game = ItchGame(
                        url=item.url,
                        title=item.title or item.url.rsplit("/", 1)[-1],
                        cover_url=item.cover_url,
                        description=item.description,
                        price=item.price,
                        source_feed=feed_url,
                        itch_published_at=item.published_at,
                        platforms_json=_json(item.platforms) or None,
                        status=ItchGameStatus.new,
                    )
                    db.add(game)
                    created += 1
                else:
                    game.last_seen_at = now_local()
            db.commit()
    return {"feeds": len(feeds), "seen": seen, "created": created, "errors": errors}


async def enrich_game(db: Session, game: ItchGame, client: httpx.AsyncClient) -> bool:
    """抓单个游戏详情页并补全字段；成功返回 True，失败记录退避等待下轮。

    403/522 多为出口 IP 被 itch 前置防护拦截，按 attempts 指数退避
    （2h → 4h → … → 封顶 24h），8 次自动重试后只允许手动「补全详情」触发。
    """
    settings = get_settings()
    try:
        response = await _get_polite(client, game.url)
    except Exception as exc:
        game.last_error = f"{type(exc).__name__}: {exc}"
        game.detail_attempts = (game.detail_attempts or 0) + 1
        game.next_detail_at = now_local() + timedelta(hours=min(2 ** game.detail_attempts, 24))
        db.commit()
        return False
    detail = parse_game_page(response.text)
    game.author = detail.author or game.author
    game.cover_url = detail.cover_url or game.cover_url
    game.description = detail.description or game.description
    if detail.published_exact_at:
        game.itch_published_at = detail.published_exact_at
    if detail.genres:
        game.genre_json = _json(detail.genres)
    if detail.tags:
        game.tags_json = _json(detail.tags)
    platforms = detail.platforms or game.platforms
    if platforms:
        game.platforms_json = _json(platforms)
    if detail.screenshots:
        game.screenshots_json = _json(detail.screenshots)
    game.title = detail.title or game.title
    game.keywords_json = _json(
        derive_keywords(game.title, detail.tags, detail.genres)
    )
    game.quality_json = _json(
        evaluate_quality(
            cover_url=game.cover_url,
            description=game.description,
            status=detail.status,
            platforms=platforms,
        )
    )
    game.detail_fetched_at = now_local()
    game.detail_attempts = 0
    game.next_detail_at = None
    game.status = ItchGameStatus.ready
    game.last_error = None
    db.commit()
    await asyncio.sleep(settings.itch_radar_detail_delay_seconds)
    return True


async def enrich_pending(db: Session, limit: int | None = None) -> int:
    """为本轮待补全的游戏抓详情页，返回成功数。失败退避中的游戏跳过。"""
    batch = get_settings().itch_radar_detail_batch if limit is None else limit
    if batch <= 0:
        return 0
    now = now_local()
    due = (ItchGame.next_detail_at.is_(None)) | (ItchGame.next_detail_at <= now)
    games = db.scalars(
        select(ItchGame)
        .where(
            ItchGame.status == ItchGameStatus.new,
            ItchGame.detail_fetched_at.is_(None),
            due,
            ItchGame.detail_attempts < 8,
        )
        .order_by(ItchGame.detail_attempts.asc(), ItchGame.discovered_at.desc())
        .limit(batch)
    ).all()
    if not games:
        return 0
    done = 0
    async with _make_client() as client:
        for game in games:
            if await enrich_game(db, game, client):
                done += 1
    return done


async def run_radar_cycle() -> dict:
    """调度器/手动触发的完整一轮：RSS 发现 → 详情补全。自带会话。"""
    with SessionLocal() as db:
        poll = await poll_feeds(db)
        enriched = await enrich_pending(db)
    return {**poll, "enriched": enriched}
