#!/usr/bin/env python3
"""demand-mining 运行结果校验 + 去重 + 落盘。

用法:
    python3 finalize_run.py <runs_dir>/<run_id>

输入:  <run_dir>/signals-raw.json
输出:  data/demand_signals/pending/<run_id>.json
       data/demand_signals/seen/signatures.txt  (7 天滑动窗口, 自动修剪)
stdout: 单行摘要 + 明细计数 (模型以本输出为准写日报)

去重键 = sha1(entity|source|source_url)。 Reddit 等带 URL 的信号天然唯一;
trend/suggest 这类无 URL 信号靠 7 天窗口抑制重复, 7 天后重现视为仍活跃、允许再次入库。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

VALID_TYPES = {
    "new_product", "complaint", "request", "alternative",
    "revenue", "hiring", "trend", "landing_page",
}
VALID_EMOTION = {"negative", "asking", "positive", "neutral"}
SEEN_WINDOW_DAYS = 7


def signature(signal: dict) -> str:
    key = f"{signal.get('entity', '').casefold().strip()}|{signal.get('source', '')}|{signal.get('source_url', '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def load_seen(path: Path) -> dict[str, str]:
    """返回 hash -> 'YYYY-MM-DD'，已修剪出窗口的旧条目。"""
    seen: dict[str, str] = {}
    if not path.exists():
        return seen
    cutoff = (date.today() - timedelta(days=SEEN_WINDOW_DAYS)).isoformat()
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] >= cutoff:
            seen[parts[0]] = parts[1]
    return seen


def main(run_dir: Path) -> int:
    run_dir = run_dir.resolve()
    raw_path = run_dir / "signals-raw.json"
    if not raw_path.exists():
        print(f"ERROR: 找不到 {raw_path}")
        return 1

    data = json.loads(raw_path.read_text(encoding="utf-8"))
    run_id = data.get("run_id") or run_dir.name
    signals = data.get("signals", [])

    demand_root = run_dir.parents[1]      # .../demand_signals/runs/<run_id> -> .../demand_signals
    pending_dir = demand_root / "pending"
    seen_path = demand_root / "seen" / "signatures.txt"
    pending_dir.mkdir(parents=True, exist_ok=True)
    seen_path.parent.mkdir(parents=True, exist_ok=True)

    marker = run_dir / ".finalized"
    out_path = pending_dir / f"{run_id}.json"
    if marker.exists() and out_path.exists():
        # 已定稿过的运行目录：seen 已记账，重跑只会全部判重。
        # 此时保留既有 pending 文件，只打印摘要，保证重复执行幂等。
        done = json.loads(out_path.read_text(encoding="utf-8"))
        d = done.get("dedup", {})
        print(f"ALREADY_FINALIZED pending={out_path}")
        print(f"输入 {d.get('input', '?')} → 保留 {d.get('kept', '?')}（单轮去重 {d.get('in_run_dup', '?')}，历史去重 {d.get('seen_dup', '?')}，无效 {d.get('invalid', '?')}）")
        return 0

    seen = load_seen(seen_path)

    kept: list[dict] = []
    in_run: set[str] = set()
    drops = {"invalid": 0, "in_run_dup": 0, "seen_dup": 0}
    for sig_item in signals:
        entity = str(sig_item.get("entity", "")).strip()
        if (
            sig_item.get("signal_type") not in VALID_TYPES
            or not entity
            or len(entity) > 300
            or (sig_item.get("emotion") and sig_item["emotion"] not in VALID_EMOTION)
        ):
            drops["invalid"] += 1
            continue
        h = signature(sig_item)
        if h in in_run:
            drops["in_run_dup"] += 1
            continue
        if h in seen:
            drops["seen_dup"] += 1
            continue
        in_run.add(h)
        kept.append(sig_item)

    data["signals"] = kept
    data["dedup"] = {
        "input": len(signals),
        "kept": len(kept),
        "invalid": drops["invalid"],
        "in_run_dup": drops["in_run_dup"],
        "seen_dup": drops["seen_dup"],
    }
    data["finalized_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    marker.touch()

    today = date.today().isoformat()
    for h in in_run:
        seen[h] = today
    seen_path.write_text(
        "\n".join(f"{h} {d}" for h, d in sorted(seen.items(), key=lambda kv: kv[1])) + "\n",
        encoding="utf-8",
    )

    out_path = pending_dir / f"{run_id}.json"
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out_path)

    by_type: dict[str, int] = {}
    for s in kept:
        by_type[s["signal_type"]] = by_type.get(s["signal_type"], 0) + 1
    status_lines = [
        f"  {s['source']}: {s['status']} items={s.get('items', 0)}" + (f" note={s['note']}" if s.get("note") else "")
        for s in data.get("site_status", [])
    ]

    print(f"OK pending={out_path}")
    print(f"输入 {len(signals)} → 保留 {len(kept)}（单轮去重 {drops['in_run_dup']}，历史去重 {drops['seen_dup']}，无效 {drops['invalid']}）")
    print("按类型: " + (", ".join(f"{k}={v}" for k, v in sorted(by_type.items())) or "无"))
    print("站点状态:")
    for line in status_lines:
        print(line)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python3 finalize_run.py <runs_dir>/<run_id>")
        sys.exit(2)
    target = Path(sys.argv[1])
    if target.name == "signals-raw.json":
        target = target.parent
    sys.exit(main(target))
