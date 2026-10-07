#!/usr/bin/env python3
"""SideProjectors 单会话 CDP 版（接管专用窗口，10 阶段一页跑完）。

用法: python3 sp_run_cdp.py '<site.json>'   （字段同 sp_run.py）
与 sp_run.py 的差异: 全程 CDP 单页执行（不再靠 browser.py 无头子进程，
规避 SingletonLock 与无头会话被服务端拒绝的问题）；最后一步点
"Proceed with selection" 式的新流程按钮。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).parent
ROOT = SKILL.parents[3]
API = [str(ROOT / ".venv" / "bin" / "python3"), str(SKILL / "api.py")]
PROFILES = json.load(open(ROOT / "data/backlink_submit/site_profiles.json"))["sites"]


def run_api(args: str) -> str:
    out = subprocess.run(f"{API[0]} {API[1]} {args}", shell=True, capture_output=True, text=True, timeout=120)
    return (out.stdout or out.stderr or "").strip()


JS_FETCH_EXPAND = "(function(){var cards=[].slice.call(document.querySelectorAll('div,h3,h4')).filter(function(e){return (e.innerText||'').indexOf('Fetch information from the project homepage')>-1&&e.innerText.length<120});if(!cards.length)return 'NO_CARD';cards[cards.length-1].click();return 'expanded'})()"
JS_SUBMIT_BTN = "(function(){var b=[].slice.call(document.querySelectorAll('button')).find(function(e){return /^submit$/i.test((e.innerText||'').trim())&&e.offsetParent!==null});if(!b)return 'NO_BTN';b.click();return 'clicked'})()"
JS_DRAFTS = "(function(){var ids=[];var as=document.querySelectorAll('a');for(var i=0;i<as.length;i++){var h=as[i].getAttribute('href')||'';var m=h.match(/\\/submit\\/project\\/(\\d+)\\/general/);if(m)ids.push(parseInt(m[1]))}return JSON.stringify(ids)})"
JS_ADD = "(function(){var b=[].slice.call(document.querySelectorAll('a,button')).find(function(x){return /^add$/i.test((x.innerText||'').trim())&&x.offsetParent!==null});if(b){b.click();return 'add'}return 'NO_ADD'})()"
JS_EMPTY = "(function(){return 'empty:'+((document.body.innerText||'').indexOf('no images added')>-1)})()"
JS_CHECKS = """(function(){
var out=[];
var cb=[].slice.call(document.querySelectorAll('input[type=checkbox]')).find(function(c){return /declare|truthful/i.test(c.parentElement.innerText||'')});
if(cb&&!cb.checked){cb.click();out.push('declared')}
var cards=[].slice.call(document.querySelectorAll('div,section'));
var card=cards.find(function(e){return (e.innerText||'').indexOf('Also feature this on ComingUp')>-1&&e.innerText.length<400});
if(card){var cb2=card.querySelector('input[type=checkbox]');if(cb2&&!cb2.checked){cb2.click();out.push('comingup')}}
return JSON.stringify(out);
})()"""
JS_FILL = """(function(){
var cfg=%s;
var els=document.querySelectorAll('input,textarea,select,[contenteditable="true"]');
function labelOf(el){var l=el.closest('label');if(l)return l.innerText;var c=el.closest('div');if(c){var t=(c.previousElementSibling?c.previousElementSibling.innerText:'');if(!t&&c.parentElement)t=c.parentElement.innerText||'';return t||''}return ''}
function setVal(el,v){if(el.getAttribute('contenteditable')==='true'){el.focus();document.execCommand('selectAll',false,null);document.execCommand('insertText',false,v);el.dispatchEvent(new Event('input',{bubbles:true}));return}var proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:(el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype);Object.getOwnPropertyDescriptor(proto,'value').set.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));el.dispatchEvent(new Event('blur',{bubbles:true}))}
var out=[];
for(var i=0;i<els.length;i++){var lbl=labelOf(els[i]);
if(/type of project/i.test(lbl)&&els[i].tagName==='SELECT'&&els[i].value!=='website'){setVal(els[i],'website');out.push('type')}
if(/Project name/i.test(lbl)&&els[i].tagName==='INPUT'){setVal(els[i],cfg.name);out.push('name')}
if(/pitch/i.test(lbl)&&els[i].type==='text'){setVal(els[i],cfg.pitch);out.push('pitch')}
if(/Project description/i.test(lbl)){setVal(els[i],cfg.description);out.push('desc')}}
return JSON.stringify(out);
})()"""


def js_next(tag="next"):
    return ("(function(){var b=[].slice.call(document.querySelectorAll('button'))"
            ".find(function(x){return /^%s$/i.test((x.innerText||'').trim())});"
            "if(b){b.click();return 'ok_%s'}return 'NO'})()" % (tag, tag))


def main() -> int:
    cfg = json.loads(sys.argv[1])
    pid = str(cfg["project_id"])
    a = None
    try:
        a = json.loads(run_api(f"assets --project {pid}"))
    except Exception:
        pass
    assets = (a or {}).get("project", {}) if isinstance(a, dict) else {}
    screenshot = cfg.get("screenshot")
    icon = cfg.get("icon")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = ctx.new_page()
        log = []

        def js(js, wait=1500):
            out = page.evaluate(js)
            page.wait_for_timeout(wait)
            return out

        def goto(url, wait=9000):
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(wait)

        try:
            # 1. draft fetch
            if not cfg.get("sproject_id"):
                goto("https://www.sideprojectors.com/submit/shortcut/showcase")
                log.append("1.fetch: " + str(js(JS_FETCH_EXPAND, 1500)))
                page.locator('input.input-standard >> visible=true').first.fill(cfg["url"])
                page.wait_for_timeout(800)
                log.append("1.url: " + str(js(JS_SUBMIT_BTN, 9000)))

            # 2. draft id
            goto("https://www.sideprojectors.com/user/projects-search/drafts/created_at/desc/20/0", 3000)
            ids = json.loads(js(JS_DRAFTS, 800) or "[]")
            spid = cfg.get("sproject_id") or (max(ids) if ids else None)
            if not spid:
                print(json.dumps({"site": cfg["name"], "status": "FAILED", "stage": "draft", "log": log}, ensure_ascii=False))
                return 1
            gurl = f"https://www.sideprojectors.com/submit/project/{spid}/general"
            log.append(f"2.draft: {spid}")

            # 3. general fields + logo
            goto(gurl)
            log.append("3.general: " + str(js(JS_FILL % json.dumps(
                {"name": cfg["name"], "pitch": cfg["pitch"], "description": cfg["description"]}))))
            # description 兜底：改版后 desc 是无标签 contenteditable DIV
            desc_js = cfg["description"].replace("\\", "\\\\").replace('"', '\\"')
            log.append("3.desc: " + str(js(f"""(function(){{
                const ces = [...document.querySelectorAll('[contenteditable="true"]')].filter(e => {{
                    const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }});
                if (!ces.length) return 'NO_CE';
                const ce = ces[0];
                if (ce.innerText.trim().length > 50) return 'already';
                ce.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, "{desc_js}");
                return 'filled:' + ce.innerText.length;
            }})()""")))
            if icon:
                page.locator('input[type=file]').first.set_input_files(icon, timeout=10000)
                page.wait_for_timeout(1500)
                log.append("3.logo: uploaded")

            # 4. markets
            def pick_market(q):
                page.locator(".multiselect").first.click(timeout=8000)
                page.wait_for_timeout(900)
                page.locator(".multiselect__input").first.fill(q)
                page.wait_for_timeout(1800)
                page.locator(".multiselect__option:not(.multiselect__option--disabled) >> nth=0").click(timeout=8000)
                page.wait_for_timeout(900)
                raw = page.evaluate(
                    "(function(){var tags=[].slice.call(document.querySelectorAll('.multiselect__tag')).map(function(t){return (t.innerText||'').trim()});return JSON.stringify(tags)})()")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return []
            for q in cfg["markets"][:3]:
                for attempt in (1, 2):
                    tags = pick_market(q)
                    if tags and any(q.split()[0].lower() in t.lower() for t in tags):
                        log.append(f"market {q}: OK {tags}")
                        break
                    log.append(f"market {q}: retry {tags}")

            # 5. next → media → upload → next（UI 改版：直接 set_input_files，无 ADD 步骤）
            goto(gurl)
            js(js_next("next"), 2500)
            n_files = page.locator('input[type=file]').count()
            log.append(f"5.media_inputs: {n_files}")
            if n_files:
                page.locator('input[type=file]').first.set_input_files(cfg["screenshot"], timeout=10000)
                page.wait_for_timeout(2500)
            js(js_next("next"), 2500)

            # 6. built-with + 3 next + checks
            goto(f"https://www.sideprojectors.com/submit/project/{spid}/built-with")
            page.locator(".multiselect").first.click(timeout=8000)
            page.wait_for_timeout(800)
            page.locator(".multiselect__input >> nth=0").fill("javascript")
            page.wait_for_timeout(1800)
            page.locator(".multiselect__option:not(.multiselect__option--disabled) >> nth=0").click(timeout=8000)
            page.wait_for_timeout(800)
            js(js_next("next"), 2500)
            js(js_next("next"), 2500)
            js(js_next("next"), 2500)
            log.append("7.checks: " + str(js(JS_CHECKS, 1500)))

            # 8. API task + prepared
            t = run_api(f"task-create --project {pid} "
                        f"--url 'https://www.sideprojectors.com/submit/project/{spid}/general' "
                        f"--target-url '{cfg['url']}' --anchor '{cfg['name']}' --note 'backlink-submit SP showcase'")
            task_id = json.loads(t).get("id")
            if not task_id:
                log.append(f"8.task FAILED: {t[:150]}")
                print(json.dumps({"site": cfg["name"], "status": "STOPPED", "spid": spid, "log": log}, ensure_ascii=False))
                return 1
            run_api(f"prepared --project {pid} --task-id {task_id} --url 'https://www.sideprojectors.com/submit/project/{spid}/general' "
                    f"--target '{cfg['url']}' --content '{cfg['name']}: {cfg['pitch']}' "
                    f"--website '{cfg['url']}' --anchor '{cfg['name']}' "
                    f"--message 'SP showcase,待最终Submit'")
            log.append(f"8.api: task={task_id}")

            # 9. final confirm submit
            goto(f"https://www.sideprojectors.com/submit/project/{spid}/confirm")
            js(JS_CHECKS, 1500)
            final = js(js_next("next"), 4000)
            log.append(f"9.final: {final}")
            done = "done" in str(final) or "/submit/done/" in page.url

            # 10. result
            if done:
                subs_raw = run_api(f"history --project {pid} --limit 10")
                log.append("10.result: pending(written via result cmd)")
                print(json.dumps({"site": cfg["name"], "status": "DONE", "spid": spid,
                                  "task": task_id, "done_url": page.url[:90], "log": log}, ensure_ascii=False))
            else:
                print(json.dumps({"site": cfg["name"], "status": "CHECK", "spid": spid,
                                  "task": task_id, "log": log}, ensure_ascii=False))
            return 0
        finally:
            page.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
