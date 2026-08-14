import asyncio

import httpx

from app.database import SessionLocal
from app.keyword_discovery.normalizer import normalize_game_title
from app.keyword_discovery.pipeline import _build_fetch_summary, enrich_candidate
from app.keyword_discovery.sources import download_with_retry, parse_sitemap_xml
from app.models import (
    KeywordCandidate,
    KeywordCandidateStatus,
    KeywordSignalSnapshot,
    NotifyChannel,
    NotifyChannelType,
    SerpApiPool,
)
from app.security import CredentialCipher


def test_normalizer_removes_noise_and_rejects_generic_titles():
    assert normalize_game_title("  Neon-Rider Gameplay Walkthrough Part 12  ") == ("Neon-Rider", "neon rider")
    assert normalize_game_title("Free Online Game") is None
    assert normalize_game_title("938475983") is None


def test_sitemap_parser_extracts_image_title_and_url_slug():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
      <url><loc>https://games.example/neon-rider</loc><image:image><image:title>Neon Rider</image:title></image:image></url>
      <url><loc>https://games.example/space-dash</loc></url>
    </urlset>"""
    entries, children = parse_sitemap_xml(xml)
    assert children == []
    assert [(entry.title, entry.url) for entry in entries] == [
        ("Neon Rider", "https://games.example/neon-rider"),
        ("space dash", "https://games.example/space-dash"),
    ]


def test_manual_import_and_pool_key_are_persisted_safely(authenticated_client):
    response = authenticated_client.post(
        "/keywords/manual-import",
        data={"language": "en", "keywords": "Neon Rider\nNeon Rider Gameplay\nFree Online Game"},
    )
    assert response.status_code == 200
    page = authenticated_client.get("/keywords")
    assert "Neon Rider" in page.text
    with SessionLocal() as db:
        assert db.query(KeywordCandidate).count() == 1
        candidate_id = db.query(KeywordCandidate).one().id
    assert authenticated_client.get(f"/keywords/{candidate_id}").status_code == 200
    assert authenticated_client.get("/keyword-sources").status_code == 200

    authenticated_client.post(
        "/serpapi-pools",
        data={"name": "主额度池", "api_key": "serp-secret-key", "priority": 10},
    )
    with SessionLocal() as db:
        pool = db.query(SerpApiPool).one()
        assert "serp-secret-key" not in pool.encrypted_api_key
        assert CredentialCipher().decrypt(pool.encrypted_api_key) == "serp-secret-key"
    pool_page = authenticated_client.get("/serpapi-pools")
    assert "serp-secret-key" not in pool_page.text


def test_enrichment_scores_hot_candidate_with_fake_serpapi():
    class FakeSerpApi:
        async def search(self, **params):
            engine = params["engine"]
            if engine == "google_autocomplete":
                return {"suggestions": [{"value": "neon rider game"}, {"value": "play neon rider online"}]}, 1
            if engine == "google_trends":
                return {"interest_over_time": {"timeline_data": [
                    {"values": [{"extracted_value": 15}]},
                    {"values": [{"extracted_value": 35}]},
                    {"values": [{"extracted_value": 80}]},
                ]}}, 1
            if engine == "youtube":
                return {"video_results": [{"views": 500_000}, {"views": "1.2M"}]}, 1
            return {"organic_results": [
                {"title": "Play Neon Rider", "link": "https://smallgames.example/neon-rider"},
                {"title": "Neon Rider tips", "link": "https://blog.example/tips"},
            ]}, 1

    with SessionLocal() as db:
        candidate = KeywordCandidate(
            keyword="Neon Rider",
            normalized_key="neon rider",
            language="en",
            country="US",
            source_count=2,
        )
        db.add(candidate)
        db.commit()
        calls, became_hot = asyncio.run(enrich_candidate(db, candidate, FakeSerpApi()))
        db.refresh(candidate)
        assert calls == 4
        assert became_hot is True
        assert candidate.status == KeywordCandidateStatus.hot
        assert candidate.total_score >= 70
        assert db.query(KeywordSignalSnapshot).count() == 4

    # 同一候选再次 enrich（已是 hot），不应再被标记为“新晋 HOT”。
    with SessionLocal() as db:
        candidate = db.query(KeywordCandidate).one()
        _, became_hot_again = asyncio.run(enrich_candidate(db, candidate, FakeSerpApi()))
        assert became_hot_again is False


def test_notify_channel_encrypts_config_and_never_echoes(authenticated_client):
    authenticated_client.post(
        "/notify-channels",
        data={"name": "测试微信", "channel_type": "serverchan", "sendkey": "SCT-SECRET-123"},
    )
    page = authenticated_client.get("/notify-channels")
    assert "SCT-SECRET-123" not in page.text
    assert "测试微信" in page.text
    with SessionLocal() as db:
        channel = db.query(NotifyChannel).one()
        assert "SCT-SECRET-123" not in channel.config_json
        assert CredentialCipher().decrypt_json(channel.config_json) == {"sendkey": "SCT-SECRET-123"}


def test_notify_dispatch_records_failure_and_success(monkeypatch):
    """notify() 遍历启用通道，成功通道清零失败计数，失败通道写 last_error。用假 httpx 验证。"""
    from app.keyword_discovery import notify as notify_mod

    calls: list[str] = []
    dispatch_index = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            pass

    class FakeClient:
        async def post(self, url, **kwargs):
            dispatch_index["n"] += 1
            calls.append(url)
            # 第二个通道（坏通道）推送时报错。
            if dispatch_index["n"] == 2:
                raise httpx.ConnectError("boom")
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    def fake_client_factory(*_a, **_k):
        return FakeClient()

    monkeypatch.setattr(notify_mod.httpx, "AsyncClient", fake_client_factory)

    cipher = CredentialCipher()
    with SessionLocal() as db:
        good = NotifyChannel(name="好通道", channel_type=NotifyChannelType.serverchan,
                             config_json=cipher.encrypt_json({"sendkey": "GOOD"}), enabled=True)
        bad = NotifyChannel(name="坏通道", channel_type=NotifyChannelType.serverchan,
                            config_json=cipher.encrypt_json({"sendkey": "BAD"}), enabled=True)
        bad.consecutive_failures = 2
        db.add_all([good, bad])
        db.commit()
        succeeded = asyncio.run(notify_mod.notify(db, "标题", "正文"))
        db.refresh(good)
        db.refresh(bad)
        assert succeeded == 1
        assert good.last_error is None and good.consecutive_failures == 0
        assert bad.last_error is not None
        # 两通道都被尝试。
        assert len(calls) == 2


def test_source_creation_accepts_crazygames_domain(authenticated_client):
    """放开拦截后 CrazyGames 域名应能正常创建来源（过去会被 422 拒绝）。"""
    response = authenticated_client.post(
        "/keyword-sources",
        data={
            "name": "CrazyGames",
            "source_type": "sitemap",
            "url": "https://www.crazygames.com/sitemap-index.xml",
            "language": "en", "country": "US", "interval_minutes": "360",
            "terms_confirmed": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert authenticated_client.get("/keyword-sources").status_code == 200


def test_fetch_retry_then_success(monkeypatch):
    """download_with_retry 失败两次后第三次成功应返回内容且不抛错。"""
    from app.keyword_discovery import sources

    async def _noop_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(sources.asyncio, "sleep", _noop_sleep)

    state = {"n": 0}

    class FakeResp:
        def __init__(self, content):
            self.content = content
            self.status_code = 200

        def raise_for_status(self):
            pass

    class FakeClient:
        async def get(self, url, **kwargs):
            state["n"] += 1
            if state["n"] < 3:
                raise httpx.ConnectError("boom")
            return FakeResp(b"<ok/>")

    data = asyncio.run(download_with_retry(FakeClient(), "https://x.example/sitemap.xml", retries=3))
    assert state["n"] == 3
    assert data == b"<ok/>"


def test_fetch_summary_flags_anomaly_ratio():
    """新增比例超过阈值时摘要标题带 ⚠️ 异常标记。"""
    title, body = _build_fetch_summary([
        {"source": "X", "status": "success", "discovered": 40, "new_candidates": 40, "total": 100, "new_keywords": ["k"] * 40},
    ])
    assert "⚠️" in title
    assert "异常" in body

    # 正常小量新增不应标记异常
    title_ok, _ = _build_fetch_summary([
        {"source": "Y", "status": "success", "discovered": 3, "new_candidates": 3, "total": 100, "new_keywords": ["a"]},
    ])
    assert "⚠️" not in title_ok

    # 全无新增且无失败时不应推送（标题为 None）
    title_empty, _ = _build_fetch_summary([
        {"source": "Z", "status": "success", "discovered": 0, "new_candidates": 0, "total": 100, "new_keywords": []},
    ])
    assert title_empty is None
