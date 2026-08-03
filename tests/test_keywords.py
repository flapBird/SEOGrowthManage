import asyncio

from app.database import SessionLocal
from app.keyword_discovery.normalizer import normalize_game_title
from app.keyword_discovery.pipeline import enrich_candidate
from app.keyword_discovery.sources import parse_sitemap_xml
from app.models import (
    KeywordCandidate,
    KeywordCandidateStatus,
    KeywordSignalSnapshot,
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
        calls = asyncio.run(enrich_candidate(db, candidate, FakeSerpApi()))
        db.refresh(candidate)
        assert calls == 4
        assert candidate.status == KeywordCandidateStatus.hot
        assert candidate.total_score >= 70
        assert db.query(KeywordSignalSnapshot).count() == 4
