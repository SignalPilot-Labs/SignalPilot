"""Thin async HTTP client for minting and revoking gateway dbt-proxy run-tokens.

Calls:
  POST {gateway_url}/api/dbt-proxy/run-tokens   → ProxyTokenLease
  DELETE /api/dbt-proxy/run-tokens/{run_id}     → 204 (idempotent)

Auth: Authorization: Bearer <SP_API_KEY> when set; omitted otherwise.
Failure codes:
  401 → ProxyTokenMintFailed("auth")
  409 → caller retries once then raises ProxyTokenMintFailed("conflict")
  other 4xx/5xx → ProxyTokenMintFailed with status code in message
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx

from workspaces_api.errors import ProxyTokenMintFailed

logger = logging.getLogger(__name__)

_MINT_PATH = "/api/dbt-proxy/run-tokens"


@dataclass(frozen=True)
class ProxyTokenLease:
    """Short-lived token for a dbt-proxy session.

    token is masked in __repr__ to prevent accidental log leakage.
    """

    token: str
    host_port: int
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            f"ProxyTokenLease(token=***, host_port={self.host_port!r}, "
            f"expires_at={self.expires_at!r})"
        )


class ProxyTokenClient:
    """Async HTTP client for gateway dbt-proxy token management.

    Uses a shared httpx.AsyncClient whose lifecycle is managed by the caller
    (typically the app lifespan in main.py).
    """

    def __init__(
        self,
        gateway_url: str,
        http_client: httpx.AsyncClient,
        api_key: str | None,
    ) -> None:
        self._gateway_url = gateway_url.rstrip("/")
        self._client = http_client
        self._api_key = api_key

    def _auth_headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def mint(
        self,
        run_id: uuid.UUID,
        connector_name: str,
        ttl_seconds: int,
    ) -> ProxyTokenLease:
        """Mint a run-token for the given run.

        Returns a ProxyTokenLease on success.
        Raises ProxyTokenMintFailed on 401 (auth), 409 (conflict), or other errors.
        """
        url = f"{self._gateway_url}{_MINT_PATH}"
        payload = {
            "run_id": str(run_id),
            "connector_name": connector_name,
            "ttl_seconds": ttl_seconds,
        }
        try:
            resp = await self._client.post(url, json=payload, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise ProxyTokenMintFailed(f"network error minting token: {type(exc).__name__}") from exc

        if resp.status_code == 401:
            raise ProxyTokenMintFailed("auth")

        if resp.status_code == 409:
            # Attempt revoke + retry once
            await self.revoke(run_id)
            try:
                resp = await self._client.post(
                    url, json=payload, headers=self._auth_headers()
                )
            except httpx.RequestError as exc:
                raise ProxyTokenMintFailed(
                    f"network error on retry minting token: {type(exc).__name__}"
                ) from exc
            if resp.status_code == 409:
                raise ProxyTokenMintFailed("conflict")
            if not resp.is_success:
                raise ProxyTokenMintFailed(
                    f"mint retry failed with status {resp.status_code}"
                )

        elif not resp.is_success:
            raise ProxyTokenMintFailed(f"mint failed with status {resp.status_code}")

        data = resp.json()
        expires_at = datetime.fromisoformat(data["expires_at"])
        return ProxyTokenLease(
            token=data["token"],
            host_port=int(data["host_port"]),
            expires_at=expires_at,
        )

    async def revoke(self, run_id: uuid.UUID) -> None:
        """Revoke a run-token. Gateway returns 204 always (idempotent).

        Logs on failure but does not raise — revoke is always best-effort.
        """
        url = f"{self._gateway_url}{_MINT_PATH}/{run_id}"
        try:
            await self._client.delete(url, headers=self._auth_headers())
        except httpx.RequestError as exc:
            logger.warning(
                "proxy_token revoke network error run_id=%s: %s",
                run_id,
                type(exc).__name__,
            )
