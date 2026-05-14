"""Low-level HTTP client for the SignalPilot gateway. Stdlib-only."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def _is_local_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


class GatewayClient:
    """Thin HTTP wrapper around the SignalPilot gateway API."""

    def __init__(self, gateway_url: str, token: str | None = None):
        self._url = gateway_url.rstrip("/")
        self._token = token

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if extra:
            h.update(extra)
        return h

    def get(self, path: str, params: dict[str, Any] | None = None, timeout: int = 30) -> Any:
        url = f"{self._url}{path}"
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        req = Request(url, headers=self._headers())
        return self._send(req, timeout)

    def post(self, path: str, body: dict[str, Any] | None = None, timeout: int = 60) -> Any:
        url = f"{self._url}{path}"
        data = json.dumps(body or {}).encode()
        req = Request(url, data=data, headers=self._headers())
        return self._send(req, timeout)

    def _send(self, req: Request, timeout: int) -> Any:
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw)
        except HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Gateway error (HTTP {e.code}): {body_text}") from None
        except URLError as e:
            raise RuntimeError(f"Cannot reach gateway: {e.reason}") from None

    def __repr__(self) -> str:
        return f"GatewayClient({self._url!r})"
