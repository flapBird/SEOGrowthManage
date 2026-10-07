#!/usr/bin/env python3
"""SaaSHub 提交编排器（免登录渠道，已跑通参考：minecraftcirclegen）。

用法: python3 saashub_run.py '<site.json>'
site.json: {"project_id":4, "url":"https://...", "name":"...", "cats":["gaming tools","games"]}
流程: /services/submit 填URL→Continue → 设名称 → 2个分类 → Free → Confirm
      → related-alternatives 页点 Submit Product → 完成并回写线上。
"""
import json
import subprocess
import sys

BROWSER = ".venv/bin/python3 .agents/skills/backlink-submit/scripts/browser.py"
API = "python3 .agents/skills/backlink-submit/scripts/api.py"
BOOT = {"js": "(function(){return 'boot'})()", "wait_ms": 8000}


def run_browser(url, steps):
    json.dump(steps, open("/tmp/saashub_flow.json", "w"))
    out = subprocess.run(f"{BROWSER} flow '{url}' /tmp/saashub_flow.json", shell=True,
                         capture_output=True, text=True, timeout=600)
    return [line for line in (out.stdout or "").strip().splitlines() if line]


def run_api(args):
    out = subprocess.run(f"{API} {args}", shell=True, capture_output=True, text=True, timeout=120)
    return (out.stdout or out.stderr or "").strip()


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


def cat_steps(cats):
    steps = []
    for q in cats[:2]:
        steps.append({"click": ".react-select__control >> nth=0", "wait_ms": 600})
        steps.append({"type_into": ".react-select__control >> nth=0", "text": q, "wait_ms": 3500})
        steps.append({"press": "Enter", "wait_ms": 1000})
    return steps


def main():
    cfg = json.loads(sys.argv[1])
    pid = cfg["project_id"]
    log = []

    # 1. 表单流程（单会话全程）
    steps = [dict(BOOT),
             {"js": "var cfg=" + json.dumps({"url": cfg["url"]}) + ";" + JS_URL_SUBMIT, "wait_ms": 8000},
             {"js": JS_SET_NAME % json.dumps(cfg), "wait_ms": 1500}]
    steps += cat_steps(cfg["cats"])
    steps += [{"js": JS_CLICK_FREE, "wait_ms": 1200},
              {"js": JS_CLICK_CONFIRM, "wait_ms": 6000},
              {"js": JS_STATE, "wait_ms": 1000}]
    out = run_browser("https://www.saashub.com/services/submit", steps)
    final = out[-1] if out else "{}"
    log.append(f"1.flow: {final[:180]}")

    body = final
    if "has already been taken" in body:
        log.append("RESULT: NAME_TAKEN")
        print(json.dumps({"site": cfg["name"], "status": "NAME_TAKEN", "log": log}, ensure_ascii=False))
        return
    if "NO_FORM" in body or "services/submit?url" in body:
        log.append("RESULT: FETCH_STUCK")
        print(json.dumps({"site": cfg["name"], "status": "FETCH_STUCK", "log": log}, ensure_ascii=False))
        return

    # 2. related-alternatives 页 → 点 Submit Product 完成提交
    if "related-alternatives" in body:
        out = run_browser(f"https://www.sideprojectors.com/x", [])  # 占位不执行
        out = run_browser("https://www.saashub.com/services/submit", [dict(BOOT),
                          {"js": "var cfg=1;" + JS_STATE, "wait_ms": 800}])
        # 直接在 related 页完成
        m = None
        for line in out:
            pass
        # 重新进 related 页（从 confirm 跳转的 URL 未知，改为用站点 slug 不可知 → 回到主流程：用上一步 session 已结束）
    # 简化：related 页的提交在原会话已完成——若 final url 仍是 related，则再点一次
    if "related-alternatives" in body:
        slug = body.split("related-alternatives/")[1].split("?")[0].split('"')[0]
        out = run_browser(f"https://www.saashub.com/related-alternatives/{slug}?flow=submit",
                          [dict(BOOT), {"js": JS_CLICK_SP, "wait_ms": 5000}, {"js": JS_STATE, "wait_ms": 1000}])
        final = out[-1] if out else final
        log.append(f"2.related: {final[:150]}")

    done = "/services" not in final and ("saashub.com" in final) and "already been taken" not in final
    # 3. 线上记录
    t = run_api(f"task-create --project {pid} --url 'https://www.saashub.com/services/new' "
                f"--target-url '{cfg['url']}' --anchor '{cfg['name']}' --note 'backlink-submit SaaSHub'")
    try:
        task_id = json.loads(t)["id"]
    except (json.JSONDecodeError, KeyError):
        log.append(f"3.task FAILED: {t[:120]}")
        print(json.dumps({"site": cfg["name"], "status": "API_FAIL", "log": log}, ensure_ascii=False))
        return
    listing = ""
    if "saashub.com/" in final:
        try:
            u = json.loads(final)["url"]
            if "/services" not in u:
                listing = u
        except Exception:
            pass
    run_api(f"prepared --project {pid} --task-id {task_id} --url 'https://www.saashub.com/services/new' "
            f"--target '{cfg['url']}' --content '{cfg['name']}: {','.join(cfg['cats'])}' "
            f"--website '{cfg['url']}' --anchor '{cfg['name']}' --message 'SaaSHub免登录直投,Free方案' >/dev/null")
    if done:
        run_api(f"result --project {pid} --status pending "
                f"--submission-id $(python3 -c \"import sys;sys.path.insert(0,'.agents/skills/backlink-submit/scripts');import api as A;c=A.load_config();c['project_id']={pid};print(next(s['id'] for s in A.call_api(c,'GET','/api/v1/submissions?projectId={pid}&limit=10') if s.get('taskId')=={task_id}))\") "
                f"--submission-url '{listing}' --message 'SaaSHub提交完成,待审核' --note 'Free方案,分类:{','.join(cfg['cats'])}' >/dev/null")
        log.append(f"3.result: pending listing={listing}")
    print(json.dumps({"site": cfg["name"], "status": "DONE" if done else "CHECK", "task": task_id,
                      "listing": listing, "log": log}, ensure_ascii=False))


if __name__ == "__main__":
    main()
