from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import ExtensionToken, now_local


TOKEN_PREFIX = "blx_"
Db = Annotated[Session, Depends(get_db)]


def hash_extension_token(token: str) -> str:
    secret = get_settings().session_secret
    return hashlib.sha256(f"extension:{secret}:{token}".encode()).hexdigest()


def issue_extension_token(
    db: Session,
    name: str,
    expires_at: datetime | None = None,
) -> tuple[ExtensionToken, str]:
    plaintext = f"{TOKEN_PREFIX}{secrets.token_urlsafe(40)}"
    model = ExtensionToken(
        name=name.strip() or "Chrome Extension",
        token_prefix=plaintext[:12],
        token_hash=hash_extension_token(plaintext),
        expires_at=expires_at,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model, plaintext


def require_extension_token(request: Request, db: Db) -> ExtensionToken:
    authorization = request.headers.get("Authorization", "")
    scheme, _, plaintext = authorization.partition(" ")
    if scheme.lower() != "bearer" or not plaintext.startswith(TOKEN_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少有效的 Extension Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = db.scalar(
        select(ExtensionToken).where(
            ExtensionToken.token_hash == hash_extension_token(plaintext.strip())
        )
    )
    now = now_local()
    if token is None or token.revoked_at is not None or (
        token.expires_at is not None and token.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Extension Token 无效、已过期或已撤销",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token.last_used_at is None or token.last_used_at <= now - timedelta(minutes=5):
        token.last_used_at = now
        db.commit()
    return token


ExtensionAuth = Annotated[ExtensionToken, Depends(require_extension_token)]

