#!/usr/bin/env python3
"""独立 Chrome 无头驱动（零打扰：不触碰用户正在使用的 Chrome）。

用 Playwright 驱动本机 Google Chrome 本体（channel="chrome"），
独立 user-data-dir（~/.seo-chrome-profile，登录态持久化），无窗口。

用法:
    browser.py open <url> [wait_ms]    # 打开页面，输出 JSON: {url,title}
    browser.py run <url> '<js>' [wait_ms]  # 导航后立即执行 JS（同一会话），输出结果
    browser.py flow <url> <steps.json> # 一次会话内顺序执行多步（页面状态连续）:
                                       #   steps.json = [{"js":"...","wait_ms":2000},...]
                                       #   每步输出一行 JSON 结果
    browser.py text <url> [max_chars]  # 输出 body innerText
    browser.py shot <url> <png路径> [fullpage=1|0]  # 打开页面并截图（提交资料用）
    browser.py quit                    # 关闭浏览器（登录态保留在 profile）

JS 约定：写成 IIFE 返回 JSON.stringify(...) 或字符串，不要换行。
页面加载后默认等 domcontentloaded + 固定 2.5s（SPA 渲染余量），wait_ms 参数可覆盖。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SKILL = Path(__file__).parent
PROFILE_DIR = Path(os.environ.get("SEO_CHROME_PROFILE", str(Path.home() / ".seo-chrome-profile")))
INJECT_COOKIES = os.environ.get("SEO_INJECT_COOKIES") == "1"


def _inject_cookies(ctx) -> int:
    """CDP 只读拉取专用窗口已解密 cookies 注入无头会话（不开标签页不抢焦点）。"""
    try:
        sys.path.insert(0, str(SKILL))
        from silent_browser import load_cookies
        cookies = load_cookies()
        if cookies:
            ctx.add_cookies(cookies)
            return len(cookies)
    except Exception as exc:
        print(json.dumps({"cookie_inject_err": str(exc)[:80]}), flush=True)
    return 0


def emit(result) -> None:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    try:
        parsed = json.loads(text)
        print(json.dumps(parsed, ensure_ascii=False) if not isinstance(parsed, str) else parsed)
    except (json.JSONDecodeError, TypeError):
        print(text)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "quit":
        print("ok")
        return 0

    from playwright.sync_api import sync_playwright

    url = sys.argv[2] if len(sys.argv) > 2 else None
    wait_ms = 2500
    js = None
    steps = None
    max_chars = 6000
    if cmd == "run":
        js = sys.argv[3]
        wait_ms = int(sys.argv[4]) if len(sys.argv) > 4 else 2500
    elif cmd == "flow":
        steps = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    elif cmd == "text":
        max_chars = int(sys.argv[3]) if len(sys.argv) > 3 else 6000

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=True,
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def goto(target: str) -> None:
            for attempt in (1, 2):
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=60000)
                    return
                except Exception:
                    if attempt == 2:
                        raise
                    page.wait_for_timeout(3000)

        try:
            if cmd == "open":
                goto(url)
                page.wait_for_timeout(wait_ms)
                print(json.dumps({"url": page.url, "title": page.title()},
                                 ensure_ascii=False))
            elif cmd == "run":
                goto(url)
                page.wait_for_timeout(wait_ms)
                emit(page.evaluate(js))
            elif cmd == "flow":
                goto(url)
                for step in steps:
                    page.wait_for_timeout(int(step.get("wait_ms", 800)))
                    if "choose_file" in step:
                        cf = step["choose_file"]
                        with page.expect_file_chooser(timeout=10000) as fc_info:
                            page.click(cf["trigger"], timeout=8000)
                        fc_info.value.set_files(cf["files"])
                        print(json.dumps({"chose_files": cf["files"]}, ensure_ascii=False))
                    elif "upload" in step:
                        page.set_input_files(step["upload"], step["files"], timeout=15000)
                        print(json.dumps({"uploaded": step["files"]}, ensure_ascii=False))
                    elif "click" in step:
                        page.click(step["click"], timeout=8000)
                        print(json.dumps({"clicked": step["click"]}, ensure_ascii=False))
                    elif "type_into" in step:
                        page.click(step["type_into"], timeout=8000)
                        page.keyboard.type(step["text"], delay=40)
                        if step.get("press"):
                            page.keyboard.press(step["press"])
                        print(json.dumps({"typed": step["text"][:40]}, ensure_ascii=False))
                    elif "press" in step:
                        page.keyboard.press(step["press"])
                        print(json.dumps({"pressed": step["press"]}, ensure_ascii=False))
                    elif "js" in step:
                        emit(page.evaluate(step["js"]))
            elif cmd == "text":
                goto(url)
                page.wait_for_timeout(wait_ms)
                print((page.inner_text("body") or "")[:max_chars])
            elif cmd == "shot":
                shot_path = sys.argv[3]
                full = (sys.argv[4] if len(sys.argv) > 4 else "1") == "1"
                goto(url)
                page.wait_for_timeout(max(wait_ms, 3500))
                Path(shot_path).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=shot_path, full_page=full)
                print(json.dumps({"saved": shot_path, "url": page.url}, ensure_ascii=False))
            else:
                print(f"未知命令: {cmd}", file=sys.stderr)
                return 2
        finally:
            ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
