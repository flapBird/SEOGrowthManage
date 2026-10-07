#!/usr/bin/env python3
"""把 webcafe 免费外链清单分级：排除实际付费/需勋章，其余按票数分高/中/低三组。
输入: data/channels.json + data/backlink_submit/ledger.json
输出: data/backlink_submit/channel_tiers.json + channel_tiers.md
重跑: python3 build_tiers.py（ledger 更新后重跑即可刷新状态标注）
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[4]
SKILL_DATA = Path(__file__).parents[1] / "data"
DATA = ROOT / "data" / "backlink_submit"

chs = json.load(open(SKILL_DATA / "channels.json"))["channels"]
led = json.load(open(DATA / "ledger.json"))["channels"]

# ---- 排除规则 ----
BADGE_EXTRA = {"fazier.com": "用户规则:需在自己站点挂勋章"}          # 清单未标,用户实测
PAID_PROBED = {  # 实测免费通道不存在/实为付费
    "gptdemo.net": "实测:提交表单含 payment_method/amount 字段,免费通道实为付费",
    "aixploria.com": "实测:/en/add-ai/ 重定向到 featured 付费页",
    "microlaunch.net": "实测:/submit 重定向到 premium 定价页",
    "aitoolly.com": "实测:提交走付费包(Listing $49.99 起),免费通道不存在",
    "aitools.fyi": "实测:/submit 跳 Boost My Tool 付费代提交服务(Stripe 收卡),免费通道不存在",
}
BACKLINK_EXTRA = {  # 需先在自己站点挂对方链接(用户规则:同勋章类排除)
    "mossai.org": "实测:需先在自己网站挂 MossAI 链接才能提交,用户规则同勋章类",
}
USER_EXCLUDED = {  # 免费但不投:已提交过/风控严(保留在分组里,标注状态)
    "producthunt.com": "用户已自行提交,不重复投",
    "v2ex.com": "用户已自行提交,不重复投",
    "news.ycombinator.com": "用户规则:风控严",
    "dev.to": "用户规则:风控严",
    "reddit.com": "用户规则:风控严",
}

excluded, kept = {}, []
for c in chs:
    key, notes = c["key"], (c.get("notes") or "")
    if c.get("needs_badge") or re.search(r"徽章|勋章", notes):
        excluded[key] = {"reason": "需挂勋章", "note": notes, "votes": c["votes"], "name": c["name"]}
        continue
    if key in BADGE_EXTRA:
        excluded[key] = {"reason": BADGE_EXTRA[key], "note": notes, "votes": c["votes"], "name": c["name"]}
        continue
    if re.search(r"收费", notes) and not re.search(r"免费", notes):
        excluded[key] = {"reason": "清单标注收费", "note": notes, "votes": c["votes"], "name": c["name"]}
        continue
    if key in PAID_PROBED:
        excluded[key] = {"reason": PAID_PROBED[key], "note": notes, "votes": c["votes"], "name": c["name"]}
        continue
    if key in BACKLINK_EXTRA:
        excluded[key] = {"reason": BACKLINK_EXTRA[key], "note": notes, "votes": c["votes"], "name": c["name"]}
        continue
    kept.append(c)

# ---- 分组阈值: 高>=10 / 中 3-9 / 低<=2 ----
def tier(v):
    return "high" if v >= 10 else ("mid" if v >= 3 else "low")

# ---- 状态标注 ----
STATUS_ORDER = ["walked", "semi", "open", "needs_email", "needs_login", "needs_verify",
                "anti_bot", "probe_failed", "user_excluded", "no_url", "unprobed"]
STATUS_LABEL = {
    "walked": "✅已跑通", "semi": "◐半通", "open": "🟢免登录可直接走",
    "needs_email": "📧缺联系邮箱", "needs_login": "🔒需登录", "needs_verify": "🔍待人工确认",
    "anti_bot": "🛡️CF反爬(自动化被拦)",
    "probe_failed": "⚠️探测失败", "user_excluded": "⛔排除", "no_url": "−清单无URL", "unprobed": "未探测",
}

def status_of(key, c):
    if not c.get("url"):
        return "no_url", "清单未提供URL"
    if key == "sideprojectors.com":
        return "walked", "sp_run.py 编排器已固化,14站全铺,等审核"
    if key == "saashub.com":
        return "semi", "免登录匿名流程已固化;每人限1个匿名产品,名额已用,余下需注册"
    if key in USER_EXCLUDED:
        return "user_excluded", USER_EXCLUDED[key]
    l = led.get(key)
    if l:
        st, note = l.get("status") or "", l.get("note") or ""
        m = {"": "open", "needs_login": "needs_login", "needs_email": "needs_email",
             "needs_verify": "needs_verify", "failed": "probe_failed", "anti_bot": "anti_bot"}
        if st == "skipped":  # 区分真排除与"入口待确认/投稿制"
            if re.search(r"404|待确认|待站内", note):
                return "needs_verify", note
            if re.search(r"邮箱投稿|编辑投稿|投稿制", note):
                return "needs_email", note
            return "user_excluded", note or "台账标记跳过"
        return m.get(st, "unprobed"), note
    return "unprobed", ""

rows = []
for c in kept:
    st, note = status_of(c["key"], c)
    rows.append({
        "key": c["key"], "name": c["name"], "url": c.get("url", ""),
        "votes": c["votes"] or 0, "tier": tier(c["votes"] or 0),
        "category": c["category"], "paid_tier": bool(c.get("paid_tier")),
        "status": st, "status_label": STATUS_LABEL[st], "note": note,
        "fit": "仅工具站(游戏站不投)" if c["category"] == "ai-directory" else "",
    })

rows.sort(key=lambda r: (-r["votes"], r["key"]))
out = {
    "generated_at": "2026-09-30",
    "thresholds": {"high": "votes>=10", "mid": "3-9", "low": "<=2"},
    "excluded": excluded,
    "counts": {
        "total": len(chs), "excluded": len(excluded), "kept": len(kept),
        "high": sum(1 for r in rows if r["tier"] == "high"),
        "mid": sum(1 for r in rows if r["tier"] == "mid"),
        "low": sum(1 for r in rows if r["tier"] == "low"),
    },
    "channels": rows,
}
json.dump(out, open(DATA / "channel_tiers.json", "w"), ensure_ascii=False, indent=2)

# ---- Markdown ----
lines = ["# 免费外链渠道分级（排除付费/勋章后按票数分组）", "",
         f"- 数据源: channels.json 共 {len(chs)} 个; 排除 {len(excluded)} 个; 分组 {len(kept)} 个",
         "- 阈值: 高 ≥10票 / 中 3–9票 / 低 ≤2票", "",
         "## 排除清单（实际付费或需勋章）", "",
         "| 渠道 | 票 | 原因 |", "|---|---|---|"]
for k, v in sorted(excluded.items(), key=lambda kv: -(kv[1]["votes"] or 0)):
    lines.append(f"| {k} | {v['votes'] or 0} | {v['reason']} |")
for t, title in [("high", "高票（≥10）"), ("mid", "中票（3–9）"), ("low", "低票（≤2）")]:
    sub = [r for r in rows if r["tier"] == t]
    lines += ["", f"## {title} — {len(sub)} 个", "",
              "| 渠道 | 票 | 类型 | 状态 | 备注 |", "|---|---|---|---|---|"]
    for r in sub:
        fit = f" {r['fit']}" if r["fit"] else ""
        lines.append(f"| {r['key']}{fit} | {r['votes']} | {r['category']} | {r['status_label']} | {r['note'][:60]} |")
(DATA / "channel_tiers.md").write_text("\n".join(lines) + "\n")

print(f"total={len(chs)} excluded={len(excluded)} kept={len(kept)} "
      f"high={out['counts']['high']} mid={out['counts']['mid']} low={out['counts']['low']}")
print("\n排除:")
for k, v in sorted(excluded.items(), key=lambda kv: -(kv[1]['votes'] or 0)):
    print(f"  {k} ({v['votes'] or 0}票) — {v['reason']}")
print("\n状态分布:")
from collections import Counter
for st, n in sorted(Counter(r["status"] for r in rows).items(), key=lambda kv: -kv[1]):
    print(f"  {STATUS_LABEL[st]}: {n}")
print("\n高票组明细:")
for r in rows:
    if r["tier"] == "high":
        fit = f" [{r['fit']}]" if r["fit"] else ""
        print(f"  {r['votes']:>2}票 {r['key']}{fit} — {r['status_label']}")
