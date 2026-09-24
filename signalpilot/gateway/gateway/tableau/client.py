"""Async Tableau REST client with one cached auth token per org.

A Tableau personal access token (PAT) allows ONE session: a second sign-in
with the same PAT invalidates the first. The client therefore never signs in
per call. It keeps one token per cache key (the org id) in a process-local
dict, reuses it for every request, and signs in again at most once when a
request answers 401 (another process used the PAT, or the token expired).

Secrets never reach logs or exception messages: errors carry only the
Tableau error summary/detail/code.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_VERSION_CAP = "3.29"
FALLBACK_API_VERSION = "3.21"
DEFAULT_TIMEOUT_S = 60.0
LONG_TIMEOUT_S = 600.0


class TableauError(Exception):
    """A Tableau call failed. ``status_code`` is the HTTP status to answer with."""

    def __init__(self, message: str, *, status_code: int = 502, tableau_status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.tableau_status = tableau_status


@dataclass(frozen=True)
class TableauCredentials:
    server_url: str
    site_content_url: str
    pat_name: str
    pat_secret: str

    def fingerprint(self) -> str:
        """Hash of the credential set, so a rotated PAT never reuses an old token."""
        raw = "\x1f".join((self.server_url, self.site_content_url, self.pat_name, self.pat_secret))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TableauAuth:
    token: str
    site_id: str
    user_id: str
    api_version: str
    fingerprint: str


_TOKENS: dict[str, TableauAuth] = {}
_LOCKS: dict[str, asyncio.Lock] = {}
_API_VERSIONS: dict[str, str] = {}


def forget_token(cache_key: str) -> None:
    """Drop the cached token for one org (on delete or credential change)."""
    _TOKENS.pop(cache_key, None)


def clear_token_cache() -> None:
    """Drop every cached token and API version (tests)."""
    _TOKENS.clear()
    _LOCKS.clear()
    _API_VERSIONS.clear()


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in value.split("."))
    except ValueError:
        return (0,)


def error_message(response: httpx.Response) -> str:
    """Tableau's error summary/detail/code from a JSON or XML error body."""
    try:
        err = (response.json() or {}).get("error") or {}
        if isinstance(err, dict) and (err.get("summary") or err.get("detail")):
            parts = [str(err.get("summary") or "").strip(), str(err.get("detail") or "").strip()]
            text = ": ".join(p for p in parts if p)
            return f"{text} ({err['code']})" if err.get("code") else text
        if isinstance(response.json(), dict) and response.json().get("message"):
            return str(response.json()["message"])[:500]
    except Exception:
        pass
    body = response.text or ""
    summary = re.search(r"<summary>(.*?)</summary>", body, re.S)
    detail = re.search(r"<detail>(.*?)</detail>", body, re.S)
    if summary or detail:
        return ": ".join(m.group(1).strip() for m in (summary, detail) if m)
    title = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    if title:  # an HTML error page from a proxy or the servlet container
        return f"HTTP {response.status_code}: {title.group(1).strip()[:200]}"
    return f"HTTP {response.status_code}: {body[:300].strip()}" if body.strip() else f"HTTP {response.status_code}"


def _status_for(tableau_status: int) -> int:
    """Map a Tableau HTTP status to the status the gateway answers with."""
    return tableau_status if tableau_status in (400, 403, 404, 409, 413) else 502


