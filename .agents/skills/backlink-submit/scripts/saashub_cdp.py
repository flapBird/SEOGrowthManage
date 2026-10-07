#!/usr/bin/env python3
"""SaaSHub 批量提交（CDP 接管用户已登录的专用 Chrome，不再关窗口）。
流程: /services/submit 填URL→Continue → 名称 → 2分类(react-select) → Free → Confirm
      → related-alternatives 页 Submit Product → 回写线上(task/prepared/result pending)
用法: python3 saashub_cdp.py 2 15 3 6 ...   (project_id 列表)
NAME_TAKEN 时自动用 "<名称> Online" 重试一次。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).parent
ROOT = SKILL.parents[3]
API = [str(ROOT / ".venv" / "bin" / "python3"), str(SKILL / "api.py")]
PROFILES = json.load(open(ROOT / "data" / "backlink_submit" / "site_profiles.json"))["sites"]
CATS = {
    "4": ["fonts", "design tools"],
    "2": ["name generator", "writing tools"],
    "15": ["ai tools", "prompt generator"],
    "3": ["games", "random generator"],
    "6": ["games", "browser games"],
    "14": ["music", "games"],
    "13": ["games", "browser games"],
    "9": ["games", "browser games"],
    "12": ["games", "browser games"],
    "10": ["games", "browser games"],
    "11": ["games", "browser games"],
    "7": ["games", "gaming guides"],
    "8": ["games", "gaming guides"],
}

JS_URL_SUBMIT = """(function(){
var f=document.querySelector('input[name=url]');
if(!f)return 'NO_FIELD';
var p=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value');
p.set.call(f,cfg.url);
f.dispatchEvent(new Event('input',{bubbles:true}));
var bs=document.querySelectorAll('input[type=submit]');
for(var i=0;i<bs.length;i++){if(/^continue$/i.test((bs[i].value||'').trim())){bs[i].click();return 'continue_clicked'}}
return 'NO_BTN';
})()"""
JS_SET_NAME = """(function(){
var cfg=%s;
var n=document.querySelector('input[name="service[name]"]');
if(!n)return 'NO_FORM';
var p=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value');
p.set.call(n,cfg.name);n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}));
return 'name_set:'+n.value;
})()"""
JS_CLICK_FREE = "(function(){var els=[].slice.call(document.querySelectorAll('button')).filter(function(e){return /^\\s*Free\\s*$/.test((e.innerText||'').trim())&&e.offsetParent!==null});if(!els.length)return 'NO_FREE';els[0].click();return 'free'})()"
JS_CLICK_CONFIRM = "(function(){var c=[].slice.call(document.querySelectorAll('button')).find(function(b){return /^confirm$/i.test((b.innerText||'').trim())&&b.offsetParent!==null});if(!c)return 'NO_CONFIRM';c.click();return 'confirm'})()"
JS_CLICK_SP = "(function(){var a=[].slice.call(document.querySelectorAll('a')).find(function(x){return /^submit product$/i.test((x.innerText||'').trim())&&x.offsetParent!==null});if(!a)return 'NO_SP_LINK';a.click();return 'sp_clicked'})()"
JS_STATE = "(function(){return JSON.stringify({url:location.href.slice(0,110),body:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,320)})})()"


def api(*args: str) -> dict:
    r = subprocess.run(API + list(args), capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout or r.stderr)[:150]}


def submit_one(page, pid: str, name_override: str | None = None) -> dict:
    prof = PROFILES[pid]
    name = name_override or prof["name"]
    cats = CATS[pid]
    rec = {"pid": pid, "name": name}
    page.goto("https://www.saashub.com/services/submit", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    # 1) URL + Continue
    page.evaluate("var cfg=" + json.dumps({"url": prof["url"]}) + ";" + JS_URL_SUBMIT)
    # 2) 名称（站点 meta 抓取可能较慢，轮询等待表单出现）
    r = "NO_FORM"
    for _ in range(24):
        page.wait_for_timeout(5000)
        r = page.evaluate(JS_SET_NAME % json.dumps({"name": name}))
        if "NO_FORM" not in r:
            break
    if "NO_FORM" in r:
        rec["status"] = "FETCH_STUCK"; return rec
    # 3) 两个分类(react-select)
    for q in cats:
        page.locator(".react-select__control").first.click(timeout=8000)
        page.keyboard.type(q, delay=40)
        page.wait_for_timeout(3500)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
    # 4) Free → Confirm
    page.evaluate(JS_CLICK_FREE); page.wait_for_timeout(1200)
    page.evaluate(JS_CLICK_CONFIRM); page.wait_for_timeout(7000)
    st = json.loads(page.evaluate(JS_STATE))
    body = st["body"]
    if "has already been taken" in body:
        rec["status"] = "NAME_TAKEN"; return rec
    if "NO_FORM" in body or "services/submit?url" in st["url"]:
        rec["status"] = "FETCH_STUCK"; return rec
    # 5) related-alternatives → Proceed with selection（流程改版：底部 input[type=submit]）
    if "related-alternatives" in st["url"] or "related-alternatives" in body:
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.evaluate("""() => {
            const b = [...document.querySelectorAll('input[type=submit],button')]
                .find(e => /proceed with selection/i.test((e.value||e.innerText||'')));
            if (b) b.click();
        }""")
        page.wait_for_timeout(8000)
        st = json.loads(page.evaluate(JS_STATE))
    final_url = st["url"]
    done = "/services" not in final_url and "related-alternatives" not in final_url
    rec["final_url"] = final_url[:90]
    rec["status"] = "DONE" if done else "CHECK"
    return rec


def main() -> int:
    pids = sys.argv[1:]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = b.contexts[0]
        page = ctx.new_page()
        for pid in pids:
            prof = PROFILES[pid]
            try:
                r = submit_one(page, pid)
                if r.get("status") == "NAME_TAKEN":
                    r2 = submit_one(page, pid, name_override=prof["name"] + " Online")
                    r2["renamed"] = True
                    r = r2
                if r.get("status") in ("DONE", "CHECK"):
                    task = api("task-create", "--project", pid,
                               "--url", "https://www.saashub.com/services/new",
                               "--target-url", prof["url"], "--anchor", r.get("name", prof["name"]),
                               "--note", "SaaSHub logged-in submit")
                    task_id = task.get("taskId") or task.get("id")
                    prep = api("prepared", "--project", pid, "--task-id", str(task_id),
                               "--url", "https://www.saashub.com/services/new", "--target", prof["url"],
                               "--content", f"{r.get('name')}: {','.join(CATS[pid])}", "--website", prof["url"],
                               "--message", f"SaaSHub登录态提交,Free方案,分类:{','.join(CATS[pid])}")
                    sub_id = prep.get("submissionId") or prep.get("id")
                    if sub_id:
                        api("result", "--submission-id", str(sub_id), "--status", "pending",
                            "--submission-url", r.get("final_url", ""),
                            "--message", "SaaSHub提交完成,待审核")
                    r["task"] = task_id; r["sub"] = sub_id
            except Exception as exc:  # noqa: BLE001
                r = {"pid": pid, "status": "exception", "err": str(exc)[:150]}
            print(json.dumps(r, ensure_ascii=False), flush=True)
        page.close()
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
