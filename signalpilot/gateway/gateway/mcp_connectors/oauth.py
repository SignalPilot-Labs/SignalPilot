"""OAuth for remote connectors lives in the gateway (R6).

Discovery: ``WWW-Authenticate … resource_metadata=`` -> PRM (RFC 9728) -> AS
metadata (RFC 8414 / OIDC). Registration order: pre-registered client ->
CIMD (the gateway hosts a client-metadata document) -> DCR (with
``application_type``) -> ask the user. PKCE S256 always; RFC 8707 ``resource``
is the MCP server URL; scopes from the challenge, then ``scopes_supported``.
Tokens are per user per connector; refresh is single-flight per (connector, user).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
)

from gateway.mcp_connectors.ssrf import (
    PROBE_TIMEOUT_SECONDS,
    UnsafeUrlError,
    read_capped,
    safe_async_client,
    validate_remote_url,
)

logger = logging.getLogger(__name__)

CIMD_PATH = "/api/mcp/oauth/client-metadata.json"
CALLBACK_PATH = "/api/mcp/oauth/callback"
CLIENT_NAME = "SignalPilot"
_REFRESH_SKEW_SECONDS = 60
_WWW_AUTH_FIELD = re.compile(r'([a-zA-Z_]+)=(?:"([^"]*)"|([^\s,]+))')


class OAuthError(RuntimeError):
    """A recoverable OAuth failure with a user-facing message."""


class NeedsClientRegistration(OAuthError):
    """The provider needs a pre-registered client (manual client_id/secret)."""


@dataclass
class OAuthDiscovery:
    issuer: str
    metadata_url: str
    metadata: dict[str, Any]
    resource_metadata: dict[str, Any] | None
    scopes: str | None
    registration: str  # "cimd" | "dcr" | "manual"
    challenge: dict[str, str] = field(default_factory=dict)


def parse_www_authenticate(header: str | None) -> dict[str, str]:
    if not header:
        return {}
    return {name: (quoted if quoted is not None else bare) for name, quoted, bare in _WWW_AUTH_FIELD.findall(header)}


def make_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def canonical_resource(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def redirect_uri(gateway_url: str) -> str:
    return f"{gateway_url.rstrip('/')}{CALLBACK_PATH}"


def cimd_client_id(gateway_url: str) -> str:
    return f"{gateway_url.rstrip('/')}{CIMD_PATH}"


def cimd_document(gateway_url: str) -> dict[str, Any]:
    """Client ID Metadata Document (SEP-991) served publicly by the gateway."""
    return {
        "client_id": cimd_client_id(gateway_url),
        "client_name": CLIENT_NAME,
        "client_uri": gateway_url.rstrip("/"),
        "redirect_uris": [redirect_uri(gateway_url)],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": "web",
    }


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    try:
        await validate_remote_url(url)
        async with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
            if response.status_code != 200:
                return None
            body = await read_capped(response)
    except (httpx.HTTPError, UnsafeUrlError):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def discover(
    server_url: str,
    www_authenticate: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> OAuthDiscovery | None:
    """Run PRM + AS-metadata discovery. None when the server advertises no OAuth."""
    challenge = parse_www_authenticate(www_authenticate)
    owns_client = client is None
    client = client or safe_async_client(timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS))
    try:
        prm: dict[str, Any] | None = None
        for url in build_protected_resource_metadata_discovery_urls(challenge.get("resource_metadata"), server_url):
            candidate = await _fetch_json(client, url)
            if candidate and isinstance(candidate.get("authorization_servers"), list):
                prm = candidate
                break
        servers = [str(s) for s in (prm or {}).get("authorization_servers") or []] or [None]
        for auth_server in servers:
            for metadata_url in build_oauth_authorization_server_metadata_discovery_urls(auth_server, server_url):
                metadata = await _fetch_json(client, metadata_url)
                if not metadata or "authorization_endpoint" not in metadata or "token_endpoint" not in metadata:
                    continue
                methods = metadata.get("code_challenge_methods_supported")
                if isinstance(methods, list) and "S256" not in methods:
                    raise OAuthError("The provider does not support PKCE (S256), which is required")
                scopes = challenge.get("scope") or _join(prm and prm.get("scopes_supported")) or _join(
                    metadata.get("scopes_supported")
                )
                scopes = _with_offline_access(scopes, metadata)
                if metadata.get("client_id_metadata_document_supported"):
                    registration = "cimd"
                elif metadata.get("registration_endpoint"):
                    registration = "dcr"
                else:
                    registration = "manual"
                return OAuthDiscovery(
                    issuer=str(metadata.get("issuer") or auth_server or metadata_url),
                    metadata_url=metadata_url,
                    metadata=metadata,
                    resource_metadata=prm,
                    scopes=scopes,
                    registration=registration,
                    challenge=challenge,
                )
        return None
    finally:
        if owns_client:
            await client.aclose()


def _join(values: Any) -> str | None:
    if isinstance(values, list) and values:
        return " ".join(str(v) for v in values)
    return None


def _with_offline_access(scopes: str | None, metadata: dict[str, Any]) -> str | None:
    """Ask for a refresh token where the provider only issues one on request."""
    supported = metadata.get("scopes_supported")
    if not isinstance(supported, list) or "offline_access" not in supported:
        return scopes
    current = (scopes or "").split()
    if "offline_access" in current:
        return scopes
    return " ".join([*current, "offline_access"])


def oauth_config(
    discovery: OAuthDiscovery,
    *,
    server_url: str,
    client_id: str | None = None,
    has_client_secret: bool = False,
) -> dict[str, Any]:
    """The non-secret OAuth record stored on the connector (``oauth_json``)."""
    registration = "manual" if client_id else discovery.registration
    return {
        "issuer": discovery.issuer,
        "metadata_url": discovery.metadata_url,
        "authorization_endpoint": discovery.metadata["authorization_endpoint"],
        "token_endpoint": discovery.metadata["token_endpoint"],
        "registration_endpoint": discovery.metadata.get("registration_endpoint"),
        "revocation_endpoint": discovery.metadata.get("revocation_endpoint"),
        "scopes": discovery.scopes,
        "resource": canonical_resource(server_url),
        "registration": registration,
        "client_id": client_id,
        "token_endpoint_auth_method": "client_secret_basic" if has_client_secret else "none",
    }


async def register_client(
    oauth: dict[str, Any],
    *,
    gateway_url: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Resolve ``client_id`` per the registration order. Returns (oauth, client_secret)."""
    if oauth.get("client_id"):
        return oauth, None
    if oauth.get("registration") == "cimd":
        return {**oauth, "client_id": cimd_client_id(gateway_url)}, None
    endpoint = oauth.get("registration_endpoint")
    if oauth.get("registration") != "dcr" or not endpoint:
        raise NeedsClientRegistration("This provider needs a registered client. Add a client ID and secret.")
    owns_client = client is None
    client = client or safe_async_client(timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS))
    try:
        await validate_remote_url(str(endpoint))
        document = {k: v for k, v in cimd_document(gateway_url).items() if k != "client_id"}
        response = await client.post(str(endpoint), json=document, headers={"Accept": "application/json"})
        if response.status_code not in (200, 201):
            raise NeedsClientRegistration("The provider refused automatic client registration. Add a client ID.")
        data = response.json()
    except (httpx.HTTPError, UnsafeUrlError, ValueError) as exc:
        raise NeedsClientRegistration("The provider refused automatic client registration. Add a client ID.") from exc
    finally:
        if owns_client:
            await client.aclose()
    client_id = data.get("client_id")
    if not client_id:
        raise NeedsClientRegistration("The provider refused automatic client registration. Add a client ID.")
    secret = data.get("client_secret") or None
    method = data.get("token_endpoint_auth_method") or ("client_secret_basic" if secret else "none")
    return {**oauth, "client_id": str(client_id), "token_endpoint_auth_method": method}, secret


