import hmac
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import AdminSession


SESSION_COOKIE = "backlink_manager_session"


def authenticate(username: str, password: str) -> bool:
    settings = get_settings()
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
        password, settings.admin_password
    )


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(token: str) -> str:
    secret = get_settings().session_secret
    return hashlib.sha256(f"{secret}:{token}".encode()).hexdigest()


def create_session(db: Session) -> str:
    now = _now_utc_naive()
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
    token = secrets.token_urlsafe(48)
    db.add(AdminSession(
        token_hash=_hash_token(token),
        expires_at=now + timedelta(days=get_settings().session_days),
    ))
    db.commit()
    return token


def delete_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AdminSession).where(AdminSession.token_hash == _hash_token(token)))
        db.commit()


def is_authenticated(request: Request, db: Session) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    session = db.get(AdminSession, _hash_token(token))
    if session is None:
        return False
    if session.expires_at <= _now_utc_naive():
        db.delete(session)
        db.commit()
        return False
    return True


def require_auth(request: Request, db: Session = Depends(get_db)) -> None:
    if not is_authenticated(request, db):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"},
        )


class CredentialCipher:
    def __init__(self, key: str | None = None) -> None:
        self._fernet = Fernet((key or get_settings().fernet_key).encode())

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("凭据无法解密，请检查 FERNET_KEY 是否与入库时一致") from exc

    def encrypt_json(self, value: dict[str, Any]) -> str | None:
        return self.encrypt(json.dumps(value, ensure_ascii=False)) if value else None

    def decrypt_json(self, value: str | None) -> dict[str, Any]:
        plaintext = self.decrypt(value)
        return json.loads(plaintext) if plaintext else {}
