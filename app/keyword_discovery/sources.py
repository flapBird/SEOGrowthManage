from __future__ import annotations

import json
import gzip
from dataclasses import dataclass
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx

from ..models import KeywordSource, KeywordSourceType
from .normalizer import title_from_url


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 50_000


@dataclass(frozen=True)
class SourceEntry:
    title: str
    url: str | None = None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap_xml(content: bytes) -> tuple[list[SourceEntry], list[str]]:
    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)
    root = ElementTree.fromstring(content)
    root_name = _local_name(root.tag)
    entries: list[SourceEntry] = []
    child_sitemaps: list[str] = []
    if root_name == "sitemapindex":
        for node in root:
            location = next((child.text for child in node if _local_name(child.tag) == "loc"), None)
            if location:
                child_sitemaps.append(location.strip())
        return entries, child_sitemaps
    if root_name != "urlset":
        raise ValueError("仅支持标准 sitemap urlset 或 sitemapindex XML")
    for node in list(root)[:MAX_ITEMS]:
        location = next((child.text for child in node if _local_name(child.tag) == "loc"), None)
        if not location:
            continue
        image_title = next(
            (desc.text for desc in node.iter() if _local_name(desc.tag) in ("title", "caption") and desc.text),
            None,
        )
        entries.append(SourceEntry((image_title or title_from_url(location)).strip(), location.strip()))
    return entries, child_sitemaps


def parse_rss_xml(content: bytes) -> list[SourceEntry]:
    root = ElementTree.fromstring(content)
    entries: list[SourceEntry] = []
    for item in root.iter():
        if _local_name(item.tag) not in ("item", "entry"):
            continue
        title = next((child.text for child in item if _local_name(child.tag) == "title" and child.text), None)
        link_node = next((child for child in item if _local_name(child.tag) == "link"), None)
        link = None
        if link_node is not None:
            link = link_node.text or link_node.attrib.get("href")
        if title:
            entries.append(SourceEntry(title.strip(), link.strip() if link else None))
    return entries[:MAX_ITEMS]


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("来源响应超过 8MB 安全上限")
    return response.content


async def fetch_source_entries(source: KeywordSource) -> list[SourceEntry]:
    if not source.terms_confirmed:
        raise ValueError("尚未确认该来源允许自动访问")
    if not source.url:
        raise ValueError("来源 URL 为空")
    config = json.loads(source.config_json or "{}")
    headers = {"User-Agent": config.get("user_agent", "BacklinkManager-KeywordDiscovery/1.0")}
    async with httpx.AsyncClient(headers=headers) as client:
        content = await _download(client, source.url)
        if source.source_type == KeywordSourceType.trends_rss:
            return parse_rss_xml(content)
        if source.source_type != KeywordSourceType.sitemap:
            return []
        entries, child_sitemaps = parse_sitemap_xml(content)
        max_children = min(int(config.get("max_child_sitemaps", 20)), 100)
        for child_url in child_sitemaps[:max_children]:
            child_content = await _download(client, urljoin(source.url, child_url))
            child_entries, _ = parse_sitemap_xml(child_content)
            entries.extend(child_entries)
            if len(entries) >= MAX_ITEMS:
                break
        return entries[:MAX_ITEMS]
