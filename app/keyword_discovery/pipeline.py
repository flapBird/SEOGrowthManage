from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import (
    KeywordCandidate,
    KeywordCandidateStatus,
    KeywordFetchRun,
    KeywordFetchStatus,
    KeywordSignalSnapshot,
    KeywordSource,
    KeywordSourceItem,
    KeywordSourceType,
    now_local,
)
from .normalizer import normalize_game_title
from .notify import notify
from .serpapi import SerpApiClient, SerpApiUnavailable
from .sources import SourceEntry, fetch_source_entries


STRONG_DOMAINS = {
    "wikipedia.org", "youtube.com", "steampowered.com", "ign.com", "fandom.com",
    "reddit.com", "play.google.com", "apps.apple.com", "store.epicgames.com",
}
SERP_SIGNAL_TYPES = {"serpapi_autocomplete", "serpapi_trends", "serpapi_youtube", "serpapi_competition"}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fingerprint(entry: SourceEntry) -> str:
    return hashlib.sha256(f"{entry.url or ''}\n{entry.title.casefold()}".encode()).hexdigest()


def ingest_entries(db: Session, source: KeywordSource, entries: list[SourceEntry], baseline_mode: bool = False) -> tuple[int, int]:
    """把抓回来的条目入库并建候选。

    baseline_mode=True（首次抓取建基线）：只建来源项指纹、刷新 last_seen_at、统计 discovered，
    完全不碰候选库——几十万历史老词不该一股脑进候选库拖垮 SerpAPI/Agent。
    baseline_mode=False（默认，增量）：走原有逻辑，新出现的指纹才建候选。
    手动导入永远传 False（人工精选词应立即生效）。
    """
    now = now_local()
    discovered = 0
    new_candidates = 0
    for entry in entries:
        fingerprint = _fingerprint(entry)
        existing_item = db.scalar(select(KeywordSourceItem).where(
            KeywordSourceItem.source_id == source.id,
            KeywordSourceItem.fingerprint == fingerprint,
        ))
        if existing_item:
            existing_item.last_seen_at = now
            continue
        discovered += 1
        db.add(KeywordSourceItem(
            source_id=source.id,
            fingerprint=fingerprint,
            raw_title=entry.title[:1000],
            item_url=(entry.url or "")[:2048] or None,
            first_seen_at=now,
            last_seen_at=now,
        ))
        if baseline_mode:
            continue  # 基线模式：指纹已建，到此为止，不评估候选。
        normalized = normalize_game_title(entry.title, source.language)
        if not normalized:
            continue
        display_keyword, normalized_key = normalized
        candidate = db.scalar(select(KeywordCandidate).where(KeywordCandidate.normalized_key == normalized_key))
        if candidate is None:
            candidate = KeywordCandidate(
                keyword=display_keyword,
                normalized_key=normalized_key,
                language=source.language,
                country=source.country,
                status=KeywordCandidateStatus.discovered,
                freshness_score=25,
                total_score=25,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(candidate)
            db.flush()
            new_candidates += 1
        else:
            candidate.last_seen_at = now
        prior_source_signal = db.scalar(select(KeywordSignalSnapshot.id).where(
            KeywordSignalSnapshot.candidate_id == candidate.id,
            KeywordSignalSnapshot.source_id == source.id,
            KeywordSignalSnapshot.signal_type == "source_discovery",
        ))
        if prior_source_signal is None:
            db.add(KeywordSignalSnapshot(
                candidate_id=candidate.id,
                source_id=source.id,
                signal_type="source_discovery",
                numeric_value=1,
                payload_json=_json({"raw_title": entry.title, "url": entry.url}),
            ))
            candidate.source_count += 1 if candidate.source_count else 1
            if candidate.status == KeywordCandidateStatus.ignore:
                candidate.status = KeywordCandidateStatus.discovered
                candidate.ignored_until = None
                candidate.next_review_at = now
    db.commit()
    return discovered, new_candidates


async def run_source(source_id: int) -> dict:
    """抓取单个来源。返回结果摘要供上层聚合成一条通知（避免逐来源推送刷屏）。"""
    with SessionLocal() as db:
        source = db.get(KeywordSource, source_id)
        if source is None or not source.enabled or source.source_type == KeywordSourceType.manual:
            return {}
        source_name = source.name
        run = KeywordFetchRun(source_id=source.id, status=KeywordFetchStatus.running)
        db.add(run)
        db.commit()
        try:
            entries = await fetch_source_entries(source)
            if not entries:
                # 抓取未抛错但结果为空：大概率是被 WAF 拦截或网络异常导致返回了空文档。
                # 绝不能把它当作“站点真的没有内容”——那样会污染基线。保留 last_fetched_at 不动，
                # 仅记录一条失败运行，下次抓取恢复正常即可（移植脚本“空结果不覆盖基线”的防御意图）。
                source.last_error = "抓取结果为空，疑似被拦截或返回空文档，未更新基线"
                run.status = KeywordFetchStatus.failed
                run.message = source.last_error
                run.finished_at = now_local()
                db.commit()
                return {"source": source_name, "status": "failed", "message": source.last_error}
            # 是否首次抓取建基线：来源未初始化且非 manual（manual 永远走增量，立即建候选）。
            # 空结果分支已在上面 return，到这里说明抓到了内容，可以安全判定。
            is_first_run = (not source.is_initialized) and source.source_type != KeywordSourceType.manual
            discovered, new_candidates = ingest_entries(db, source, entries, baseline_mode=is_first_run)
            if is_first_run:
                source.is_initialized = True  # 基线已建立，后续抓取走增量
            source.last_fetched_at = now_local()
            source.last_error = None
            run.status = KeywordFetchStatus.success
            run.discovered_count = discovered
            run.new_candidate_count = new_candidates
            if is_first_run:
                run.message = f"首次抓取，已建立基线 {discovered} 条，不计为新增候选；下次起增量计新增"
            else:
                run.message = f"读取 {len(entries)} 项，新来源项 {discovered}，新候选 {new_candidates}"
            run.finished_at = now_local()
            db.commit()
            new_keywords = _recent_new_keywords(db, source.id, limit=15)
            return {
                "source": source_name,
                "status": "success",
                "discovered": discovered,
                "new_candidates": new_candidates,
                "total": len(entries),
                "new_keywords": new_keywords,
                "baseline": is_first_run,
            }
        except Exception as exc:
            source.last_error = f"{type(exc).__name__}: {exc}"[:4000]
            run.status = KeywordFetchStatus.failed
            run.message = source.last_error
            run.finished_at = now_local()
            db.commit()
            return {"source": source_name, "status": "failed", "message": source.last_error}


def _recent_new_keywords(db: Session, source_id: int, limit: int = 15) -> list[str]:
    """取某来源本次新增的候选词（按信号快照时间倒序），用于通知摘要。"""
    rows = db.scalars(
        select(KeywordCandidate.keyword, KeywordSignalSnapshot.captured_at)
        .join(KeywordSignalSnapshot, KeywordSignalSnapshot.candidate_id == KeywordCandidate.id)
        .where(
            KeywordSignalSnapshot.source_id == source_id,
            KeywordSignalSnapshot.signal_type == "source_discovery",
        )
        .order_by(KeywordSignalSnapshot.captured_at.desc())
        .limit(limit)
    ).all()
    return [row[0] for row in rows]


def _build_fetch_summary(results: list[dict]) -> tuple[str | None, str]:
    """把本轮各来源的抓取结果聚合成 markdown 摘要。
    返回 (标题, 正文)；没有内容值得推送时标题为 None。"""
    settings = get_settings()
    successes = [r for r in results if r.get("status") == "success"]
    failures = [r for r in results if r.get("status") == "failed"]
    total_new = sum(r.get("new_candidates", 0) for r in successes)

    anomalies: list[str] = []
    for r in successes:
        if r.get("baseline"):
            continue  # 首次抓取建基线：discovered 必然接近全量，不算异常，也不进新增摘要
        total = r.get("total", 0)
        new = r.get("discovered", 0)
        if total > 0 and new / total > settings.keyword_anomaly_ratio:
            anomalies.append(
                f"- ⚠️ {r['source']}：新增 {new} / 共 {total}（占比 {new/total:.0%}），"
                f"比例异常高，可能是站点改版或抓取逻辑问题，不一定是真新词"
            )
    for r in failures:
        anomalies.append(f"- ⚠️ {r['source']}：{r.get('message', '抓取失败')}")

    if total_new == 0 and not anomalies:
        return None, ""

    lines = []
    for r in successes:
        if r.get("new_candidates", 0) > 0:
            sample = "、".join(r["new_keywords"][:8])
            more = f"等 {r['new_candidates']} 个" if r["new_candidates"] > 8 else ""
            lines.append(f"**{r['source']}** 新增 {r['new_candidates']} 个候选：{sample}{more}")
    if anomalies:
        lines.append("")
        lines.append("**异常提醒（请先核实）：**")
        lines.extend(anomalies)

    title = f"关键词发现：本轮新增 {total_new} 个候选"
    if anomalies:
        title = "⚠️ " + title + "（有异常）"
    return title, "\n".join(lines)


async def fetch_due_sources() -> None:
    now = now_local()
    with SessionLocal() as db:
        sources = db.scalars(select(KeywordSource).where(
            KeywordSource.enabled.is_(True),
            KeywordSource.source_type != KeywordSourceType.manual,
        )).all()
        due_ids = [
            source.id for source in sources
            if source.last_fetched_at is None or source.last_fetched_at + timedelta(minutes=source.interval_minutes) <= now
        ]
    if not due_ids:
        return
    results: list[dict] = []
    for source_id in due_ids:
        results.append(await run_source(source_id))
    # 本轮全部来源抓完后聚合发一条通知（而非逐来源推送），避免刷屏。
    title, body = _build_fetch_summary(results)
    if title:
        with SessionLocal() as db:
            await notify(db, title, body)


def _add_serp_signal(db: Session, candidate: KeywordCandidate, signal_type: str, value: float | None, payload, pool_id: int) -> None:
    db.add(KeywordSignalSnapshot(
        candidate_id=candidate.id,
        signal_type=signal_type,
        numeric_value=value,
        payload_json=_json({"pool_id": pool_id, "result": payload}),
    ))


def _parse_view_count(value) -> int:
    if isinstance(value, int):
        return value
    if not value:
        return 0
    text = str(value).lower().replace(",", "").replace(" views", "")
    multiplier = 1
    if text.endswith("k"):
        multiplier, text = 1_000, text[:-1]
    elif text.endswith("m"):
        multiplier, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


async def enrich_candidate(db: Session, candidate: KeywordCandidate, client: SerpApiClient | None = None) -> tuple[int, bool]:
    """对一个候选跑四路 SerpAPI 信号并评分。返回 (本次 SerpAPI 调用次数, 是否在本次新晋为 HOT)。"""
    client = client or SerpApiClient(db)
    keyword = candidate.keyword
    calls = 0
    prior_status = candidate.status
    results: dict[str, dict] = {}
    requests = (
        ("autocomplete", {"engine": "google_autocomplete", "q": keyword, "hl": candidate.language[:2], "gl": candidate.country.lower()}),
        ("trends", {"engine": "google_trends", "q": keyword, "date": "now 7-d", "data_type": "TIMESERIES"}),
        ("youtube", {"engine": "youtube", "search_query": keyword, "hl": candidate.language[:2], "gl": candidate.country.lower()}),
        ("competition", {"engine": "google", "q": keyword, "hl": candidate.language[:2], "gl": candidate.country.lower(), "num": 10}),
    )
    for name, params in requests:
        payload, pool_id = await client.search(**params)
        calls += 1
        results[name] = payload
        numeric_value = None
        if name == "trends":
            timeline = payload.get("interest_over_time", {}).get("timeline_data", [])
            values = [row.get("values", [{}])[0].get("extracted_value", 0) for row in timeline if row.get("values")]
            numeric_value = float(values[-1]) if values else 0
        elif name == "youtube":
            videos = payload.get("video_results", [])[:10]
            numeric_value = float(sum(_parse_view_count(video.get("views")) for video in videos))
        elif name == "autocomplete":
            numeric_value = float(len(payload.get("suggestions", [])))
        elif name == "competition":
            numeric_value = float(len(payload.get("organic_results", [])))
        _add_serp_signal(db, candidate, f"serpapi_{name}", numeric_value, payload, pool_id)
        db.commit()

    autocomplete = [str(item.get("value", "")).casefold() for item in results["autocomplete"].get("suggestions", [])]
    intent_terms = ("play", "online", "game", "download", "攻略", "怎么玩")
    intent_hits = sum(any(term in suggestion for term in intent_terms) for suggestion in autocomplete)
    intent_score = min(20, 4 + intent_hits * 3) if autocomplete else 0

    timeline = results["trends"].get("interest_over_time", {}).get("timeline_data", [])
    trend_values = [row.get("values", [{}])[0].get("extracted_value", 0) for row in timeline if row.get("values")]
    trend_latest = float(trend_values[-1]) if trend_values else 0
    trend_growth = max(0.0, trend_latest - (sum(trend_values[:max(1, len(trend_values)//2)]) / max(1, len(trend_values)//2))) if trend_values else 0
    videos = results["youtube"].get("video_results", [])[:10]
    youtube_views = sum(_parse_view_count(video.get("views")) for video in videos)
    youtube_snapshots = db.scalars(
        select(KeywordSignalSnapshot)
        .where(
            KeywordSignalSnapshot.candidate_id == candidate.id,
            KeywordSignalSnapshot.signal_type == "serpapi_youtube",
        )
        .order_by(KeywordSignalSnapshot.captured_at.desc())
        .limit(2)
    ).all()
    youtube_velocity = 0.0
    if len(youtube_snapshots) == 2 and youtube_snapshots[1].numeric_value is not None:
        hours = max(1, (youtube_snapshots[0].captured_at - youtube_snapshots[1].captured_at).total_seconds() / 3600)
        youtube_velocity = max(0, youtube_views - youtube_snapshots[1].numeric_value) / hours
    heat_score = min(35, trend_latest * 0.22 + min(9, math.log10(max(1, youtube_views))) + min(4, trend_growth / 20) + min(4, math.log10(max(1, youtube_velocity))))

    organic = results["competition"].get("organic_results", [])[:10]
    strong_count = 0
    exact_title_count = 0
    for result in organic:
        host = urlparse(result.get("link", "")).hostname or ""
        if any(host == domain or host.endswith(f".{domain}") for domain in STRONG_DOMAINS):
            strong_count += 1
        if candidate.normalized_key in str(result.get("title", "")).casefold():
            exact_title_count += 1
    competition_score = max(0, min(15, 15 - strong_count * 1.5 - exact_title_count * 0.5))

    age_hours = max(0, (now_local() - candidate.first_seen_at).total_seconds() / 3600)
    freshness_score = max(0, 25 - age_hours / 24 * 2)
    family_count = 1 + int(bool(autocomplete)) + int(bool(trend_values)) + int(bool(videos)) + int(bool(organic))
    confidence_score = min(5, family_count + min(2, max(0, candidate.source_count - 1)))
    total = min(100, heat_score + freshness_score + intent_score + competition_score + confidence_score)

    candidate.heat_score = round(heat_score, 1)
    candidate.freshness_score = round(freshness_score, 1)
    candidate.intent_score = round(intent_score, 1)
    candidate.competition_score = round(competition_score, 1)
    candidate.confidence_score = round(confidence_score, 1)
    candidate.total_score = round(total, 1)
    candidate.last_enriched_at = now_local()
    became_hot = False
    if total >= 70 and family_count >= 3:
        candidate.status = KeywordCandidateStatus.hot
        candidate.next_review_at = None
        candidate.ignored_until = None
        candidate.decision_reason = "热度、新鲜度和搜索需求达到 HOT 阈值"
        # 只在状态从非 HOT 翻转为 HOT 的那一刻通知，避免每次复查都重复推送同一个 HOT 候选。
        became_hot = prior_status != KeywordCandidateStatus.hot
    elif total >= 35:
        candidate.status = KeywordCandidateStatus.hold
        delay = 24 if total >= 55 else 72 if total >= 42 else 168
        candidate.next_review_at = now_local() + timedelta(hours=delay)
        candidate.ignored_until = None
        candidate.decision_reason = f"信号尚不足，{delay} 小时后自动复查"
    else:
        candidate.status = KeywordCandidateStatus.ignore
        candidate.next_review_at = None
        candidate.ignored_until = now_local() + timedelta(days=get_settings().keyword_ignore_cooldown_days)
        candidate.decision_reason = "当前搜索需求或热度不足，进入冷却历史库"
    db.commit()
    return calls, became_hot


async def enrich_due_candidates() -> None:
    settings = get_settings()
    if settings.keyword_serpapi_daily_budget <= 0:
        return
    now = now_local()
    day_start = datetime.combine(now.date(), datetime.min.time())
    with SessionLocal() as db:
        used_today = db.scalar(select(func.count(KeywordSignalSnapshot.id)).where(
            KeywordSignalSnapshot.signal_type.in_(SERP_SIGNAL_TYPES),
            KeywordSignalSnapshot.captured_at >= day_start,
        )) or 0
        available_calls = settings.keyword_serpapi_daily_budget - used_today
        batch_size = min(settings.keyword_enrichment_batch_size, max(0, available_calls // 4))
        if batch_size <= 0:
            return
        candidates = db.scalars(
            select(KeywordCandidate)
            .where(
                (KeywordCandidate.status == KeywordCandidateStatus.discovered)
                | ((KeywordCandidate.status == KeywordCandidateStatus.hold) & (KeywordCandidate.next_review_at <= now))
                | ((KeywordCandidate.status == KeywordCandidateStatus.ignore) & (KeywordCandidate.ignored_until <= now))
            )
            .order_by(KeywordCandidate.total_score.desc(), KeywordCandidate.first_seen_at.desc())
            .limit(batch_size)
        ).all()
        client = SerpApiClient(db)
        new_hot: list[str] = []
        for candidate in candidates:
            try:
                _, became_hot = await enrich_candidate(db, candidate, client)
                if became_hot:
                    new_hot.append(f"{candidate.keyword}（{candidate.total_score} 分）")
            except SerpApiUnavailable as exc:
                candidate.decision_reason = f"等待可用 SerpAPI 额度池: {exc}"
                candidate.next_review_at = now + timedelta(hours=1)
                db.commit()
                break
            except Exception as exc:
                candidate.decision_reason = f"信号查询失败: {type(exc).__name__}: {exc}"[:2000]
                candidate.next_review_at = now + timedelta(hours=1)
                candidate.status = KeywordCandidateStatus.hold
                db.commit()
    # 本轮全部候选分析完后，把新晋 HOT 聚合成一条通知。
    if new_hot:
        title = f"关键词发现：本轮新晋 HOT {len(new_hot)} 个"
        body = "以下候选总分达到 HOT 阈值，值得优先跟进：\n\n- " + "\n- ".join(new_hot)
        with SessionLocal() as db:
            await notify(db, title, body)
