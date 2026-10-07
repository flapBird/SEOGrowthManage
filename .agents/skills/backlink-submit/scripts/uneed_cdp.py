#!/usr/bin/env python3
"""Uneed 批量提交（CDP 接管已登录窗口）。
流程: /submit-a-tool 填 name+url → Submit your product → 机器人抓取 → waiting-line
用法: python3 uneed_cdp.py <pid>...   (pid=1 只补记录不重提交)
"""
import json, subprocess, sys
from pathlib import Path

SKILL = Path(__file__).parent
ROOT = SKILL.parents[3]
API = [str(ROOT / ".venv" / "bin" / "python3"), str(SKILL / "api.py")]
PROFILES = json.load(open(ROOT / "data" / "backlink_submit" / "site_profiles.json"))["sites"]


def api(*args: str) -> dict:
    r = subprocess.run(API + list(args), capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout or r.stderr)[:150]}


def main() -> int:
    pids = sys.argv[1:]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = b.contexts[0]
        page = ctx.new_page()
        for pid in pids:
            prof = PROFILES[pid]
            rec = {"pid": pid, "site": prof["name"]}
            try:
                task = api("task-create", "--project", pid, "--url", "https://www.uneed.best/submit-a-tool",
                           "--target-url", prof["url"], "--note", "uneed submit-a-tool (logged in)")
                task_id = task.get("taskId") or task.get("id")
                if pid == "1":  # mcgen 已建工具 56506,只补记录
                    prep = api("prepared", "--project", pid, "--task-id", str(task_id),
                               "--url", "https://www.uneed.best/submit-a-tool", "--target", prof["url"],
                               "--content", prof["tagline"][:200], "--website", prof["url"],
                               "--message", "uneed 工具已建(waiting-line 56506),机器人抓取成功")
                    sub_id = prep.get("submissionId") or prep.get("id")
                    if sub_id:
                        api("result", "--submission-id", str(sub_id), "--status", "pending",
                            "--submission-url", "https://www.uneed.best/edit/waiting-line/56506",
                            "--message", "工具已入等待队列,免费排期 2027-01-19;可在后台 Schedule")
                    rec.update({"status": "recorded", "task": task_id, "sub": sub_id})
                    print(json.dumps(rec, ensure_ascii=False), flush=True)
                    continue
                page.goto("https://www.uneed.best/submit-a-tool", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                page.locator('input[name=name]').fill(prof["name"], timeout=10000)
                page.locator('input[name=url]').fill(prof["url"], timeout=8000)
                page.wait_for_timeout(2500)
                prep = api("prepared", "--project", pid, "--task-id", str(task_id),
                           "--url", "https://www.uneed.best/submit-a-tool", "--target", prof["url"],
                           "--content", prof["tagline"][:200], "--website", prof["url"],
                           "--message", "uneed: name+url 已填,机器人抓取")
                btn = page.locator("button", has_text="Submit your product").first
                btn.click(timeout=10000)
                page.wait_for_timeout(15000)
                url = page.url
                txt = page.inner_text("body").replace("\n", " ")
                if "/edit/waiting-line/" in url or "/edit/" in url:
                    status = "pending"
                elif any(k in txt.lower() for k in ("already", "duplicate", "exists")):
                    status = "duplicate"
                elif any(k in txt.lower() for k in ("error", "required", "invalid")):
                    status = "failed"
                else:
                    status = "unknown"
                tool_id = url.split("waiting-line/")[1].split("?")[0] if "waiting-line/" in url else ""
                sub_id = prep.get("submissionId") or prep.get("id")
                if sub_id:
                    api("result", "--submission-id", str(sub_id), "--status", status,
                        "--submission-url", url[:180],
                        "--message", f"uneed tool_id={tool_id} waiting-line;免费排期见后台" if tool_id else txt[:180])
                rec.update({"status": status, "tool": tool_id, "task": task_id, "sub": sub_id, "final": url[:80]})
            except Exception as exc:  # noqa: BLE001
                rec["status"] = "exception"; rec["err"] = str(exc)[:130]
            print(json.dumps(rec, ensure_ascii=False), flush=True)
        page.close()
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
