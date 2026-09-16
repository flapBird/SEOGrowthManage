#!/usr/bin/env python3
"""从 web.cafe 免费外链清单 Markdown 生成结构化 channels.json。

用法:
    python3 build_channels.py [清单.md路径] [输出.json路径]

默认输入 ~/Downloads/webcafe免费外链清单.md，
默认输出 本skill目录/../data/channels.json。

清单格式（web.cafe 悬赏帖导出）:
    ## 一、免费 · 5 票以上（社区公认主流）   <- 分节，决定 tier
    1. **Product Hunt** — https://producthunt.com/ · 72票
       - 免费，权重高，gsc收录              <- 缩进的注释行
    143. NavFolders — https://navfolders.com/（有付费位）

同名/同域名重复条目会合并（合并票数取最大、备注拼接、付费位标记取或）。
"""

from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

# 域名子串 -> 分类。匹配按顺序取第一个命中；未命中归 other。
CATEGORY_RULES: list[tuple[str, str]] = [
    # launch 发布平台
    ("producthunt", "launch"), ("fazier", "launch"), ("tinylaunch", "launch"),
    ("microlaunch", "launch"), ("betalist", "launch"), ("uneed", "launch"),
    ("devhunt", "launch"), ("launchingnext", "launch"), ("startupbuffer", "launch"),
    ("firsto", "launch"), ("sideprojectors", "launch"), ("launchtory", "launch"),
    ("launchclash", "launch"), ("launchitx", "launch"), ("deeplaunch", "launch"),
    ("superlaunch", "launch"), ("feedmystartup", "launch"), ("saassurf", "launch"),
    ("comingup", "launch"), ("promoteproject", "launch"), ("startupranking", "launch"),
    ("startupbase", "launch"), ("fastlaunch", "launch"), ("hunt0", "launch"),
    ("startups.fyi", "launch"), ("startuptracker", "launch"), ("betabound", "launch"),
    ("wellfound", "launch"), ("peerlist", "launch"), ("twelve.tools", "launch"),
    ("startupfa.me", "launch"), ("startupstash", "launch"), ("startuphub.ai", "launch"),
    ("f6s", "launch"), ("foundrlist", "launch"), ("aitoolsrecap", "launch"),
    ("websitelaunches", "launch"), ("toolfame", "launch"), ("geekwire", "launch"),
    # AI 目录
    ("theresanaiforthat", "ai-directory"), ("toolify", "ai-directory"),
    ("futurepedia", "ai-directory"), ("dang.ai", "ai-directory"), ("topai.tools", "ai-directory"),
    ("aitoolsdirectory", "ai-directory"), ("aixploria", "ai-directory"), ("gptdemo", "ai-directory"),
    ("listedai", "ai-directory"), ("turbo0", "ai-directory"), ("saasaitools", "ai-directory"),
    ("aistage", "ai-directory"), ("aitoolboard", "ai-directory"), ("aitoolguru", "ai-directory"),
    ("aitools.fyi", "ai-directory"), ("aitoolly", "ai-directory"), ("findly.tools", "ai-directory"),
    ("mossai", "ai-directory"), ("aiagentsdirectory", "ai-directory"), ("aitools.inc", "ai-directory"),
    ("ctrlalt", "ai-directory"), ("toolrain", "ai-directory"), ("toolscout", "ai-directory"),
    ("aitoolsguide", "ai-directory"), ("aitoolhunt", "ai-directory"), ("tools-ai.online", "ai-directory"),
    ("insidr.ai", "ai-directory"), ("aimarketing.directory", "ai-directory"),
    ("theaigeneration", "ai-directory"), ("aitoolsup", "ai-directory"), ("aifinderplus", "ai-directory"),
    ("dropyourai", "ai-directory"), ("theainavigator", "ai-directory"), ("startupaitools", "ai-directory"),
    ("aitogrow", "ai-directory"), ("tools.so", "ai-directory"), ("basedtools", "ai-directory"),
    ("thewarehouse.ai", "ai-directory"), ("faind.ai", "ai-directory"), ("superaitools.io", "ai-directory"),
    ("infrabase", "ai-directory"), ("inouts", "ai-directory"), ("gpte.ai", "ai-directory"),
    ("nologin.tools", "ai-directory"), ("aicompare", "ai-directory"), ("neuron.co.uk", "ai-directory"),
    ("frontendprompt", "ai-directory"), ("fundl.us", "ai-directory"), ("watcha.cn", "ai-directory"),
    ("anyfp", "ai-directory"), ("withai.top", "ai-directory"), ("ki-suche", "ai-directory"),
    ("cloudfindr", "ai-directory"), ("aimojo", "ai-directory"), ("theailibrary", "ai-directory"),
    ("brouseai", "ai-directory"), ("interestedinai", "ai-directory"), ("easywithai", "ai-directory"),
    ("maomu", "ai-directory"), ("iai88", "ai-directory"), ("myaiexp", "ai-directory"),
    ("navfolders", "ai-directory"), ("vuink", "ai-directory"), ("similarlabs", "ai-directory"),
    ("aitools.neilpatel", "ai-directory"), ("library.phygital.plus", "ai-directory"),
    ("llmstxt.site", "ai-directory"), ("aitools.online", "ai-directory"),
    # 软件目录/评论
    ("alternativeto", "software-directory"), ("saashub", "software-directory"),
    ("stackshare", "software-directory"), ("alternative.me", "software-directory"),
    ("openalternative", "software-directory"), ("sourceforge", "software-directory"),
    ("g2.com", "review"), ("capterra", "review"), ("getapp", "review"), ("trustpilot", "review"),
    ("saasworthy", "review"), ("crozdesk", "review"), ("goodfirms", "review"),
    ("trustradius", "review"), ("sitejabber", "review"), ("financesonline", "review"),
    ("tekpon", "review"), ("yelp", "review"), ("webwiki", "review"), ("bbb.org", "review"),
    ("hotfrog", "review"), ("brownbook", "review"), ("addonbiz", "review"),
    ("scamadviser", "review"), ("business-software.com", "review"), ("getlatka", "review"),
    ("digitalagencynetwork", "review"),
    # 博客/内容平台
    ("medium", "blog"), ("dev.to", "blog"), ("hashnode", "blog"), ("substack", "blog"),
    ("blogger.com", "blog"), ("wordpress", "blog"), ("tumblr", "blog"), ("bearblog", "blog"),
    ("write.as", "blog"), ("vocal.media", "blog"), ("telegra.ph", "blog"), ("hackernoon", "blog"),
    ("cnblogs", "blog"), ("csdn", "blog"), ("juejin", "blog"), ("qiita", "blog"),
    ("zhihu", "blog"), ("jianshu", "blog"), ("segmentfault", "blog"), ("gitbook", "blog"),
    ("notion.so", "blog"), ("sites.google.com", "blog"), ("webflow.io", "blog"),
    ("carrd", "blog"), ("weebly", "blog"),
    # 社区
    ("v2ex", "community"), ("reddit", "community"), ("news.ycombinator", "community"),
    ("indiehackers", "community"), ("stackoverflow", "community"), ("quora", "community"),
    ("forum.bubble", "community"), ("community.windy", "community"), ("community.ctrader", "community"),
    ("tapatalk", "community"), ("fandom", "community"), ("miraheze", "community"),
    ("wikihow", "community"), ("douban", "community"), ("disqus", "community"),
    ("humanornot", "other"),
    # 社交/视频/多媒体
    ("x.com", "social"), ("twitter", "social"), ("facebook", "social"), ("instagram", "social"),
    ("linkedin", "social"), ("pinterest", "social"), ("youtube", "social"), ("tiktok", "social"),
    ("threads", "social"), ("bsky.app", "social"), ("mastodon", "social"), ("vk.com", "social"),
    ("plurk", "social"), ("minds.com", "social"), ("t.me", "social"), ("xing", "social"),
    ("imgur", "social"), ("vimeo", "social"), ("dailymotion", "social"), ("soundcloud", "social"),
    ("podcasters.spotify", "social"), ("500px", "social"), ("flickr", "social"),
    # 代码/开发资产
    ("github", "repo"), ("gitlab", "repo"), ("bitbucket", "repo"), ("npmjs", "repo"),
    ("pypi", "repo"), ("replit", "repo"), ("codepen", "repo"), ("jsfiddle", "repo"),
    ("gitee", "repo"), ("huggingface", "repo"), ("kaggle", "repo"),
    ("marketplace.visualstudio", "repo"), ("addons.mozilla", "repo"), ("addons.opera", "repo"),
    ("code.market", "repo"),
    # 设计/灵感站
    ("land-book", "design"), ("godly.website", "design"), ("lapa.ninja", "design"),
    ("httpster", "design"), ("onepagelove", "design"), ("siteinspire", "design"),
    ("cssdesignawards", "design"), ("dribbble", "design"), ("behance", "design"),
    ("awwwards", "design"), ("deviantart", "design"), ("huntscreens", "design"),
    # 媒体/文档
    ("slashdot", "media"), ("eu-startups", "media"), ("techpluto", "media"),
    ("issuu", "media"), ("scribd", "media"), ("slideshare", "media"), ("dzen.ru", "media"),
    # 个人档案/书签
    ("about.me", "profile"), ("gravatar", "profile"), ("start.me", "profile"),
    ("solo.to", "profile"), ("taplink", "profile"), ("crunchbase", "profile"),
    ("business.google.com", "profile"), ("diigo", "profile"), ("raindrop", "profile"),
    ("tiermaker", "other"),
]

