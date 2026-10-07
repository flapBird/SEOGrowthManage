#!/usr/bin/env python3
"""高/中票渠道发布入口 × 登录要求统计。
数据源: channel_tiers.json(分组) + 本文件 ENTRIES(2026-09-30/10-01 两轮探测结论)
输出: data/backlink_submit/channel_entries.json + channel_entries.md
重跑: python3 gen_entries.py
"""
import json
from pathlib import Path

DATA = Path(__file__).parents[4] / "data" / "backlink_submit"
tiers = json.load(open(DATA / "channel_tiers.json"))

# key: (入口, 是否登录, 验证码, 类型, 证据, 备注)
# login: yes/no/half/unknown(未到登录步骤就被拦)
# kind: walked|open-form|semi-open|login-form|content|anti-bot|editorial|dead|none
E = {
    # ---- 高票 ----
    "sideprojectors.com": ("/projects/new", "no", "no", "walked", "已跑通", "sp_run.py 编排器,14站全铺,等审核"),
    "saashub.com": ("/services/submit", "no(匿名限1)", "no", "open-form", "已跑通", "saashub_run.py;匿名名额已用,余下需注册"),
    "theresanaiforthat.com": ("/submit/", "unknown", "unknown", "anti-bot", "curl+浏览器", "免费提交手动审核;CF 拦无头,需真实浏览器/人工;仅工具站"),
    "toolify.ai": ("待确认(CF拦)", "unknown", "unknown", "anti-bot", "浏览器", "CF 反爬;仅工具站可投"),
    "github.com": ("github.com/new 仓库/Profile README", "yes", "no", "content", "常识", "仓库与 README 品牌引用"),
    "medium.com": ("medium.com/new-story", "yes", "no", "content", "常识", "发文"),
    "alternativeto.net": ("/add/", "unknown", "unknown", "anti-bot", "浏览器", "清单标注免费提交;CF 拦无头"),
    "promoteproject.com": ("Submit Startup → /login", "yes", "no", "login-form", "curl", "DR50;登录后还可发博客"),
    "indiehackers.com": ("无公开表单(/posts/new 已下线)", "yes", "unknown", "login-form", "浏览器", "发帖/产品需账号"),
    "peerlist.io": ("待确认(CF拦)", "yes(共识)", "unknown", "anti-bot", "浏览器", "Launchpad;CF 反爬"),
    "blogger.com": ("blogger.com 建站发文", "yes(Google)", "no", "content", "常识", ""),
    "crunchbase.com": ("公司资料页", "yes", "no", "content", "常识", "品牌主页"),
    "g2.com": ("/products/get-listed", "yes(商家)", "unknown", "login-form", "浏览器", "商家免费收录;页面反爬内容不可见"),
    "substack.com": ("substack.com 建专栏发文", "yes", "no", "content", "常识", ""),
    "topai.tools": ("/submit(存在性待确认)", "unknown", "unknown", "anti-bot", "curl+浏览器", "仅工具站;有付费位;CF 拦无头"),
    "uneed.best": ("/submit-a-tool", "yes(保存需注册)", "unknown", "login-form", "浏览器+实测", "免登录填名称+URL机器人抓取,保存/发布需注册;待用户注册后重跑"),
    # ---- 中票 ----
    "f6s.com": ("创建公司 profile(JS 应用)", "yes", "unknown", "login-form", "curl", "高DA创业平台"),
    "x.com": ("x.com/compose/post", "yes", "no", "content", "常识", ""),
    "getapp.com": ("商家收录(Gartner)", "yes(商家)", "unknown", "anti-bot", "浏览器", "CF 硬拦"),
    "aitoolsdirectory.com": ("/submit-tool", "no", "unknown", "semi-open", "浏览器", "人工审核;说明明确表单提交,字段需真实浏览器滚动确认"),
    "capterra.com": ("商家收录(Gartner)", "yes(商家)", "unknown", "anti-bot", "浏览器", "CF 硬拦"),
    "linkedin.com": ("动态/长文", "yes", "no", "content", "常识", ""),
    "tinylaunch.com": ("/submit", "yes", "no", "login-form", "curl", "Submit → auth/login 重定向"),
    "toolpilot.ai": ("/pages/submit-your-ai-tool", "no", "yes", "semi-open", "curl", "Shopify 联系表单(邮件型)"),
    "hashnode.com": ("发文", "yes", "no", "content", "常识", ""),
    "pinterest.com": ("建 Pin", "yes", "no", "content", "常识", ""),
    "quora.com": ("回答/文章", "yes", "unknown", "content", "常识", "自动化访问被 CF 拦"),
    "stackshare.io": ("List a Tool", "yes", "no", "login-form", "浏览器", ""),
    "trustpilot.com": ("商家点评页", "yes(商家)", "unknown", "anti-bot", "curl", "CF 拦无头"),
    "youtube.com": ("频道/视频", "yes", "no", "content", "常识", ""),
    "zhihu.com": ("专栏/回答", "yes", "no", "content", "常识", ""),
    "behance.net": ("作品项目", "yes(Adobe)", "no", "content", "常识", ""),
    "devhunt.org": ("Launch 按钮", "yes(GitHub)", "no", "login-form", "curl", ""),
    "launchtory.com": ("/projects/new", "yes", "yes", "login-form", "浏览器", "导航含 Login/Signup;首页有 reCAPTCHA"),
    "listedai.co": ("/submit", "no", "no", "semi-open", "curl", "开放表单,必填联系邮箱"),
    "saasaitools.com": ("/submit → /signup", "yes", "no", "login-form", "浏览器", ""),
    "saasworthy.com": ("待确认(CF拦)", "yes(推测商家)", "unknown", "anti-bot", "浏览器", ""),
    "sites.google.com": ("Google Sites 建站", "yes(Google)", "no", "content", "常识", ""),
    "slideshare.net": ("文档上传", "yes", "no", "content", "常识", ""),
    "stackoverflow.com": ("问答", "yes", "no", "content", "常识", "不适合硬推广"),
    "startupstash.com": ("/add-listing", "no", "yes", "semi-open", "curl", "CF7 表单+reCAPTCHA"),
    "turbo0.com": ("/submit → auth/login", "yes", "no", "login-form", "curl", ""),
    "aistage.net": ("/submit", "unknown", "unknown", "anti-bot", "浏览器", "有付费位;CF 拦无头"),
    "aitoolboard.com": ("表单公开可填,提交需账号(Submit→/login)", "yes", "no", "login-form", "浏览器+提交实测", "流程已固化 scripts/aitoolboard_run.py:名称/短/长描述/URL/截图上传/分类/免费pricing/Free Listing;登录后重跑 4 工具站"),
    "aitoolguru.com": ("—", "unknown", "unknown", "dead", "浏览器", "站点 522 宕机(2026-09-30/10-01)"),
    "aitools.fyi": ("—", "—", "—", "none", "浏览器+实测", "实测:/submit 跳 Boost My Tool 付费代提交服务(Stripe),免费通道不存在"),
    "aitools.neilpatel.com": ("无标准入口", "—", "—", "none", "curl", "仅 feedbear 功能投票板,非收录渠道"),
    "crozdesk.com": ("vendor.revleads.com/user/signup", "yes", "no", "login-form", "浏览器", "商家 portal 注册"),
    "eu-startups.com": ("pitch 邮件投稿", "no(邮件)", "—", "editorial", "浏览器", "CF 拦自动化;媒体站"),
    "financesonline.com": ("/add-product/", "no", "yes", "semi-open", "curl", "Ninja Forms+reCAPTCHA"),
    "gitbook.com": ("文档站", "yes", "no", "content", "常识", ""),
    "goodfirms.co": ("商家收录", "yes(推测)", "unknown", "anti-bot", "浏览器", "CF 拦无头"),
    "gravatar.com": ("头像资料带链接", "yes", "no", "content", "常识", ""),
    "huggingface.co": ("huggingface.co/new-space", "yes", "no", "content", "常识", "Space/Model 页"),
    "instagram.com": ("资料/帖子", "yes", "no", "content", "常识", ""),
    "juejin.cn": ("文章", "yes", "no", "content", "常识", ""),
    "launchingnext.com": ("待确认", "unknown", "unknown", "anti-bot", "浏览器", "请求验证页拦自动化"),
    "startupbase.io": ("/launch", "yes", "no", "login-form", "curl", "Submit → login 重定向"),
    "startupranking.com": ("/submit", "unknown", "unknown", "anti-bot", "浏览器", "CF 拦无头"),
    "tumblr.com": ("博客", "yes", "no", "content", "常识", ""),
    "viesearch.com": ("/submit", "no", "no", "semi-open", "浏览器+实测", "URL/标题/描述可自动抓取;必填 Email 是唯一阻塞,拿到邮箱即可全自动"),
    "wellfound.com": ("公司 profile", "yes", "no", "login-form", "curl", "AngelList 体系"),
    "wordpress.com": ("博客", "yes", "no", "content", "常识", ""),
    "facebook.com": ("主页", "yes", "no", "content", "常识", ""),
    "sourceforge.net": ("登录后建项目页", "yes", "unknown", "none", "浏览器", "仅适合开源软件,本批闭源站不适用;CF 硬拦"),
    "futurepedia.io": ("未发现公开提交入口(/submit 404)", "unknown", "unknown", "none", "curl", "有付费位;入口可能需登录或已关闭,待真实浏览器确认"),
}

