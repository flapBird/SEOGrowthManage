#!/usr/bin/env python3
"""静默浏览器 v2：CDP 只读导出登录态 → 无头 Chrome 注入，零打扰。

专用窗口(9222)仅作为登录态来源：连接 CDP 读取 cookies 属纯元数据读取，
不开标签页、不抢焦点。cookies 缓存到本地 jar，窗口关了也能继续跑。

用法:
    from silent_browser import launch
    with launch() as (ctx, page):
        ...  # 全程无头，用户不可见
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).parents[3]
JAR = ROOT / "data" / "backlink_submit" / "cookie_jar.json"
SILENT_PROFILE = Path.home() / ".seo-chrome-profile-silent"
CDP = "http://127.0.0.1:9222"
JAR_MAX_AGE = 12 * 3600  # jar 有效期12小时


def fetch_cookies_from_window() -> list[dict] | None:
    """从专用窗口 CDP 只读拉取 cookies（不开标签页）。失败返回 None。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(CDP)
            try:
                cookies = []
                for ctx in b.contexts:
                    cookies.extend(ctx.cookies())
                return cookies
            finally:
                b.close()
    except Exception:
        return None


def load_cookies() -> list[dict]:
    """优先从专用窗口拉取；失败则用本地 jar 缓存。"""
    fresh = fetch_cookies_from_window()
    if fresh:
        JAR.parent.mkdir(parents=True, exist_ok=True)
        JAR.write_text(json.dumps({"fetched_at": time.time(), "cookies": fresh},
                                  ensure_ascii=False), encoding="utf-8")
        return fresh
    if JAR.exists():
        try:
            data = json.loads(JAR.read_text(encoding="utf-8"))
            if time.time() - data.get("fetched_at", 0) < JAR_MAX_AGE:
                return data["cookies"]
        except Exception:
            pass
    return []


MAC_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")


@contextmanager
def launch(headless: bool = True, with_login: bool = True, offscreen: bool = False):
    """启动静默 Chrome，yield (context, page)。

    headless=True 默认无头；若站点 CF 拦无头，可 offscreen=True 有头但窗口
    定位到屏幕外（-32000,-32000），仍不干扰用户桌面。
    """
    from playwright.sync_api import sync_playwright
    args = ["--disable-blink-features=AutomationControlled",
            "--no-first-run", "--no-default-browser-check"]
    if offscreen:
        args += ["--window-position=-32000,-32000"]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(SILENT_PROFILE),
            channel="chrome",
            headless=headless,
            viewport={"width": 1440, "height": 900},
            user_agent=MAC_UA,
            args=args,
        )
        if with_login:
            cookies = load_cookies()
            if cookies:
                try:
                    ctx.add_cookies(cookies)
                except Exception:
                    pass
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            yield ctx, page
        finally:
            ctx.close()


if __name__ == "__main__":
    with launch() as (ctx, page):
        page.goto("https://substack.com/settings", wait_until="domcontentloaded", timeout=60000)
        for _ in range(8):
            page.wait_for_timeout(3000)
            txt = page.evaluate("() => document.body.innerText.replace(/\\s+/g,' ').slice(0,300)")
            if "Sign in" not in txt:
                break
        print(txt[:200])
