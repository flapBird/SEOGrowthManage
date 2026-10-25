"""itch 对接 API 密钥的签发与校验：与 ExtensionToken 同一套模式，
数据库只存哈希、明文仅创建时显示一次、支持过期与撤销。

密钥来源有两处，命中任意一个即通过：
- 环境变量 ITCH_RADAR_API_KEY（.env），兼容早期部署方式；
- /itch 页面创建的 ItchApiKey（哈希落库）。
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import ItchApiKey, now_local


KEY_PREFIX = "itch_"
Db = Annotated[Session, Depends(get_db)]


def hash_itch_key(key: str) -> str:
    secret = get_settings().session_secret
    return hashlib.sha256(f"itch-api:{secret}:{key}".encode()).hexdigest()


def issue_itch_api_key(
    db: Session,
    name: str,
    expires_at: datetime | None = None,
) -> tuple[ItchApiKey, str]:
    plaintext = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    model = ItchApiKey(
        name=name.strip() or "PlayBloo Skill",
        key_prefix=plaintext[:12],
        key_hash=hash_itch_key(plaintext),
        expires_at=expires_at,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model, plaintext


def has_any_itch_key_source(db: Session) -> bool:
    """是否存在任何可用的密钥来源（环境变量或未撤销的页面密钥），
    用于区分 403「完全没配置」和 401「密钥不对」。"""
    if get_settings().itch_radar_api_key:
        return True
    return (
        db.scalar(
            select(ItchApiKey.id).where(ItchApiKey.revoked_at.is_(None)).limit(1)
        )
        is not None
    )


def require_itch_api_key(request: Request, db: Db) -> None:
    provided = request.headers.get("X-API-Key", "").strip()
    if not provided:
        authorization = request.headers.get("Authorization", "")
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = value.strip()

    settings = get_settings()
    if provided and settings.itch_radar_api_key and secrets.compare_digest(
        provided, settings.itch_radar_api_key
    ):
        return

    if provided and provided.startswith(KEY_PREFIX):
        api_key = db.scalar(
            select(ItchApiKey).where(ItchApiKey.key_hash == hash_itch_key(provided))
        )
        now = now_local()
        if api_key is not None and api_key.revoked_at is None and (
            api_key.expires_at is None or api_key.expires_at > now
        ):
            if api_key.last_used_at is None or api_key.last_used_at <= now - timedelta(minutes=5):
                api_key.last_used_at = now
                db.commit()
            return

    if not has_any_itch_key_source(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="服务端尚未配置任何 API 密钥：请在 /itch 页面「外部 API 密钥」中生成",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API Key 无效、已过期或已撤销",
    )
