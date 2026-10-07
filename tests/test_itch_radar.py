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
from app.models import ItchGame, ItchGameStatus


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


def test_itch_list_page_and_export(authenticated_client):
    import asyncio
    from datetime import datetime

    async def seed():
        with SessionLocal() as db:
            db.add(ItchGame(
                url="https://demo.itch.io/demo-game", title="Demo Game", author="demodev",
                description="A demo browser game long enough for export rendering.",
                status=ItchGameStatus.ready,
                itch_published_at=datetime(2026, 10, 6, 21, 0, 0),
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
