"""itch.io 新游雷达的解析层：RSS 条目解析、详情页解析、关键词推导、质量评估。

所有函数都是纯函数（输入字节串/字符串，输出 dataclass），方便离线测试；
网络请求统一放在 fetcher.py。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

# 与 sources.py 的取舍一致：用浏览器 UA 避免 itch.io 前置 WAF 对脚本的误伤。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ItchFeedItem:
    """一条 itch RSS 条目。published_at 为东八区 naive 时间。"""

    url: str
    title: str
    cover_url: str | None = None
    description: str | None = None
    price: str | None = None
    published_at: datetime | None = None
    platforms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ItchGameDetail:
    """详情页解析结果；row 字段为信息面板 label -> 值文本列表。"""

    title: str | None = None
    author: str | None = None
    cover_url: str | None = None
    description: str | None = None
    status: str | None = None
    platforms: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    published_exact_at: datetime | None = None
    rows: dict[str, list[str]] = field(default_factory=dict)


def to_shanghai_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI).replace(tzinfo=None)


def normalize_game_url(url: str) -> str:
    """feed 的 guid/link 偶有尾斜杠与 query 差异，统一成 https://host/path 做去重键。"""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


def strip_html(text: str | None) -> str | None:
    if not text:
        return None
    plain = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", plain).strip() or None


def _parse_rss_datetime(raw: str | None) -> datetime | None:
    if not raw or not raw.strip():
        return None
    try:
        return to_shanghai_naive(parsedate_to_datetime(raw.strip()))
    except (TypeError, ValueError):
        return None


def parse_itch_rss(content: bytes) -> list[ItchFeedItem]:
    """解析 itch browse 页 .xml / feed/new.xml 的 RSS。字段缺失时全部容忍为 None。"""
    root = ElementTree.fromstring(content)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    items: list[ItchFeedItem] = []
    for node in root.iter():
        if local(node.tag) != "item":
            continue
        fields: dict[str, str] = {}
        for child in node:
            fields[local(child.tag)] = (child.text or "").strip()
        url = normalize_game_url(fields.get("guid") or fields.get("link"))
        if not url:
            continue
        title = fields.get("plaintitle") or fields.get("title") or ""
        platforms = [p for p in re.split(r"[|,]", fields.get("platforms", "")) if p.strip()]
        items.append(
            ItchFeedItem(
                url=url,
                title=title,
                cover_url=fields.get("imageurl") or None,
                description=strip_html(fields.get("description")),
                price=fields.get("price") or None,
                published_at=_parse_rss_datetime(fields.get("createdate") or fields.get("pubdate")),
                platforms=platforms,
            )
        )
    return items


def _parse_panel_datetime(raw: str | None) -> datetime | None:
    """详情页 Published 单元格里的 <abbr title="06 October 2026 @ 13:43 UTC">。"""
    if not raw:
        return None
    match = re.search(r"(\d{1,2}\s+\w+\s+\d{4})\s+@\s+(\d{1,2}:\d{2})", raw)
    if not match:
        return None
    try:
        value = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%d %B %Y %H:%M")
    except ValueError:
        return None
    return to_shanghai_naive(value.replace(tzinfo=ZoneInfo("UTC")))


def parse_game_page(html: str) -> ItchGameDetail:
    soup = BeautifulSoup(html, "html.parser")

    def meta_content(key: str) -> str | None:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        return (tag.get("content") or "").strip() or None if tag else None

    rows: dict[str, list[str]] = {}
    published_exact: datetime | None = None
    panel = soup.select_one(".info_panel_wrapper")
    if panel is not None:
        for tr in panel.select("tr"):
            cells = tr.find_all("td")
            if len(cells) != 2:
                continue
            label = cells[0].get_text(" ", strip=True)
            value_cell = cells[1]
            abbr = value_cell.find("abbr")
            if label.lower() == "published" and abbr is not None:
                published_exact = _parse_panel_datetime(abbr.get("title"))
            values = [a.get_text(" ", strip=True) for a in value_cell.find_all("a")]
            if not values:
                values = [value_cell.get_text(" ", strip=True)]
            rows[label] = [v for v in values if v]

    screenshots = [img.get("src", "") for img in soup.select(".screenshot_list img")]
    return ItchGameDetail(
        title=meta_content("og:title"),
        author=(rows.get("Author") or [None])[0],
        cover_url=meta_content("og:image"),
        description=strip_html(meta_content("og:description")),
        status=(rows.get("Status") or [None])[0],
        platforms=rows.get("Platforms", []),
        genres=rows.get("Genre", []),
        tags=rows.get("Tags", []),
        screenshots=[s for s in screenshots if s][:6],
        published_exact_at=published_exact,
        rows=rows,
    )


def evaluate_quality(
    *,
    cover_url: str | None,
    description: str | None,
    status: str | None,
    platforms: list[str],
) -> dict:
    """轻质量门槛：给出 pass/notes，供 UI 展示，不自动改状态（发布与否由人工决定）。"""
    notes: list[str] = []
    if not cover_url:
        notes.append("缺少封面图")
    if not description or len(description) < 30:
        notes.append("简介缺失或过短（少于 30 字符）")
    if status is not None and status not in ("Released", "Playable"):
        notes.append(f"未正式发布（{status}）")
    lowered = {p.lower() for p in platforms}
    if platforms and not lowered & {"html5", "web", "web (html)"}:
        notes.append("详情页平台未标注 HTML5，可能无法在浏览器游玩")
    return {"ok": not notes, "notes": notes}


def derive_keywords(title: str, tags: list[str], genres: list[str]) -> list[str]:
    """为交给外部 AI 的导出材料生成种子关键词：标题变体 + itch 原生标签/类型。

    标题变体是聚合站的经典搜索模式；itch 标签本身在 itch 站内有搜索页，
    可直接作为相关词。
    """
    title = (title or "").strip()
    phrases = [
        title,
        f"{title} online",
        f"{title} play online",
        f"{title} free game",
        f"{title} browser game",
    ]
    phrases.extend(t for t in tags if t)
    phrases.extend(g for g in genres if g)
    seen: set[str] = set()
    result: list[str] = []
    for phrase in phrases:
        key = phrase.strip().lower()
        if phrase.strip() and key not in seen:
            seen.add(key)
            result.append(phrase.strip())
    return result
