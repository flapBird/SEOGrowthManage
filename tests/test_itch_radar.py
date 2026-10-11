"""itch.io 新游雷达：RSS/详情页解析、关键词推导、入库去重。"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.itch_radar.fetcher import poll_feeds
from app.itch_radar.parse import (
    derive_keywords,
    evaluate_quality,
    normalize_game_url,
    parse_game_page,
    parse_itch_rss,
)
from app.models import ItchGame, ItchGameStatus, now_local


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<title>Latest free HTML5 games for Web - itch.io</title>
<item>
  <guid>https://pgskizzes.itch.io/clawtastrophe</guid>
  <title>Clawtastrophe [Free] [Simulation]</title>
  <plainTitle>Clawtastrophe</plainTitle>
  <imageurl>https://img.itch.zone/aW1nLzEucG5n/315x250%23c/cPqFeG.jpg</imageurl>
  <price>$0.00</price><currency>USD</currency>
  <link>https://pgskizzes.itch.io/clawtastrophe</link>
  <description>Degeneracy wears many hats &lt;img src="https://img.itch.zone/x.jpg"/&gt;</description>
  <pubDate>Tue, 06 Oct 2026 13:33:03 GMT</pubDate>
  <createDate>Tue, 06 Oct 2026 13:33:03 GMT</createDate>
  <updateDate>Tue, 06 Oct 2026 13:43:11 GMT</updateDate>
  <platforms></platforms>
</item>
<item>
  <guid>https://froggacuda.itch.io/wizza</guid>
  <title>Wizza [Free]</title>
  <plainTitle>Wizza</plainTitle>
  <link>https://froggacuda.itch.io/wizza</link>
  <pubDate>Tue, 06 Oct 2026 13:30:51 GMT</pubDate>
</item>
</channel></rss>"""

GAME_PAGE_SAMPLE = """
<html><head>
<meta content="https://img.itch.zone/aW1nLzEub3JpZ2luYWwucG5n" property="og:image"/>
<meta content="Clawtastrophe by pgskizzes" property="og:title"/>
<meta content="Degeneracy wears many hats. A physics casino simulation you can play right in your browser." property="og:description"/>
</head><body>
<div class="info_panel_wrapper"><div class="game_info_panel_widget"><table><tbody>
<tr><td>Published</td><td><abbr title="06 October 2026 @ 13:43 UTC">1 hour ago</abbr></td></tr>
<tr><td>Status</td><td><a href="https://itch.io/games/released">Released</a></td></tr>
<tr><td>Platforms</td><td><a href="https://itch.io/games/html5">HTML5</a></td></tr>
<tr><td>Author</td><td><a href="https://pgskizzes.itch.io">pgskizzes</a></td></tr>
<tr><td>Genre</td><td><a href="https://itch.io/games/genre-simulation">Simulation</a>, <a href="https://itch.io/games/tag-card-game">Card Game</a></td></tr>
<tr><td>Tags</td><td><a href="https://itch.io/games/tag-3d">3D</a>, <a href="https://itch.io/games/tag-arcade">Arcade</a></td></tr>
</tbody></table></div></div>
<div class="screenshot_list"><img src="https://img.itch.zone/shot1.jpg"/><img src="https://img.itch.zone/shot2.jpg"/></div>
</body></html>
"""


def test_parse_itch_rss():
    items = parse_itch_rss(RSS_SAMPLE.encode())
    assert len(items) == 2
    first = items[0]
    assert first.url == "https://pgskizzes.itch.io/clawtastrophe"
    assert first.title == "Clawtastrophe"  # plainTitle 优先
    assert first.price == "$0.00"
    assert first.cover_url.startswith("https://img.itch.zone/")
    assert first.description == "Degeneracy wears many hats"  # 去掉内嵌 img
    # 13:33:03 GMT → 东八区 21:33:03，naive
    assert (first.published_at.year, first.published_at.month, first.published_at.day) == (2026, 10, 6)
    assert (first.published_at.hour, first.published_at.minute) == (21, 33)


def test_parse_game_page():
    detail = parse_game_page(GAME_PAGE_SAMPLE)
    assert detail.title == "Clawtastrophe by pgskizzes"
    assert detail.author == "pgskizzes"
    assert detail.status == "Released"
    assert detail.platforms == ["HTML5"]
    assert detail.tags == ["3D", "Arcade"]
    assert "Simulation" in detail.genres and "Card Game" in detail.genres
    assert detail.screenshots == ["https://img.itch.zone/shot1.jpg", "https://img.itch.zone/shot2.jpg"]
    # 13:43 UTC → 东八区 21:43
    assert (detail.published_exact_at.hour, detail.published_exact_at.minute) == (21, 43)
    quality = evaluate_quality(
        cover_url=detail.cover_url, description=detail.description,
        status=detail.status, platforms=detail.platforms,
    )
    assert quality == {"ok": True, "notes": []}


