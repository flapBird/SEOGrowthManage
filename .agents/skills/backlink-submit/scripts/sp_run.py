#!/usr/bin/env python3
"""SideProjectors 提交编排器：一个站点一条命令跑完 10 个阶段。

用法: python3 sp_run.py '<site.json>'
site.json 字段:
  project_id, url, name, pitch, description, markets: [..], screenshot, sproject_id(可选,已有草稿)

阶段: draft-fetch → 找草稿id → general字段+market1 → market2 → market3
      → Next+media上传+ADD+Next → built-with+3×Next+confirm勾选
      → API(task+prepared) → final Next → API(result)
每阶段独立调用 browser.py（会话隔离，跨会话靠服务端草稿 autosave）。
"""

import json
import subprocess
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from assets import resolve

BROWSER = ".venv/bin/python3 .agents/skills/backlink-submit/scripts/browser.py"
API = "python3 .agents/skills/backlink-submit/scripts/api.py"
BOOT = {"js": "(function(){return 'boot'})()", "wait_ms": 9000}


def run_browser(url, steps):
    tmp = "/tmp/sp_flow_steps.json"
    json.dump(steps, open(tmp, "w"))
    out = subprocess.run(f"{BROWSER} flow '{url}' {tmp}", shell=True,
                         capture_output=True, text=True, timeout=600)
    return [line for line in (out.stdout or "").strip().splitlines() if line]


def run_api(args):
    out = subprocess.run(f"{API} {args}", shell=True, capture_output=True, text=True, timeout=120)
    return (out.stdout or out.stderr or "").strip()


def next_btn(tag):
    return {"js": "(function(){var b=[].slice.call(document.querySelectorAll('button')).find(function(x){return /^%s$/i.test((x.innerText||'').trim())});if(b){b.click();return 'ok_%s'}return 'NO'})()" % (tag, tag), "wait_ms": 3500}


def market_pick(q, verify_tag_list):
    return [
        {"click": ".multiselect", "wait_ms": 900},
        {"type_into": ".multiselect__input", "text": q, "wait_ms": 1800},
        {"click": ".multiselect__option:not(.multiselect__option--disabled) >> nth=0", "wait_ms": 900},
        {"js": verify_tag_list, "wait_ms": 600},
    ]


TAGS_JS = "(function(){var tags=[].slice.call(document.querySelectorAll('.multiselect__tag')).map(function(t){return (t.innerText||'').trim()});return JSON.stringify(tags)})()"

JS_FETCH_EXPAND = "(function(){var cards=[].slice.call(document.querySelectorAll('div,h3,h4')).filter(function(e){return (e.innerText||'').indexOf('Fetch information from the project homepage')>-1&&e.innerText.length<120});if(!cards.length)return 'NO_CARD';cards[cards.length-1].click();return 'expanded'})()"
JS_SUBMIT_BTN = "(function(){var b=[].slice.call(document.querySelectorAll('button')).find(function(e){return /^submit$/i.test((e.innerText||'').trim())&&e.offsetParent!==null});if(!b)return 'NO_BTN';b.click();return 'clicked'})()"
JS_DRAFTS = "(function(){var ids=[];var as=document.querySelectorAll('a');for(var i=0;i<as.length;i++){var h=as[i].getAttribute('href')||'';var m=h.match(/\\/submit\\/project\\/(\\d+)\\/general/);if(m)ids.push(parseInt(m[1]))}return JSON.stringify(ids)})"
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


