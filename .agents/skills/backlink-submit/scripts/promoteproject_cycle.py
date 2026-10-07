#!/usr/bin/env python3
"""PromoteProject 自动投票+铺站循环。
投 5 票(未投过的 startup)赚 5 积分 → 提交 1 个站 → 重复。
用法: python3 promoteproject_cycle.py  (提交顺序: 3,6,12,13,14)
"""
import json, subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[4]
PROFILES = json.load(open(ROOT / "data" / "backlink_submit" / "site_profiles.json"))["sites"]
CATS = {"3": "Entertainment and Media", "6": "Entertainment and Media", "12": "Entertainment and Media",
        "13": "Entertainment and Media", "14": "Entertainment and Media"}
QUEUE = ["3", "6", "12", "13", "14"]


def api(*a):
    r = subprocess.run([".venv/bin/python3", ".agents/skills/backlink-submit/scripts/api.py", *a],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"error": (r.stdout or r.stderr)[:150]}


def vote_five(page) -> int:
    voted = 0
    for pg_num in range(1, 8):
        if voted >= 5:
            break
        page.goto(f"https://www.promoteproject.com/startups?page={pg_num}",
                  wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(7000)
        rounds = 0
        while voted < 5 and rounds < 4:
            rounds += 1
            ids = page.evaluate("""() => Array.from(document.querySelectorAll('div[id^="1_"]'))
              .filter(d=>!d.className.includes('icon-thumb-voted')).map(d=>d.id).slice(0,8)""")
            for vid in ids:
                if voted >= 5:
                    break
                try:
                    loc = page.locator(f'div#{vid}')
                    loc.click(timeout=5000)
                    page.wait_for_timeout(2500)
                    now = page.evaluate(f"() => document.querySelector('#{vid}')?.className || ''")
                    if "voted" in now:
                        voted += 1
                        print(f"  vote {voted}/5: {vid} (page {pg_num})", flush=True)
                except Exception:
                    continue
            if voted < 5:
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2500)
    return voted


def submit_site(page, pid) -> dict:
    prof = PROFILES[pid]
    rec = {"pid": pid, "site": prof["name"]}
    task = api("task-create", "--project", pid, "--url", "https://www.promoteproject.com/submit-startup",
               "--target-url", prof["url"], "--note", "promoteproject (credits cycle)")
    task_id = task.get("taskId") or task.get("id")
    page.goto("https://www.promoteproject.com/submit-startup", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(8000)
    F = lambda n: page.locator(f'input[name="{n}"], textarea[name="{n}"]').first
    F("link").fill(prof["url"], timeout=8000)
    F("title").fill(prof["name"], timeout=8000)
    F("short_description").fill(prof["tagline"][:150], timeout=8000)
    F("full_description").fill((prof.get("short") or prof["tagline"])[:800], timeout=8000)
    F("tags").fill(", ".join(prof.get("keywords", [])[:3]), timeout=8000)
    F("total_employees").fill("1", timeout=8000)
    page.evaluate("""(raw) => {
      const cfg = JSON.parse(raw);
      const set = (n, txt) => { const s = document.querySelector(`select[name=${n}]`);
        const o = Array.from(s.options).find(o=>o.text.trim()===txt); if (o) { s.value=o.value; s.dispatchEvent(new Event('change',{bubbles:true})); } };
      set('category',cfg.cat); set('founded_year','2024'); set('country','United States of America');
    }""", json.dumps({"cat": CATS[pid]}))
    page.wait_for_timeout(1000)
    prep = api("prepared", "--project", pid, "--task-id", str(task_id), "--url",
               "https://www.promoteproject.com/submit-startup",
               "--target", prof["url"], "--content", prof["tagline"][:200], "--website", prof["url"],
               "--message", "promoteproject: 全字段已填(投票循环积分)")
    page.evaluate("""() => {
      const b = Array.from(document.querySelectorAll('button,input[type=submit]')).find(x=>/submit|publish/i.test((x.innerText||x.value||'')) && x.getBoundingClientRect().width>0);
      if (b) b.click();
    }""")
    page.wait_for_timeout(12000)
    ok = "save-link" in page.url
    txt = page.inner_text("body").replace("\n", " ")
    taken = "taken" in txt.lower()
    status = "submitted" if ok else ("failed" if taken else "unknown")
    sub_id = prep.get("submissionId") or prep.get("id")
    if sub_id:
        api("result", "--submission-id", str(sub_id), "--status", status, "--message", txt[:150])
    rec.update({"task": task_id, "sub": sub_id, "status": status, "taken": taken})
    return rec


def main():
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = b.contexts[0]
        user_tab = ctx.pages[-1]
        page = ctx.new_page()
        try:
            user_tab.bring_to_front()
        except Exception:
            pass
        for pid in QUEUE:
            print(f"== {pid} {PROFILES[pid]['name']}: 投票赚积分", flush=True)
            n = vote_five(page)
            print(f"  已投 {n} 票", flush=True)
            if n < 5:
                rec = {"pid": pid, "status": "insufficient-credits", "voted": n}
                print(json.dumps(rec, ensure_ascii=False), flush=True)
                continue
            try:
                rec = submit_site(page, pid)
            except Exception as e:
                rec = {"pid": pid, "status": "exception", "err": str(e)[:110]}
            print(json.dumps(rec, ensure_ascii=False), flush=True)
        page.close()
        b.close()


if __name__ == "__main__":
    main()
