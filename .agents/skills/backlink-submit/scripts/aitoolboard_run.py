#!/usr/bin/env python3
"""AIToolboard.com 批量提交编排器（免登录开放表单，Free Listing 待审通道）。

流程（SKILL.md 步骤 5-8）：线上建任务 → 填表(含截图上传) → prepared → 提交 → 判定结果回写。
用法: python3 aitoolboard_run.py [--only project_id ...]
分类映射与文案取自 site_profiles.json；截图取自 assets.py 解析（screenshot-1 优先）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).parent
sys.path.insert(0, str(SKILL))
from assets import resolve  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = SKILL.parents[3]  # scripts → backlink-submit → skills → .agents → 工作区根
API = [str(ROOT / ".venv" / "bin" / "python3"), str(SKILL / "api.py")]
PROFILES = json.load(open(ROOT / "data" / "backlink_submit" / "site_profiles.json"))["sites"]

SUBMIT_URL = "https://aitoolboard.com/submit"
# project_id → aitoolboard 分类选项文本（2026-10-01 实测下拉）
CATEGORY = {
    "15": "✨ Prompt Tools",      # hotellobbyai: AI 视频 prompt 生成器
    "4": "🎉 Fun",                # font-generators: 文本样式娱乐工具
    "2": "✍️ Writing",            # japanesenames: 取名/写作工具
    "1": "🎮 Gaming",             # mcgen: Minecraft 建筑工具
}
SITES = ["15", "4", "2", "1"]


def api(*args: str) -> dict:
    r = subprocess.run(API + list(args), capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout or r.stderr)[:200]}


def fill_and_submit(page, pid: str) -> dict:
    prof = PROFILES[pid]
    name, tagline = prof["name"], prof["tagline"]
    long_desc = prof.get("short") or prof.get("medium") or tagline
    url = prof["url"]
    tags = ", ".join(prof.get("keywords", [])[:5])

    page.goto(SUBMIT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    by_placeholder = {
        "e.g., ChatGPT": name,
        "Brief description in one sentence": tagline,
        "http://example.com or https://example.com": url,
        "AI, chatbot, automation": tags,
    }
    filled = []
    for ph, val in by_placeholder.items():
        loc = page.get_by_placeholder(ph)
        loc.fill(val, timeout=10000)
        filled.append(ph[:20])
    page.get_by_placeholder("Detailed description of your tool").fill(long_desc, timeout=10000)

    # 下拉：第 1 个=分类（按文本），第 2 个=定价(free)
    sels = page.locator("select")
    sels.nth(0).select_option(label=CATEGORY[pid], timeout=10000)
    sels.nth(1).select_option(value="free", timeout=10000)

    # 截图上传：页面上的 file input（可能隐藏），取第一个（Tool Image）
    shot = resolve(url)["screenshots"][0]
    files = page.locator("input[type=file]")
    n_files = files.count()
    upload_note = ""
    if n_files == 0:
        # 兜底：点击 "Click to upload" 触发 chooser
        with page.expect_file_chooser(timeout=8000) as fc:
            page.get_by_text("Click to upload").first.click(timeout=8000)
        fc.value.set_files(str(shot))
        upload_note = "via-chooser"
    else:
        files.nth(0).set_input_files(str(shot), timeout=15000)
        upload_note = f"input[0/{n_files}]"
    page.wait_for_timeout(2500)
    # 验证文件名已显示
    body_txt = page.inner_text("body")
    fname_ok = Path(shot).name in body_txt

    # Listing Type：Free Listing 单选
    page.get_by_text("Free Listing", exact=False).first.click(timeout=8000)
    page.wait_for_timeout(800)

    shot_path = f"/tmp/aitoolboard_{pid}_filled.png"
    page.screenshot(path=shot_path, full_page=False)

    task = api("task-create", "--project", pid, "--url", SUBMIT_URL,
               "--target-url", url, "--note", "aitoolboard free listing (auto)")
    if "taskId" not in task and "id" not in task:
        return {"pid": pid, "error": f"task-create failed: {json.dumps(task, ensure_ascii=False)[:150]}"}
    task_id = task.get("taskId") or task.get("id")

    prep = api("prepared", "--project", pid, "--task-id", str(task_id), "--url", SUBMIT_URL,
               "--target", url, "--workflow", "directory", "--content", tagline,
               "--website", url,
               "--message", f"填入: name/short/long/URL/category={CATEGORY[pid]}/pricing=free/tags/截图({upload_note})/Free Listing")

    page.get_by_role("button", name="Submit Tool").click(timeout=10000)
    page.wait_for_timeout(6000)
    result_txt = page.inner_text("body").replace("\n", " ")[:800]
    final_url = page.url
    low = result_txt.lower()
    if any(k in low for k in ("thank you", "successfully", "submitted", "review", "received")):
        status = "submitted"
    elif any(k in low for k in ("required", "error", "failed", "invalid")):
        status = "failed"
    else:
        status = "unknown"
    res = api("result", "--submission-id", str(prep.get("submissionId") or prep.get("id") or ""),
              "--status", status, "--message", result_txt[:180]) \
        if prep.get("submissionId") or prep.get("id") else {"error": "no submission id"}
    return {"pid": pid, "task_id": task_id, "prep": prep.get("submissionId") or prep.get("id"),
            "status": status, "final_url": final_url[:100], "upload": upload_note,
            "fname_ok": fname_ok, "result_api": res, "snippet": result_txt[:220]}


def main() -> int:
    only = set(sys.argv[2:]) if len(sys.argv) > 2 else None
    out = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(Path.home() / ".seo-chrome-profile"), channel="chrome", headless=True,
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for pid in SITES:
            if only and pid not in only:
                continue
            try:
                r = fill_and_submit(page, pid)
            except Exception as exc:  # noqa: BLE001
                r = {"pid": pid, "error": str(exc)[:200]}
            out.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
        ctx.close()
    (ROOT / "data" / "backlink_submit" / "reports" / "aitoolboard-last-run.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
