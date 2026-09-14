"""Low-level HTTP client for the SignalPilot gateway. Stdlib-only."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

# Transient statuses from the tunnel or load balancer in front of the gateway.
_RETRY_STATUSES = frozenset({502, 503, 504})
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (0.5, 1.5, 4.0)


def _is_local_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


class GatewayClient:
    """Thin HTTP wrapper around the SignalPilot gateway API."""

    def __init__(
        self,
        gateway_url: str,
        token: str | None = None,
        token_file: str | os.PathLike[str] | None = None,
    ):
        from signalpilot._utils.localhost import fix_localhost_url
        self._url = fix_localhost_url(gateway_url).rstrip("/")
        self._token = token
        # Credentials rotate BETWEEN chat runs: a kernel kept alive across
        # turns gets a fresh run-scoped token written to this file at
        # adoption. Read it per request so the live kernel always presents
        # the active run's token, not the one captured at sp.init().
        self._token_file = Path(token_file) if token_file else None
        self._token_file_mtime: float | None = None

    def _resolve_token(self) -> str | None:
        if self._token_file is None:
            return self._token
        try:
            mtime = self._token_file.stat().st_mtime
            if mtime != self._token_file_mtime:
                self._token = self._token_file.read_text(encoding="utf-8").strip()
                self._token_file_mtime = mtime
        except OSError:
            # The file is removed between runs. Keep the last token read.
            pass
        return self._token

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        token = self._resolve_token()
        if token:
            h["Authorization"] = f"Bearer {token}"
        if extra:
            h.update(extra)
        return h

    def get(self, path: str, params: dict[str, Any] | None = None, timeout: int = 30) -> Any:
        url = f"{self._url}{path}"
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        req = Request(url, headers=self._headers())
        return self._send(req, timeout)

    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        timeout: int = 60,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self._url}{path}"
        data = json.dumps(body or {}).encode()
        req = Request(url, data=data, headers=self._headers(headers))
        return self._send(req, timeout)

    def _send(self, req: Request, timeout: int) -> Any:
        """Send one request. Transient gateway or tunnel failures are retried.

        Every SDK call is a read on the data plane, so replaying a request is
        safe. 502, 503, and 504 (a tunnel or load balancer between the sandbox
        and the gateway) and connection errors retry with a short backoff.
        Other HTTP errors are final.
        """
        attempt = 0
        while True:
            try:
                with urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if not raw:
                        return None
                    return json.loads(raw)
            except HTTPError as e:
                body_text = e.read().decode("utf-8", errors="replace")[:500]
                if e.code in _RETRY_STATUSES and attempt < _RETRY_ATTEMPTS:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise RuntimeError(f"Gateway error (HTTP {e.code}): {body_text}") from None
            except URLError as e:
                if attempt < _RETRY_ATTEMPTS:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise RuntimeError(f"Cannot reach gateway: {e.reason}") from None

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(_RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)])

    def download(self, path: str, destination: Path, timeout: int = 300) -> None:
        """Stream an authenticated private object to a runtime-local file.

        Transient failures at connection time retry like ``_send``. A failure
        after streaming has started is final; the partial file is removed.
        """
        req = Request(f"{self._url}{path}", headers=self._headers())
        attempt = 0
        while True:
            try:
                response = urlopen(req, timeout=timeout)
            except HTTPError as e:
                body_text = e.read().decode("utf-8", errors="replace")[:500]
                if e.code in _RETRY_STATUSES and attempt < _RETRY_ATTEMPTS:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise RuntimeError(f"Gateway error (HTTP {e.code}): {body_text}") from None
            except URLError as e:
                if attempt < _RETRY_ATTEMPTS:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise RuntimeError(f"Cannot reach gateway: {e.reason}") from None
            try:
                with response, destination.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            except (OSError, URLError) as e:
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"Download interrupted: {e}") from None
            return

    def __repr__(self) -> str:
        return f"GatewayClient({self._url!r})"