# 用户已排除/无URL 的不做入口统计
SKIP_SURVEY = {"producthunt.com", "v2ex.com", "news.ycombinator.com", "dev.to", "reddit.com", "google"}

SECTION_ORDER = [
    ("walked", "✅ 已跑通"),
    ("open-form", "🟢 免登录开放表单（自动化主战场）"),
    ("semi-open", "◐ 免登录开始但有附加条件（验证码/需邮箱/保存需注册/待确认字段）"),
    ("login-form", "🔒 表单型需登录/注册"),
    ("content", "📝 内容型（发文/主页/仓库，均需账号）"),
    ("anti-bot", "🛡️ CF 反爬（无头自动化被拦，需真实浏览器或人工）"),
    ("editorial", "✉️ 编辑投稿（邮件 pitch）"),
    ("none", "⊘ 无标准入口/不适用"),
    ("dead", "⚠️ 站点故障"),
]
KIND_HEADER = {"walked": "渠道 | 票 | 入口 | 备注", "editorial": "渠道 | 票 | 入口 | 备注",
               "dead": "渠道 | 票 | 状态", "none": "渠道 | 票 | 状态"}

hm = [r for r in tiers["channels"] if r["tier"] in ("high", "mid")
      and r["key"] not in SKIP_SURVEY]