def test_evaluate_quality_flags():
    result = evaluate_quality(cover_url=None, description="too short", status="In development", platforms=["Windows"])
    assert result["ok"] is False
    assert any("封面" in note for note in result["notes"])
    assert any("简介" in note for note in result["notes"])


def test_derive_keywords_dedup():
    keywords = derive_keywords("Wizza", ["Puzzle", "puzzle", "Cozy"], ["Puzzle"])
    lowered = [k.lower() for k in keywords]
    assert len(lowered) == len(set(lowered))
    assert keywords[0] == "Wizza"
    assert "Wizza play online" in keywords
    assert "Cozy" in keywords


def test_normalize_game_url():
    assert normalize_game_url("https://a.itch.io/game?utm=x") == "https://a.itch.io/game"
    assert normalize_game_url("http://A.itch.io/game/") == "https://a.itch.io/game"


def test_poll_feeds_upsert(monkeypatch):
    import asyncio

    async def fake_download(client, url, retries=None):
        return RSS_SAMPLE.encode()

    async def scenario():
        with SessionLocal() as db:
            first = await poll_feeds(db)
            assert first["seen"] == 2
            assert first["created"] == 2
            games = db.scalars(select(ItchGame)).all()
            assert {g.title for g in games} == {"Clawtastrophe", "Wizza"}
            assert all(g.status == ItchGameStatus.new for g in games)
            assert all(g.itch_published_at is not None for g in games)

            second = await poll_feeds(db)
            assert second["seen"] == 2  # 再次看到但不重复入库
            assert second["created"] == 0
            assert len(db.scalars(select(ItchGame)).all()) == 2

    monkeypatch.setattr("app.itch_radar.fetcher._download_with_retry", fake_download)
    asyncio.run(scenario())


def test_poll_feeds_daily_quota(monkeypatch):
    """每日配额：当天已收录满则跳过；未满按榜单顺序收录；往日游戏不占额度。"""
    import asyncio
    from datetime import timedelta

    from app.config import get_settings

    async def fake_download(client, url, retries=None):
        return RSS_SAMPLE.encode()

    monkeypatch.setattr("app.itch_radar.fetcher._download_with_retry", fake_download)

    async def seed_today(count: int):
        with SessionLocal() as db:
            for i in range(count):
                db.add(ItchGame(url=f"https://seed.itch.io/today-{i}", title=f"T{i}",
                                itch_published_at=now_local()))
            db.commit()

    async def seed_yesterday(count: int):
        with SessionLocal() as db:
            for i in range(count):
                yesterday = now_local() - timedelta(days=1)
                db.add(ItchGame(url=f"https://seed.itch.io/old-{i}", title=f"O{i}",
                                itch_published_at=yesterday, discovered_at=yesterday))
            db.commit()

    # A) 配额 1，当天已收录 1 款 → 满员，直接跳过且不发请求
    async def boom(client, url, retries=None):
        raise AssertionError("配额满员时不应发起请求")

    monkeypatch.setattr(get_settings(), "itch_radar_daily_limit", 1)
    asyncio.run(seed_today(1))
    monkeypatch.setattr("app.itch_radar.fetcher._download_with_retry", boom)
    with SessionLocal() as db:
        result = asyncio.run(poll_feeds(db))
    assert result["created"] == 0 and "跳过" in result["note"]

    # B) 配额 2，当天已收录 1 款 → 只收榜单第 1 个新游戏，第 2 个不收
    asyncio.run(seed_yesterday(1))  # 往日游戏不应影响今天的配额
    monkeypatch.setattr(get_settings(), "itch_radar_daily_limit", 2)
    monkeypatch.setattr("app.itch_radar.fetcher._download_with_retry", fake_download)
    with SessionLocal() as db:
        result = asyncio.run(poll_feeds(db))
    assert result["created"] == 1  # 只收 clawtastrophe，wizza 因配额用尽被跳过
    urls = {g.url for g in db.scalars(select(ItchGame)).all()}
    assert "https://pgskizzes.itch.io/clawtastrophe" in urls
    assert "https://froggacuda.itch.io/wizza" not in urls

    # C) 已入库的游戏重复出现不占额度：今天已收录 2 款（seed + clawtastrophe），
    #    配额给 3 → 剩 1 个名额；clawtastrophe 重复出现只刷新 last_seen，名额留给 wizza
    monkeypatch.setattr(get_settings(), "itch_radar_daily_limit", 3)
    with SessionLocal() as db:
        result = asyncio.run(poll_feeds(db))
    assert result["created"] == 1  # wizza 补上（clawtastrophe 是去重不算新增）
    urls = {g.url for g in db.scalars(select(ItchGame)).all()}
    assert "https://froggacuda.itch.io/wizza" in urls


