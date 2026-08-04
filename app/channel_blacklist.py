from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Channel, ChannelBlacklist


def normalize_blacklist_domain(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValueError("黑名单域名不能为空")
    cleaned = cleaned.removeprefix("*.").lstrip(".")
    parsed = urlsplit(cleaned if "://" in cleaned else f"//{cleaned}")
    host = (parsed.hostname or "").rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or " " in host:
        raise ValueError(f"无法识别域名: {value}")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2 or any(not label for label in labels):
        raise ValueError(f"请输入完整域名: {value}")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"域名格式无效: {value}") from exc


def channel_host(url: str) -> str:
    parsed = urlsplit(url if "://" in url else f"//{url}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def domain_matches(host: str, blocked_domain: str) -> bool:
    return host == blocked_domain or host.endswith(f".{blocked_domain}")


def matching_blacklist_entry(db: Session, url: str) -> ChannelBlacklist | None:
    host = channel_host(url)
    if not host:
        return None
    for entry in db.scalars(select(ChannelBlacklist).order_by(ChannelBlacklist.domain)).all():
        if domain_matches(host, entry.domain):
            return entry
    return None


def is_channel_blacklisted(db: Session, channel: Channel) -> bool:
    return matching_blacklist_entry(db, channel.url) is not None


def available_channels(db: Session) -> list[Channel]:
    channels = db.scalars(select(Channel).order_by(Channel.name)).all()
    return [channel for channel in channels if not is_channel_blacklisted(db, channel)]
