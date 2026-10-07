#!/usr/bin/env python3
"""批量修复 SideProjectors 项目媒体：删 og-image 引用，上传真实截图。

用法: python3 fix_media.py  (内置 14 个项目清单)
验证: 修复后 img src 应包含 r2.dev/production（真上传存储路径）。
"""
import json
import os
import subprocess
import sys

BROWSER = f"{sys.executable} .agents/skills/backlink-submit/scripts/browser.py"
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from assets import resolve

# (SP项目id, 站点URL, 名称) —— 截图路径由 assets.py 按域名解析
PROJECTS = [
    (97552, "https://minecraftcirclegen.com/", "minecraftcirclegen"),
    (97568, "https://japanesenames.site/", "japanesenames"),
    (97569, "https://randompokemon.xyz/", "randompokemon"),
    (97574, "https://playbloo.net/", "playbloo"),
    (97577, "https://thefreakcircus.help/", "thefreakcircus"),
    (97581, "https://treeshateyou.help/", "treeshateyou"),
    (97598, "https://font-generators.org/", "fontgen"),
    (97602, "https://hotellobbyai.online/", "hotellobbyai"),
    (97605, "https://electrondash.site/", "electrondash"),
    (97609, "https://ships3d.xyz/", "ships3d"),
    (97611, "https://sprintergame.xyz/", "sprintergame"),
    (97612, "https://basketballbros.site/", "basketballbros"),
    (97613, "https://blobopera.xyz/", "blobopera"),
    (97614, "https://wrestlebros.xyz/", "wrestlebros"),
]
BOOT = {"js": "(function(){return 'boot'})()", "wait_ms": 11000}
JS_MEDIA_STATE = """(function(){
var dels=[].slice.call(document.querySelectorAll('button,a,div,span')).filter(function(e){return /^delete$/i.test((e.innerText||'').trim())&&e.offsetParent!==null});
var srcs=[];
var els=document.querySelectorAll('img,[style*="background-image"]');
for(var i=0;i<els.length;i++){
  var src=els[i].src||((getComputedStyle(els[i]).backgroundImage||'').match(/url\\("?([^")]+)"?\\)/)||['',''])[1];
  if(src&&src.indexOf('/img/logo')<0&&src.indexOf('googleusercontent')<0&&src.length>10)srcs.push(src.slice(0,80));
}
return JSON.stringify({deletes:dels.length,srcs:srcs.slice(0,2)});
})()"""
JS_DELETE = """(function(){
var del=[].slice.call(document.querySelectorAll('a,button')).find(function(e){return /^delete$/i.test((e.innerText||'').trim())&&e.offsetParent!==null});
if(!del)return 'NO_DELETE';
del.click();return 'deleted';
})()"""
JS_ADD = "(function(){var b=[].slice.call(document.querySelectorAll('a,button')).find(function(x){return /^add$/i.test((x.innerText||'').trim())&&x.offsetParent!==null});if(b){b.click();return 'add'}return 'NO_ADD'})()"
JS_SAVE = """(function(){
var b=[].slice.call(document.querySelectorAll('a,button')).find(function(x){return /save & publish later/i.test((x.innerText||'').trim())&&x.offsetParent!==null});
if(!b)return 'NO_SAVE';
b.click();return 'saved';
})()"""


def run_browser(url, steps):
    tmp = "/tmp/fix_media_steps.json"
    json.dump(steps, open(tmp, "w"))
    out = subprocess.run(f"{BROWSER} flow '{url}' {tmp}", shell=True,
                         capture_output=True, text=True, timeout=600)
    return [line for line in (out.stdout or "").strip().splitlines() if line]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for spid, site_url, name in PROJECTS:
        if only and only != name:
            continue
        a = resolve(site_url)
        if not a["screenshots"]:
            print(f"{spid} {name}: SKIP assets 无截图")
            continue
        shot = a["screenshots"][0]
        url = f"https://www.sideprojectors.com/submit/project/{spid}/media"
        state = run_browser(url, [dict(BOOT), {"js": JS_MEDIA_STATE, "wait_ms": 800}])
        state = state[-1] if state else "{}"
        state = json.loads(state[state.index("{"):]) if "{" in state else {}
        log = [f"before={state}"]
        # 删除旧的 og 引用（可能多个）
        for _ in range(3):
            if state.get("deletes", 0) > 0 or state.get("noImages"):
                out = run_browser(url, [dict(BOOT), {"js": JS_DELETE, "wait_ms": 1500},
                                        {"js": JS_MEDIA_STATE, "wait_ms": 800}])
                try:
                    line = out[-1]
                    state = json.loads(line[line.index("{"):])
                    log.append(f"del→{state}")
                    if state.get("deletes", 0) == 0:
                        break
                except Exception:
                    break
        # 上传真实截图（等 ajax-loader 转完再验证）
        out = run_browser(url, [dict(BOOT),
                                {"upload": "input[type=file]", "files": [shot], "wait_ms": 1500},
                                {"js": JS_ADD, "wait_ms": 2000},
                                {"js": JS_MEDIA_STATE, "wait_ms": 4000},
                                {"js": JS_MEDIA_STATE, "wait_ms": 4000},
                                {"js": JS_MEDIA_STATE, "wait_ms": 800}])
        try:
            line = out[-1]
            state = json.loads(line[line.index("{"):])
            log.append(f"upload→{state}")
        except Exception:
            log.append(f"upload=? {out[-1] if out else ''}")
        # 保存
        out = run_browser(url, [dict(BOOT), {"js": JS_SAVE, "wait_ms": 3000},
                                {"js": JS_MEDIA_STATE, "wait_ms": 1000}])
        try:
            line = out[-1]
            state = json.loads(line[line.index("{"):])
            log.append(f"save→{state}")
        except Exception:
            pass
        ok = any("r2.dev/production" in s for s in state.get("srcs", [])) if isinstance(state, dict) else False
        print(json.dumps({"spid": spid, "name": name, "ok": ok, "log": log}, ensure_ascii=False))


if __name__ == "__main__":
    main()