def build_authorize_url(
    oauth: dict[str, Any],
    *,
    state: str,
    code_challenge: str,
    gateway_url: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": oauth["client_id"],
        "redirect_uri": redirect_uri(gateway_url),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": oauth["resource"],
    }
    if oauth.get("scopes"):
        params["scope"] = oauth["scopes"]
    endpoint = str(oauth["authorization_endpoint"])
    if urlsplit(endpoint).scheme not in {"https", "http"}:
        raise OAuthError("The provider's sign-in address is not an https:// URL")
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(params)}"


def _token_auth(oauth: dict[str, Any], client_secret: str | None) -> tuple[httpx.Auth | None, dict[str, str]]:
    if not client_secret:
        return None, {}
    if oauth.get("token_endpoint_auth_method") == "client_secret_post":
        return None, {"client_secret": client_secret}
    return httpx.BasicAuth(str(oauth["client_id"]), client_secret), {}


async def _token_request(
    oauth: dict[str, Any],
    client_secret: str | None,
    form: dict[str, str],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    endpoint = str(oauth["token_endpoint"])
    auth, extra = _token_auth(oauth, client_secret)
    owns_client = client is None
    client = client or safe_async_client(timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS))
    try:
        await validate_remote_url(endpoint)
        response = await client.post(
            endpoint,
            data={**form, "client_id": str(oauth["client_id"]), "resource": oauth["resource"], **extra},
            auth=auth,
            headers={"Accept": "application/json"},
        )
    except (httpx.HTTPError, UnsafeUrlError) as exc:
        raise OAuthError("We couldn't reach the provider's sign-in service") from exc
    finally:
        if owns_client:
            await client.aclose()
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200 or not isinstance(data, dict) or not data.get("access_token"):
        error = (data.get("error") if isinstance(data, dict) else None) or f"HTTP {response.status_code}"
        raise OAuthError(f"The provider refused sign-in ({error})")
    return data


