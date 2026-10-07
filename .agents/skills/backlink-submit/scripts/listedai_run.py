#!/usr/bin/env python3
"""ListedAI.co 批量提交编排器（免登录 AI 工具目录，仅 Email）。
表单: name*/url*/shortDescription*/email* + description(长) + 标签勾选 + first/last name
用法: python3 listedai_run.py [--only project_id ...]
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
PROFILE_DIR = Path(os.environ.get("SEO_CHROME_PROFILE", str(Path.home() / ".seo-chrome-profile")))

SUBMIT_URL = "https://listedai.co/submit"
PIDS = ["15", "4", "2", "1"]


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
            viewport={"width": 1366, "height": 1200},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for pid in PIDS:
            if only and pid not in only:
                continue
            prof = PROFILES[pid]
            url = prof["url"]
            domain = url.split("//", 1)[1].rstrip("/")
            rec: dict = {"pid": pid, "site": prof["name"]}
            try:
                chk = api("check", "--project", pid, "--url", SUBMIT_URL)
                if chk.get("exactSubmissionCount", 0) > 0:
                    rec["status"] = "skipped-duplicate"
                    out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
                    continue
                task = api("task-create", "--project", pid, "--url", SUBMIT_URL,
                           "--target-url", url, "--note", "listedai free listing (email)")
                task_id = task.get("taskId") or task.get("id")
                if not task_id:
                    rec["status"] = "task-failed"; rec["err"] = json.dumps(task, ensure_ascii=False)[:120]
                    out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
                    continue
                page.goto(SUBMIT_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                page.locator('input[name=name]').first.fill(prof["name"], timeout=10000)
                page.locator('input[name=url]').first.fill(domain, timeout=8000)
                page.locator('input[name=shortDescription]').first.fill(prof["tagline"][:150], timeout=8000)
                page.locator('input[name=email]').first.fill(EMAIL, timeout=8000)
                long_desc = prof.get("medium") or prof.get("short") or prof["tagline"]
                page.locator('textarea[name=description]').first.fill(long_desc[:3000], timeout=8000)
                for tag in ("free", "no-signup-required"):
                    try:
                        page.locator(f'input[name={tag}]').first.check(timeout=4000)
                    except Exception:  # noqa: BLE001
                        pass
                page.locator('input[name=first-name]').first.fill("Leeswal", timeout=6000)
                page.locator('input[name=last-name]').first.fill("Lee", timeout=6000)
                # "You" 区第二个 email 也是必填
                page.locator('input[name=email]').nth(1).fill(EMAIL, timeout=6000)
                prep = api("prepared", "--project", pid, "--task-id", str(task_id), "--url", SUBMIT_URL,
                           "--target", url, "--content", prof["tagline"][:200], "--website", url,
                           "--message", "listedai: name/url/shortDescription/description/email×2 已填")
                # 真正的提交按钮 = 表单底部 type=submit（导航 "Submit" 是链接,点了会刷新清空表单）
                btn = page.locator('form button[type=submit]', has_text="Submit").first
                btn.scroll_into_view_if_needed(timeout=8000)
                btn.click(timeout=10000)
                page.wait_for_timeout(7000)
                txt = page.inner_text("body").replace("\n", " ")
                low = txt.lower()
                if any(k in low for k in ("thank", "success", "received", "review", "submitted", "queued")):
                    status = "submitted"
                elif any(k in low for k in ("already", "duplicate", "exists")):
                    status = "duplicate"
                elif any(k in low for k in ("error", "invalid", "required")):
                    status = "failed"
                else:
                    status = "unknown"
                sub_id = prep.get("submissionId") or prep.get("id")
                if sub_id:
                    api("result", "--submission-id", str(sub_id), "--status", status, "--message", txt[:180])
                rec.update({"task_id": task_id, "sub_id": sub_id, "status": status,
                            "final_url": page.url[:80], "snippet": txt[:200]})
            except Exception as exc:  # noqa: BLE001
                rec["status"] = "exception"; rec["err"] = str(exc)[:160]
            out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
        ctx.close()
    (ROOT / "data" / "backlink_submit" / "reports" / "listedai-last-run.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    ok = sum(1 for r in out if r.get("status") == "submitted")
    print(f"DONE listedai: {ok}/{len(out)} submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