def main():
    global assets_dir
    cfg = json.loads(sys.argv[1])
    pid = cfg["project_id"]
    log = []
    a = resolve(cfg["url"])
    screenshot = (a["screenshots"] or [cfg.get("screenshot")])[0]
    icon = a["icon"]

    # 1. draft fetch（已有草稿时跳过）
    if not cfg.get("sproject_id"):
        steps = [dict(BOOT),
             {"js": JS_FETCH_EXPAND, "wait_ms": 1500},
             {"type_into": "input.input-standard >> visible=true", "text": cfg["url"], "wait_ms": 800},
             {"js": JS_SUBMIT_BTN, "wait_ms": 9000}]
        out = run_browser("https://www.sideprojectors.com/submit/shortcut/showcase", steps)
        log.append(f"1.fetch: {out[-1] if out else 'EMPTY'}")

    # 2. find draft id
    out = run_browser("https://www.sideprojectors.com/user/projects-search/drafts/created_at/desc/20/0",
                      [dict(BOOT), {"js": JS_DRAFTS, "wait_ms": 800}])
    ids = json.loads(out[-1]) if out and out[-1].startswith("[") else []
    spid = cfg.get("sproject_id") or (max(ids) if ids else None)
    if not spid:
        print(json.dumps({"site": cfg["name"], "status": "FAILED", "stage": "draft", "log": log}, ensure_ascii=False))
        return 1
    gurl = f"https://www.sideprojectors.com/submit/project/{spid}/general"
    log.append(f"2.draft: {spid}")

    # 3. general fields + markets（toggle 感知：选完验证，缺失重试）
    steps = [dict(BOOT),
             {"js": JS_FILL % json.dumps({"name": cfg["name"], "pitch": cfg["pitch"],
                                          "description": cfg["description"]}), "wait_ms": 1500}]
    if icon:
        steps += [{"upload": "input[type=file]", "files": [icon], "wait_ms": 1500}]
        log.append("3.logo: uploaded")
    out = run_browser(gurl, steps)
    log.append(f"3.general: {out[-1] if out else 'EMPTY'}")

    def pick_market(q):
        out = run_browser(gurl, [dict(BOOT)] + market_pick(q, TAGS_JS))
        try:
            return json.loads(out[-1]) if out and out[-1].startswith("[") else None
        except json.JSONDecodeError:
            return None
    for q in cfg["markets"][:3]:
        for attempt in (1, 2):
            tags = pick_market(q)
            if tags and any(q.split()[0].lower() in t.lower() for t in tags):
                log.append(f"market {q}: OK {tags}")
                break
            log.append(f"market {q}: retry {tags}")

    # 6. Next → media upload → ADD → Next（素材文件夹优先；screenshot-2 存在则连传）
    shots = [screenshot] + (a["screenshots"][1:2])
    steps = [dict(BOOT),
             next_btn("next")]
    for shot_file in shots:
        steps += [{"upload": "input[type=file]", "files": [shot_file], "wait_ms": 1200},
                  {"js": JS_ADD, "wait_ms": 1500},
                  {"js": JS_EMPTY, "wait_ms": 600}]
    steps += [next_btn("next"),
              {"js": "(function(){return JSON.stringify({url:location.href.slice(0,80)})})()", "wait_ms": 800}]
    out = run_browser(gurl, steps)
    log.append(f"6.media: {out[-3] if len(out) > 2 else 'EMPTY'} | {out[-1] if out else 'EMPTY'}")

    # 7. built-with + 3 Next + confirm checks
    steps = [dict(BOOT),
             {"click": ".multiselect >> nth=0", "wait_ms": 800},
             {"type_into": ".multiselect__input >> nth=0", "text": "javascript", "wait_ms": 1800},
             {"click": ".multiselect__option:not(.multiselect__option--disabled) >> nth=0", "wait_ms": 800},
             next_btn("next"), next_btn("next"), next_btn("next"),
             {"js": JS_CHECKS, "wait_ms": 1500},
             {"js": "(function(){return JSON.stringify({url:location.href.slice(0,80)})})()", "wait_ms": 800}]
    out = run_browser(f"https://www.sideprojectors.com/submit/project/{spid}/built-with", steps)
    log.append(f"7.steps345: {out[-2] if len(out) > 1 else 'EMPTY'} | {out[-1] if out else 'EMPTY'}")

    # 8. API task + prepared
    t = run_api(f"task-create --project {pid} "
                f"--url 'https://www.sideprojectors.com/submit/project/{spid}/general' "
                f"--target-url '{cfg['url']}' --anchor '{cfg['name']}' --note 'backlink-submit SP showcase'")
    try:
        task_id = json.loads(t)["id"]
    except (json.JSONDecodeError, KeyError):
        log.append(f"8.task FAILED: {t[:150]}")
        print(json.dumps({"site": cfg["name"], "status": "STOPPED_BEFORE_SUBMIT", "spid": spid, "log": log}, ensure_ascii=False))
        return 1
    run_api(f"prepared --project {pid} --task-id {task_id} --url 'https://www.sideprojectors.com/submit/project/{spid}/general' "
            f"--target '{cfg['url']}' --content '{cfg['name']}: {cfg['pitch']} Markets: {','.join(cfg['markets'][:3])}' "
            f"--website '{cfg['url']}' --anchor '{cfg['name']}' --message 'SP 6步向导填完,待最终Submit' > /dev/null")
    log.append(f"8.api: task={task_id}")

    # 9. final submit
    steps = [dict(BOOT),
             {"js": JS_CHECKS, "wait_ms": 1500},
             next_btn("next"),
             {"js": "(function(){return JSON.stringify({url:location.href.slice(0,90)})})()", "wait_ms": 1500}]
    out = run_browser(f"https://www.sideprojectors.com/submit/project/{spid}/confirm", steps)
    done = "done" in (out[-1] if out else "")
    log.append(f"9.final: {out[-1] if out else 'EMPTY'}")

    # 10. API result
    subs = run_api("history --limit 5")
    status = "submitted" if done else "unknown"
    if done:
        run_api(f"result --submission-id $(python3 -c \"import sys,json;sys.path.insert(0,'.agents/skills/backlink-submit/scripts');import api as A;c=A.load_config();c['project_id']={pid};print(next(s['id'] for s in A.call_api(c,'GET','/api/v1/submissions?projectId={pid}&limit=10') if s.get('taskId')=={task_id}))\") "
                f"--status pending --submission-url 'https://www.sideprojectors.com/submit/done/{spid}' "
                f"--message 'SideProjectors提交成功,under review 2-3天' --note 'SP批量流程' > /dev/null")
        log.append("10.result: pending")
    print(json.dumps({"site": cfg["name"], "status": "DONE" if done else "CHECK", "spid": spid,
                      "task": task_id, "log": log}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
