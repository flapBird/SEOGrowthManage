#!/usr/bin/env python3
"""WebsiteLaunches.com 批量提交编排器（免登录，domain+Email 请求收录审核）。
表单: Domain* / Email*，其余站点信息由对方自动探测。
用法: python3 websitelaunches_run.py [--only project_id ...]
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

SUBMIT_URL = "https://websitelaunches.com/submit-site"
ALL_PIDS = sorted(PROFILES.keys(), key=lambda x: int(x) if x.isdigit() else 99)


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
                           "--target-url", url, "--note", "websitelaunches request review (email)")
                task_id = task.get("taskId") or task.get("id")
                if not task_id:
                    rec["status"] = "task-failed"; rec["err"] = json.dumps(task, ensure_ascii=False)[:120]
                    out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
                    continue
                page.goto(SUBMIT_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                page.locator('input[name=domain]').first.fill(domain, timeout=10000)
                page.locator('input[type=email]').first.fill(EMAIL, timeout=8000)
                prep = api("prepared", "--project", pid, "--task-id", str(task_id), "--url", SUBMIT_URL,
                           "--target", url, "--content", prof["tagline"][:200], "--website", url,
                           "--message", f"websitelaunches: domain={domain} + email 已填")
                page.get_by_text("Submit for Review", exact=False).first.click(timeout=10000)
                page.wait_for_timeout(6000)
                txt = page.inner_text("body").replace("\n", " ")
                low = txt.lower()
                # 注意: 导航有 "Request Site Review" 字样,不能拿 review 当成功信号
                listing_link = ""
                view = page.get_by_text("View listing", exact=False)
                if view.count() > 0:
                    try:
                        listing_link = page.locator("a", has_text="View listing").first.get_attribute("href") or ""
                    except Exception:  # noqa: BLE001
                        pass
                if "already been detected" in low:
                    status = "duplicate"
                elif any(k in low for k in ("thank", "success", "has been submitted", "we'll review", "will review", "queued")):
                    status = "submitted"
                elif any(k in low for k in ("error", "invalid", "required")):
                    status = "failed"
                else:
                    status = "unknown"
                sub_id = prep.get("submissionId") or prep.get("id")
                if sub_id:
                    api("result", "--submission-id", str(sub_id), "--status", status,
                        "--message", (listing_link + " " + txt[:160]).strip()[:180])
                rec.update({"task_id": task_id, "sub_id": sub_id, "status": status,
                            "listing": listing_link, "final_url": page.url[:80], "snippet": txt[:180]})
            except Exception as exc:  # noqa: BLE001
                rec["status"] = "exception"; rec["err"] = str(exc)[:160]
            out.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
        ctx.close()
    (ROOT / "data" / "backlink_submit" / "reports" / "websitelaunches-last-run.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    ok = sum(1 for r in out if r.get("status") == "submitted")
    print(f"DONE websitelaunches: {ok}/{len(out)} submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
