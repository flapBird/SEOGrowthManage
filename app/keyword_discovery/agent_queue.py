from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..config import BASE_DIR, get_settings
from ..database import SessionLocal
from ..models import AgentBatch, KeywordCandidate, now_local
from .agent_filter import is_worth_agent_review
from .notify import notify


def _queue_root() -> Path:
    """Agent 队列根目录，固定在 data/ 卷下（容器 /app/data ↔ 宿主机 <repo>/data）。
    这是容器进程和宿主机 Agent 唯一共享的物理位置，交接文件必须落在这里。"""
    return BASE_DIR.parent / "data" / get_settings().agent_queue_dir


def _ensure_dirs() -> dict[str, Path]:
    """确保队列子目录存在，返回各目录路径。"""
    root = _queue_root()
    dirs = {
        "in_pending": root / "in" / "pending",
        "in_processed": root / "in" / "processed",
        "out_done": root / "out" / "done",
        "out_archived": root / "out" / "archived",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _atomic_write_json(path: Path, payload: dict) -> None:
    """原子写：先写 .tmp 再 rename，避免写到一半被读到损坏文件（移植脚本做法）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _candidate_scores(candidate: KeywordCandidate) -> dict:
    return {
        "total": candidate.total_score,
        "heat": candidate.heat_score,
        "freshness": candidate.freshness_score,
        "intent": candidate.intent_score,
        "competition": candidate.competition_score,
        "confidence": candidate.confidence_score,
    }


def _candidate_payload(candidate: KeywordCandidate) -> dict:
    """单个候选交给 Agent 的数据：足够它判断，但不泄露系统内部字段。"""
    return {
        "candidate_id": candidate.id,
        "keyword": candidate.keyword,
        "language": candidate.language,
        "country": candidate.country,
        "source_count": candidate.source_count,
        "scores": _candidate_scores(candidate),
    }


async def dispatch_due_to_agent() -> None:
    """定时任务：筛选值得送 Agent 的候选，攒一批写成 JSON 到 in/pending/。"""
    settings = get_settings()
    if not settings.agent_integration_enabled:
        return
    dirs = _ensure_dirs()
    with SessionLocal() as db:
        candidates = db.scalars(
            select(KeywordCandidate)
            .order_by(KeywordCandidate.total_score.desc(), KeywordCandidate.first_seen_at.desc())
            .limit(settings.agent_batch_size * 4)  # 多取一些，过滤后留足 batch_size
        ).all()
        worth = [c for c in candidates if is_worth_agent_review(c)][:settings.agent_batch_size]
        if not worth:
            return
        now = now_local()
        batch_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        in_path = dirs["in_pending"] / f"{batch_id}.json"
        payload = {
            "batch_id": batch_id,
            "created_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "candidates": [_candidate_payload(c) for c in worth],
        }
        _atomic_write_json(in_path, payload)
        db.add(AgentBatch(
            batch_id=batch_id,
            candidate_count=len(worth),
            in_path=str(in_path.relative_to(BASE_DIR.parent)),
            status="dispatched",
        ))
        db.commit()


def _build_agent_hot_body(new_hot: list[tuple[str, int | None, str | None]]) -> str:
    lines = ["Agent 综合判断（KD + 趋势）认为以下词值得优先跟进：", ""]
    for keyword, kd, reason in new_hot:
        kd_part = f"（KD {kd}）" if kd is not None else ""
        lines.append(f"- **{keyword}**{kd_part}：{reason or '无说明'}")
    return "\n".join(lines)


async def collect_agent_results() -> None:
    """定时任务：扫 out/done/，把 Agent 的判断写回数据库。幂等——已 collected 的批次跳过。"""
    settings = get_settings()
    if not settings.agent_integration_enabled:
        return
    dirs = _ensure_dirs()
    out_files = sorted(dirs["out_done"].glob("*.json"))
    if not out_files:
        return
    with SessionLocal() as db:
        for out_file in out_files:
            try:
                data = json.loads(out_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue  # 损坏的结果文件先跳过，不删，留待人工查看
            batch_id = data.get("batch_id") or out_file.stem
            batch = db.scalar(select(AgentBatch).where(AgentBatch.batch_id == batch_id))
            if batch is not None and batch.status == "collected":
                continue  # 已回收过，幂等跳过
            new_hot: list[tuple[str, int | None, str | None]] = []
            updated = 0
            for item in data.get("results", []):
                cid = item.get("candidate_id")
                candidate = db.get(KeywordCandidate, cid) if cid is not None else None
                if candidate is None:
                    continue
                candidate.agent_verdict = item.get("verdict")
                candidate.agent_kd = item.get("kd")
                candidate.agent_reason = item.get("reason")
                candidate.agent_judged_at = now_local()
                updated += 1
                if item.get("verdict") == "hot":
                    new_hot.append((candidate.keyword, item.get("kd"), item.get("reason")))
            # 归档结果文件。
            archived = dirs["out_archived"] / out_file.name
            try:
                out_file.replace(archived)
            except OSError:
                pass
            if batch is not None:
                batch.status = "collected"
                batch.collected_at = now_local()
                batch.out_path = str(archived.relative_to(BASE_DIR.parent)) if archived.exists() else None
                batch.message = f"回收 {updated} 个判断"
            db.commit()
            # Agent 判定的新晋 HOT 聚合推送（复用现有通知模块）。
            if new_hot:
                await notify(db, f"Agent 判定新晋 HOT {len(new_hot)} 个", _build_agent_hot_body(new_hot))