rows = []
missing = []
for r in hm:
    e = E.get(r["key"])
    if not e:
        missing.append(r["key"])
        continue
    entry, login, cap, kind, evid, note = e
    rows.append({**r, "entry": entry, "login": login, "captcha": cap,
                 "kind": kind, "evidence": evid, "note": note})

from collections import Counter
kc = Counter(r["kind"] for r in rows)
out = {
    "generated_at": "2026-10-01",
    "method": "curl 批量探测 + 无头 Chrome 只读复测(不登录/不填表/不提交) + 大平台常识核验",
    "scope": f"高票+中票 {len(hm)} 个(已排除付费/勋章/回挂链接)",
    "kind_counts": dict(kc),
    "channels": rows,
}
json.dump(out, open(DATA / "channel_entries.json", "w"), ensure_ascii=False, indent=2)

L = ["# 高/中票渠道发布入口 × 登录要求统计", "",
     f"- 范围: {out['scope']}", f"- 方式: {out['method']}",
     "| 类型 | 数量 |", "|---|---|"]
name_map = dict(SECTION_ORDER)
for k, n in sorted(kc.items(), key=lambda kv: -kv[1]):
    L.append(f"| {name_map.get(k, k).split(' ', 1)[1] if ' ' in name_map.get(k, k) else k} | {n} |")

for kind, title in SECTION_ORDER:
    sub = [r for r in rows if r["kind"] == kind]
    if not sub:
        continue
    L += ["", f"## {title} — {len(sub)} 个", ""]
    if kind in ("dead", "none"):
        L += ["| 渠道 | 票 | 状态 |", "|---|---|---|"]
        for r in sub:
            L.append(f"| {r['key']} | {r['votes']} | {r['note']} |")
    else:
        L += ["| 渠道 | 票 | 入口 | 登录 | 验证码 | 备注 |", "|---|---|---|---|---|---|"]
        for r in sorted(sub, key=lambda x: -x["votes"]):
            fit = "（仅工具站）" if r.get("fit") else ""
            L.append(f"| {r['key']}{fit} | {r['votes']} | {r['entry']} | {r['login']} | {r['captcha']} | {r['note']} |")

L += ["", "---", "",
      "说明: 探测全程未登录任何站点、未填写任何表单。'unknown' 表示在到达登录/验证步骤前已被 Cloudflare 拦截。",
      "低票组另有 websitelaunches.com(2票) 实测免登录开放表单 /submit-site。"]
(DATA / "channel_entries.md").write_text("\n".join(L) + "\n")
print(f"entries: {len(rows)} channels; missing={missing}")
print("kind counts:", dict(kc))
