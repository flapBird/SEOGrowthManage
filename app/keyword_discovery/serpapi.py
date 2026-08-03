from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SerpApiPool, now_local
from ..security import CredentialCipher


class SerpApiUnavailable(RuntimeError):
    pass


def _pool_ordering():
    return (
        SerpApiPool.priority.asc(),
        SerpApiPool.quota_remaining.desc().nullslast(),
        SerpApiPool.last_used_at.asc().nullsfirst(),
    )


class SerpApiClient:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.cipher = CredentialCipher()

    def pools(self) -> list[SerpApiPool]:
        return list(self.db.scalars(
            select(SerpApiPool)
            .where(SerpApiPool.enabled.is_(True), (SerpApiPool.quota_remaining.is_(None)) | (SerpApiPool.quota_remaining > 0))
            .order_by(*_pool_ordering())
        ).all())

    async def search(self, **params: Any) -> tuple[dict[str, Any], int]:
        pools = self.pools()
        if not pools:
            raise SerpApiUnavailable("没有可用的 SerpAPI 额度池")
        last_error = "所有额度池均不可用"
        async with httpx.AsyncClient(timeout=45) as client:
            for pool in pools:
                api_key = self.cipher.decrypt(pool.encrypted_api_key)
                try:
                    response = await client.get(
                        "https://serpapi.com/search.json",
                        params={**params, "api_key": api_key},
                    )
                    payload = response.json()
                    if response.status_code in (401, 403, 429):
                        pool.consecutive_failures += 1
                        pool.last_error = str(payload.get("error") or f"HTTP {response.status_code}")[:1000]
                        if response.status_code == 429:
                            pool.quota_remaining = 0
                        self.db.commit()
                        last_error = pool.last_error
                        continue
                    response.raise_for_status()
                    if payload.get("error"):
                        raise RuntimeError(str(payload["error"]))
                    pool.last_used_at = now_local()
                    pool.consecutive_failures = 0
                    pool.last_error = None
                    if pool.quota_remaining is not None:
                        pool.quota_remaining = max(0, pool.quota_remaining - 1)
                    self.db.commit()
                    return payload, pool.id
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    pool.consecutive_failures += 1
                    pool.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                    self.db.commit()
                    last_error = pool.last_error
        raise SerpApiUnavailable(last_error)

    async def refresh_pool(self, pool: SerpApiPool) -> None:
        api_key = self.cipher.decrypt(pool.encrypted_api_key)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get("https://serpapi.com/account.json", params={"api_key": api_key})
                payload = response.json()
                response.raise_for_status()
            pool.quota_limit = payload.get("searches_per_month")
            pool.quota_remaining = payload.get("total_searches_left", payload.get("plan_searches_left"))
            renewal = payload.get("plan_renewal_date")
            pool.renewal_at = datetime.fromisoformat(renewal) if renewal else None
            pool.last_checked_at = now_local()
            pool.consecutive_failures = 0
            pool.last_error = None
        except Exception as exc:
            pool.consecutive_failures += 1
            pool.last_checked_at = now_local()
            pool.last_error = f"额度查询失败: {type(exc).__name__}: {exc}"[:1000]
        self.db.commit()

    async def refresh_all(self) -> None:
        for pool in self.db.scalars(select(SerpApiPool).where(SerpApiPool.enabled.is_(True))).all():
            await self.refresh_pool(pool)

