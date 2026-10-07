#!/usr/bin/env python3
"""Viesearch.com 批量提交编排器（免登录通用目录，仅需 Email）。
表单: Website URL* / Title(可选,自动抓取) / Description(可选) / Category(可选搜索) / Email*
策略: URL+Email 必填，Title/Description 用站点资料填(质量更好)，Category 留空。
用法: python3 viesearch_run.py [--only project_id ...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).parent
ROOT = SKILL.parents[3]
API = [str(ROOT / ".venv" / "bin" / "python3"), str(SKILL / "api.py")]
PROFILES = json.load(open(ROOT / "data" / "backlink_submit" / "site_profiles.json"))["sites"]
CONFIG = json.load(open(ROOT / "data" / "backlink_submit" / "config.json"))
EMAIL = CONFIG["contact_email"]
# 登录窗口开着时会锁主 profile；纯表单渠道用临时 profile 即可
PROFILE_DIR = Path(os.environ.get("SEO_CHROME_PROFILE", str(Path.home() / ".seo-chrome-profile")))

SUBMIT_URL = "https://viesearch.com/submit"
ALL_PIDS = ["4", "13", "14", "10", "11", "12", "7", "8", "9", "15", "2", "1", "6", "3"]


def api(*args: str) -> dict:
    r = subprocess.run(API + list(args), capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout or r.stderr)[:200]}


def main() -> int:
    only = set(sys.argv[2:]) if len(sys.argv) > 2 else None
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="chrome", headless=True,
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for pid in ALL_PIDS:
            if only and pid not in only:
                continue
            prof = PROFILES[pid]
            url, name = prof["url"], prof["name"]
            rec: dict = {"pid": pid, "site": name}
            try:
                chk = api("check", "--project", pid, "--url", SUBMIT_URL)
                if chk.get("exactSubmissionCount", 0) > 0:
                    rec["status"] = "skipped-duplicate"
                    out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
                    continue
                task = api("task-create", "--project", pid, "--url", SUBMIT_URL,
                           "--target-url", url, "--note", "viesearch free listing (email)")
                task_id = task.get("taskId") or task.get("id")
                if not task_id:
                    rec["status"] = "task-failed"; rec["err"] = json.dumps(task, ensure_ascii=False)[:120]
                    out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
                    continue

                page.goto(SUBMIT_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                page.locator('input[type=url]').first.fill(url, timeout=10000)
                page.get_by_placeholder("Custom title for your listing").fill(name, timeout=8000)
                page.get_by_placeholder("Custom description for your listing").fill(
                    (prof.get("short") or prof["tagline"])[:300], timeout=8000)
                page.locator('input[type=email]').first.fill(EMAIL, timeout=8000)
                prep = api("prepared", "--project", pid, "--task-id", str(task_id), "--url", SUBMIT_URL,
                           "--target", url, "--content", (prof.get("short") or prof["tagline"])[:200],
                           "--website", url, "--message", "viesearch: URL/Title/Description/Email 已填")
                page.get_by_role("button", name="Submit").click(timeout=10000)
                page.wait_for_timeout(6000)
                txt = page.inner_text("body").replace("\n", " ")
                low = txt.lower()
                if any(k in low for k in ("thank", "successfully", "has been submitted", "for review", "received")):
                    status = "submitted"
                elif any(k in low for k in ("already", "duplicate", "exists")):
                    status = "duplicate"
                elif any(k in low for k in ("error", "required", "invalid")):
                    status = "failed"
                else:
                    status = "unknown"
                sub_id = prep.get("submissionId") or prep.get("id")
                res = api("result", "--submission-id", str(sub_id), "--status", status,
                          "--message", txt[:180]) if sub_id else {"error": "no submission id"}
                rec.update({"task_id": task_id, "sub_id": sub_id, "status": status,
                            "final_url": page.url[:80], "snippet": txt[:180]})
            except Exception as exc:  # noqa: BLE001
                rec["status"] = "exception"; rec["err"] = str(exc)[:160]
            out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
        ctx.close()
    (ROOT / "data" / "backlink_submit" / "reports" / "viesearch-last-run.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    ok = sum(1 for r in out if r.get("status") == "submitted")
    print(f"DONE viesearch: {ok}/{len(out)} submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