class TableauClient:
    """One Tableau site. Use as ``async with TableauClient(...) as client``."""

    def __init__(
        self,
        creds: TableauCredentials,
        *,
        cache_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.creds = creds
        self.server = creds.server_url.rstrip("/")
        self.cache_key = cache_key
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._auth: TableauAuth | None = None

    async def __aenter__(self) -> TableauClient:
        self._http = httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=15.0),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("TableauClient used outside 'async with'")
        return self._http

    # ── Auth ────────────────────────────────────────────────────────────────

    async def api_version(self) -> str:
        """The server's REST API version, capped at API_VERSION_CAP."""
        cached = _API_VERSIONS.get(self.server)
        if cached:
            return cached
        version = FALLBACK_API_VERSION
        try:
            resp = await self.http.get(f"{self.server}/api/2.4/serverinfo", headers={"Accept": "application/json"})
            if resp.status_code == 200:
                reported = str(((resp.json() or {}).get("serverInfo") or {}).get("restApiVersion") or "")
                if reported:
                    version = min(reported, API_VERSION_CAP, key=_version_tuple)
        except (httpx.HTTPError, ValueError):
            logger.info("tableau serverinfo unavailable for %s; using API %s", self.server, version)
        _API_VERSIONS[self.server] = version
        return version

    def _cached(self) -> TableauAuth | None:
        if self._auth is not None and self._auth.fingerprint == self.creds.fingerprint():
            return self._auth
        if self.cache_key:
            entry = _TOKENS.get(self.cache_key)
            if entry is not None and entry.fingerprint == self.creds.fingerprint():
                return entry
        return None

    def _lock(self) -> asyncio.Lock:
        key = self.cache_key or f"_anon:{id(self)}"
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = asyncio.Lock()
        return lock

    async def _sign_in_now(self) -> TableauAuth:
        version = await self.api_version()
        try:
            resp = await self.http.post(
                f"{self.server}/api/{version}/auth/signin",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json={
                    "credentials": {
                        "personalAccessTokenName": self.creds.pat_name,
                        "personalAccessTokenSecret": self.creds.pat_secret,
                        "site": {"contentUrl": self.creds.site_content_url},
                    }
                },
            )
        except httpx.HTTPError as exc:
            raise TableauError(f"Cannot reach Tableau at {self.server}: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise TableauError(
                f"Tableau sign-in failed: {error_message(resp)}",
                status_code=502,
                tableau_status=resp.status_code,
            )
        cred = (resp.json() or {}).get("credentials") or {}
        auth = TableauAuth(
            token=str(cred.get("token") or ""),
            site_id=str((cred.get("site") or {}).get("id") or ""),
            user_id=str((cred.get("user") or {}).get("id") or ""),
            api_version=version,
            fingerprint=self.creds.fingerprint(),
        )
        if not auth.token or not auth.site_id:
            raise TableauError("Tableau sign-in returned no token")
        self._auth = auth
        if self.cache_key:
            _TOKENS[self.cache_key] = auth
        logger.info("tableau.signin org=%s site_id=%s api=%s", self.cache_key, auth.site_id, version)
        return auth

    async def sign_in(self, *, force: bool = False) -> TableauAuth:
        """Return the cached token, signing in only when there is none (or ``force``)."""
        if not force and (cached := self._cached()):
            self._auth = cached
            return cached
        async with self._lock():
            if not force and (cached := self._cached()):
                self._auth = cached
                return cached
            return await self._sign_in_now()

    async def _resign(self, stale: TableauAuth) -> TableauAuth:
        """Sign in again after a 401, unless another task already replaced the token."""
        async with self._lock():
            current = self._cached()
            if current is not None and current.token != stale.token:
                self._auth = current
                return current
            if self.cache_key and _TOKENS.get(self.cache_key) is stale:
                _TOKENS.pop(self.cache_key, None)
            self._auth = None
            return await self._sign_in_now()

    async def sign_out(self) -> None:
        """Best-effort sign-out of the cached session; always drops the cache entry."""
        auth = self._cached()
        if self.cache_key:
            forget_token(self.cache_key)
        self._auth = None
        if auth is None:
            return
        try:
            await self.http.post(
                f"{self.server}/api/{auth.api_version}/auth/signout",
                headers={"X-Tableau-Auth": auth.token},
            )
        except httpx.HTTPError:
            logger.info("tableau signout failed for org=%s", self.cache_key)

    # ── Requests ────────────────────────────────────────────────────────────

    def _url(self, auth: TableauAuth, path: str, *, scope: str) -> str:
        if scope == "site":
            return f"{self.server}/api/{auth.api_version}/sites/{auth.site_id}{path}"
        if scope == "api":
            return f"{self.server}/api/{auth.api_version}{path}"
        return f"{self.server}{path}"  # "root": /api/-/search, /api/v1/vizql-data-service/...

    async def request(
        self,
        method: str,
        path: str,
        *,
        scope: str = "site",
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        """Send one authenticated request; sign in again once on 401; raise on failure."""
        auth = await self.sign_in()
        resp = await self._send(auth, method, path, scope, params, json, content, headers, timeout, accept)
        if resp.status_code == 401:
            logger.info("tableau.token_rejected org=%s path=%s; signing in again", self.cache_key, path)
            auth = await self._resign(auth)
            resp = await self._send(auth, method, path, scope, params, json, content, headers, timeout, accept)
        if resp.status_code >= 400:
            raise TableauError(
                error_message(resp), status_code=_status_for(resp.status_code), tableau_status=resp.status_code
            )
        return resp

    async def _send(
        self,
        auth: TableauAuth,
        method: str,
        path: str,
        scope: str,
        params: dict[str, Any] | None,
        json: Any,
        content: bytes | None,
        headers: dict[str, str] | None,
        timeout: float | None,
        accept: str,
    ) -> httpx.Response:
        all_headers = {"X-Tableau-Auth": auth.token, "Accept": accept, **(headers or {})}
        kwargs: dict[str, Any] = {"params": params, "headers": all_headers}
        if json is not None:
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        if timeout is not None:
            kwargs["timeout"] = httpx.Timeout(timeout, connect=15.0)
        try:
            return await self.http.request(method, self._url(auth, path, scope=scope), **kwargs)
        except httpx.TimeoutException:
            raise TableauError(f"Tableau did not answer in time ({method} {path})", status_code=504) from None
        except httpx.HTTPError as exc:
            raise TableauError(f"Cannot reach Tableau: {type(exc).__name__}") from None

    async def get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self.request("GET", path, **kwargs)
        return resp.json() if resp.content else {}

    async def current_user(self) -> dict[str, Any]:
        """The PAT owner (``name``, ``siteRole``, ...)."""
        auth = await self.sign_in()
        data = await self.get_json(f"/users/{auth.user_id}")
        return data.get("user") or {}