ENTRY_RE = re.compile(
    r"^(?P<idx>\d+)\.\s+(?:\*\*(?P<bold>.+?)\*\*|(?P<plain>.+?))\s+—\s+(?P<rest>.+)$"
)
NOTE_RE = re.compile(r"^\s+-\s+(?P<note>.+)$")
SECTION_RE = re.compile(r"^##\s+")


def classify(url: str) -> str:
    lower = url.lower()
    for needle, cat in CATEGORY_RULES:
        if needle in lower:
            return cat
    return "other"


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "unknown"


def parse(markdown_path: Path) -> list[dict]:
    tier = 3
    channels: list[dict] = []
    by_key: dict[str, dict] = {}

    for raw in markdown_path.read_text(encoding="utf-8").splitlines():
        line = html.unescape(raw.rstrip())
        if SECTION_RE.match(line):
            tier = 1 if "5 票以上" in line else 2 if "2–4 票" in line else 3
            continue
        entry = ENTRY_RE.match(line)
        if entry:
            rest = entry.group("rest").strip()
            paid = "（有付费位）" in rest or "(有付费位)" in rest
            rest = rest.replace("（有付费位）", "").replace("(有付费位)", "").strip()
            vote_m = re.search(r"·\s*(\d+)\s*票", rest)
            votes = int(vote_m.group(1)) if vote_m else None
            rest = re.sub(r"·\s*\d+\s*票", "", rest).strip(" ·")
            url_m = re.search(r"https?://[^\s·，,]+", rest)
            if url_m:
                url = url_m.group(0).rstrip("。").rstrip("/")
            else:
                url = ""
            name = (entry.group("bold") or entry.group("plain") or "").strip()
            host = ""
            if url:
                host = urlparse(url).netloc.removeprefix("www.").lower()
            key = host if host else slugify(name)
            ch = {
                "key": key,
                "name": name,
                "url": url,
                "votes": votes,
                "tier": tier,
                "paid_tier": paid,
                "needs_badge": False,
                "category": classify(url or name),
                "notes": "",
                "submit_url": "",
            }
            channels.append(ch)
            by_key.setdefault(key, ch)
            continue
        note = NOTE_RE.match(raw)
        if note and channels:
            prev = channels[-1]
            extra = note.group("note").strip()
            prev["notes"] = (prev["notes"] + "\n" + extra).strip() if prev["notes"] else extra
            if re.search(r"徽章|badge", extra, re.I):
                prev["needs_badge"] = True

    # 归并：无 URL 条目按名称并入对应域名条目（如两处 Capterra、StartupBase），
    # 其余按 key 去重（完整域名 key，避免 addons.* 等前缀误伤）。
    first_label_to_channel: dict[str, dict] = {}
    for ch in channels:
        if ch["url"]:
            first_label_to_channel.setdefault(ch["key"].split(".")[0], ch)

    merged: dict[str, dict] = {}

    def absorb(old: dict, new: dict) -> None:
        if old["votes"] is not None or new["votes"] is not None:
            votes = [v for v in (old["votes"], new["votes"]) if v is not None]
            old["votes"] = max(votes) if votes else None
        old["tier"] = min(old["tier"], new["tier"])
        old["paid_tier"] = old["paid_tier"] or new["paid_tier"]
        old["needs_badge"] = old["needs_badge"] or new["needs_badge"]
        if not old["url"] and new["url"]:
            old["url"], old["category"], old["key"] = new["url"], new["category"], new["key"]
        if new["notes"] and new["notes"] not in old["notes"]:
            old["notes"] = (old["notes"] + "\n" + new["notes"]).strip()

    for ch in channels:
        target_key = ch["key"]
        if not ch["url"] and ch["key"] in first_label_to_channel:
            target = first_label_to_channel[ch["key"]]
            absorb(target, ch)
            continue
        if target_key in merged:
            absorb(merged[target_key], ch)
        else:
            merged[target_key] = ch

    out = sorted(merged.values(), key=lambda c: (c["tier"], -(c["votes"] or 0), c["name"]))
    for i, ch in enumerate(out, 1):
        ch["id"] = i
    return out


def main() -> int:
    skill_dir = Path(__file__).resolve().parent.parent
    md_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads/webcafe免费外链清单.md"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else skill_dir / "data" / "channels.json"
    if not md_path.exists():
        print(f"输入清单不存在: {md_path}", file=sys.stderr)
        return 1
    channels = parse(md_path)
    payload = {
        "source": str(md_path),
        "source_bounty": "https://new.web.cafe/ask/bounty/wlhmhdaoqg",
        "generated_at": date.today().isoformat(),
        "count": len(channels),
        "status_vocabulary": [
            "submitted", "pending", "live", "duplicate", "rejected", "failed", "unknown",
            "needs_login", "needs_badge", "paid_only", "skipped",
        ],
        "channels": channels,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cats: dict[str, int] = {}
    for ch in channels:
        cats[ch["category"]] = cats.get(ch["category"], 0) + 1
    print(f"写入 {out_path}")
    print(f"共 {len(channels)} 个渠道（原始条目已按域名/名称合并）")
    print("分类分布:", json.dumps(cats, ensure_ascii=False))
    print("tier 分布:", json.dumps({str(t): sum(1 for c in channels if c['tier'] == t) for t in (1, 2, 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