def test_itch_batch_status_and_api(authenticated_client):
    import asyncio
    from datetime import datetime

    async def seed():
        with SessionLocal() as db:
            db.add_all([
                ItchGame(url="https://a.itch.io/game-a", title="A",
                         itch_published_at=datetime(2026, 10, 7, 10, 0, 0), discovered_at=datetime(2026, 10, 7, 10, 0, 0)),
                ItchGame(url="https://b.itch.io/game-b", title="B",
                         itch_published_at=datetime(2026, 10, 7, 11, 0, 0), discovered_at=datetime(2026, 10, 7, 11, 0, 0)),
                ItchGame(url="https://c.itch.io/game-c", title="C",
                         itch_published_at=datetime(2026, 10, 8, 10, 0, 0), discovered_at=datetime(2026, 10, 8, 10, 0, 0)),
            ])
            db.commit()

    asyncio.run(seed())
    client = authenticated_client

    # 页面批量标记：勾选 A、B
    resp = client.post("/itch/batch-status",
                       data={"game_id": ["1", "2"], "back": "date=2026-10-07"},
                       follow_redirects=False)
    assert resp.status_code == 303
    with SessionLocal() as db:
        statuses = {g.url: g.status for g in db.scalars(select(ItchGame)).all()}
    assert statuses["https://a.itch.io/game-a"] == ItchGameStatus.used
    assert statuses["https://b.itch.io/game-b"] == ItchGameStatus.used
    assert statuses["https://c.itch.io/game-c"] == ItchGameStatus.new

    # 接口：错误 key → 401
    assert client.post("/api/itch/mark-used", json={"date": "2026-10-08"},
                       headers={"X-API-Key": "wrong"}).status_code == 401
    # 接口：空载荷 → 422
    assert client.post("/api/itch/mark-used", json={}, headers={"X-API-Key": "test-itch-api-key"}).status_code == 422
    # 接口：按日期标记 10-08 的 C
    resp = client.post("/api/itch/mark-used", json={"date": "2026-10-08"},
                       headers={"X-API-Key": "test-itch-api-key"})
    assert resp.status_code == 200 and resp.json() == {"marked": 1}
    # 接口：按 URL 标记（已 used 的不重复计数 + 未匹配清单）
    resp = client.post("/api/itch/mark-used", json={"urls": [
        "https://a.itch.io/game-a?utm=x",          # 已是 used，不计入 marked
        "https://a.itch.io/game-a/",               # 归一化后同上
        "https://unknown.itch.io/missing",         # 库里没有
    ]}, headers={"X-API-Key": "test-itch-api-key"})
    body = resp.json()
    assert resp.status_code == 200 and body["marked"] == 0
    assert body["not_found"] == ["https://unknown.itch.io/missing"]


def test_itch_list_page_and_export(authenticated_client):
    import asyncio
    from datetime import datetime

    async def seed():
        with SessionLocal() as db:
            db.add(ItchGame(
                url="https://demo.itch.io/demo-game", title="Demo Game", author="demodev",
                description="A demo browser game long enough for export rendering.",
                status=ItchGameStatus.ready,
                itch_published_at=datetime(2026, 10, 6, 21, 0, 0), discovered_at=datetime(2026, 10, 6, 21, 0, 0),
                genre_json='["Puzzle"]', tags_json='["cozy"]', platforms_json='["HTML5"]',
                keywords_json='["Demo Game online", "cozy"]', quality_json='{"ok": true, "notes": []}',
            ))
            db.commit()

    asyncio.run(seed())

    client = authenticated_client
    page = client.get("/itch?date=2026-10-06")
    assert page.status_code == 200
    assert "Demo Game" in page.text

    export = client.get("/itch/export?date=2026-10-06")
    assert export.status_code == 200
    body = export.text
    assert "## Demo Game" in body
    assert "https://demo.itch.io/demo-game" in body
    assert "Demo Game online" in body
    assert "UTC+8" in body