def tokens_from_response(data: dict[str, Any], *, previous_refresh: str | None = None) -> dict[str, Any]:
    expires_in = data.get("expires_in")
    expires_at = None
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        expires_at = time.time() + float(expires_in)
    id_token = data.get("id_token")
    return {
        "access_token": str(data["access_token"]),
        "refresh_token": str(data.get("refresh_token") or previous_refresh or "") or None,
        "expires_at": expires_at,
        "scopes": str(data.get("scope") or "") or None,
        "token_type": str(data.get("token_type") or "Bearer"),
        "id_token": id_token if isinstance(id_token, str) and id_token else None,
    }


_LABEL_CLAIMS = ("email", "preferred_username", "name")
_MAX_LABEL = 200


def account_label_from_tokens(tokens: dict[str, Any] | None) -> str | None:
    """Best-effort display identity from the ``id_token`` (email, else username, else name).

    The payload is read without signature verification: the value is a label
    for the settings page and never an authorization input. No network call is
    made; providers that return no id_token yield None.
    """
    raw = (tokens or {}).get("id_token")
    if not isinstance(raw, str) or raw.count(".") < 2:
        return None
    segment = raw.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict):
        return None
    for key in _LABEL_CLAIMS:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"[\x00-\x1f\x7f]", "", value).strip()[:_MAX_LABEL] or None
    return None


async def exchange_code(
    oauth: dict[str, Any],
    client_secret: str | None,
    *,
    code: str,
    code_verifier: str,
    gateway_url: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    data = await _token_request(
        oauth,
        client_secret,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(gateway_url),
            "code_verifier": code_verifier,
        },
        client=client,
    )
    return tokens_from_response(data)


async def refresh_tokens(
    oauth: dict[str, Any],
    client_secret: str | None,
    tokens: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise OAuthError("No refresh token; sign in again")
    data = await _token_request(
        oauth,
        client_secret,
        {"grant_type": "refresh_token", "refresh_token": str(refresh_token)},
        client=client,
    )
    return tokens_from_response(data, previous_refresh=str(refresh_token))


def token_expiring(tokens: dict[str, Any] | None) -> bool:
    if not tokens:
        return True
    expires_at = tokens.get("expires_at")
    return isinstance(expires_at, (int, float)) and expires_at - _REFRESH_SKEW_SECONDS <= time.time()


class RefreshLocks:
    """Single-flight refresh per (connector, user) so rotated tokens are never raced."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def for_key(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock


refresh_locks = RefreshLocks()
