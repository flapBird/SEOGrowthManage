from __future__ import annotations

import asyncio
import json
import gzip
from dataclasses import dataclass
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx

from ..config import get_settings
from ..models import KeywordSource, KeywordSourceType
from .normalizer import title_from_url


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 50_000
# 用常规浏览器 UA 而非自报家门的 bot UA：sitemap.xml 本就是给爬虫读的公开文件，但部分站点的
# WAF（如 Cloudflare）会无差别拦截“看起来像脚本”的请求。换浏览器 UA 是为了绕开这种误伤，
# 不是要伪装抓取非公开内容。来源的 config_json 可用 user_agent 覆盖此默认值。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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


async def _download_once(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("来源响应超过 8MB 安全上限")
    return response.content


async def download_with_retry(client: httpx.AsyncClient, url: str, retries: int | None = None) -> bytes:
    """带指数退避的下载：失败重试若干次，每次失败后退避 2*(attempt+1) 秒。
    移植自脚本 fetch_xml 的 3 次重试逻辑，异步版用 asyncio.sleep。"""
    max_attempts = retries if retries is not None else get_settings().keyword_fetch_max_retries
    last_exc: Exception | None = None
    for attempt in range(max_attempts + 1):
        try:
            return await _download_once(client, url)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            await asyncio.sleep(2 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def _gzip_safe(content: bytes) -> bytes:
    # 有些 .xml.gz 是静态压缩文件而非服务器动态 Content-Encoding，httpx 不会自动解压，
    # 要手动按魔数判断。
    if content[:2] == b"\x1f\x8b":
        return gzip.decompress(content)
    return content


async def _collect_urls(
    client: httpx.AsyncClient,
    sitemap_url: str,
    max_children: int,
    max_concurrency: int,
    request_delay: float,
    depth: int = 0,
) -> list[str]:
    """递归展开 sitemap（index 可嵌套，最多两层），返回所有页面 URL。
    子 sitemap 用 semaphore 限流并发抓取，兼顾速度与对目标服务器的礼貌。"""
    content = _gzip_safe(await download_with_retry(client, sitemap_url))
    root = ElementTree.fromstring(content)
    tag = _local_name(root.tag)
    locs = [
        child.text.strip()
        for child in root.iter()
        if _local_name(child.tag) == "loc" and child.text and child.text.strip()
    ]
    if tag == "urlset":
        return locs
    # sitemapindex：逐个并发展开子 sitemap。
    child_urls = locs[:max_children]
    semaphore = asyncio.Semaphore(max_concurrency)

    async def expand_child(child_url: str) -> list[str]:
        async with semaphore:
            if request_delay > 0:
                await asyncio.sleep(request_delay)
            child_content = _gzip_safe(await download_with_retry(client, urljoin(sitemap_url, child_url)))
            child_root = ElementTree.fromstring(child_content)
            child_tag = _local_name(child_root.tag)
            child_locs = [
                c.text.strip()
                for c in child_root.iter()
                if _local_name(c.tag) == "loc" and c.text and c.text.strip()
            ]
            if child_tag == "urlset":
                return child_locs
            if child_tag == "sitemapindex" and depth < 2:  # 极少数站点嵌套三层，防死循环
                return await _collect_urls(client, urljoin(sitemap_url, child_url), max_children, max_concurrency, request_delay, depth + 1)
            return []

    results = await asyncio.gather(*(expand_child(u) for u in child_urls), return_exceptions=True)
    flat: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        flat.extend(result)
        if len(flat) >= MAX_ITEMS:
            break
    return flat[:MAX_ITEMS]


def _sitemap_entries_from_locs(locs: list[str]) -> list[SourceEntry]:
    return [SourceEntry(title_from_url(loc).strip(), loc) for loc in locs[:MAX_ITEMS]]


async def fetch_source_entries(source: KeywordSource) -> list[SourceEntry]:
    if not source.terms_confirmed:
        raise ValueError("尚未确认该来源允许自动访问")
    if not source.url:
        raise ValueError("来源 URL 为空")
    config = json.loads(source.config_json or "{}")
    settings = get_settings()
    headers = {"User-Agent": config.get("user_agent", DEFAULT_USER_AGENT)}
    max_children = min(int(config.get("max_child_sitemaps", 50)), 300)
    max_concurrency = int(config.get("max_concurrency", settings.keyword_fetch_max_concurrency))
    request_delay = float(config.get("request_delay_seconds", settings.keyword_fetch_request_delay))
    async with httpx.AsyncClient(headers=headers) as client:
        content = _gzip_safe(await download_with_retry(client, source.url))
        if source.source_type == KeywordSourceType.trends_rss:
            return parse_rss_xml(content)
        if source.source_type != KeywordSourceType.sitemap:
            return []
        # sitemap：先解析顶层，若为 urlset 直接取条目；若为 index 走并发递归展开。
        root = ElementTree.fromstring(content)
        if _local_name(root.tag) == "urlset":
            entries, _ = parse_sitemap_xml(content)
            return entries
        locs = await _collect_urls(client, source.url, max_children, max_concurrency, request_delay)
        return _sitemap_entries_from_locs(locs)

