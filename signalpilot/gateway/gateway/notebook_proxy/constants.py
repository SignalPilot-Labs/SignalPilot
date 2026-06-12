"""Constants for the notebook proxy package."""

from __future__ import annotations

# Pattern for validating session_id path parameters.
# All chars legal in a FastAPI path segment but illegal in header/path attribute
# values (semicolon, comma, CR, LF, space) are excluded. UUIDs and opaque
# base64url IDs all satisfy this pattern.
SESSION_ID_PATTERN_STR = r"^[A-Za-z0-9_-]{1,64}$"

# Internal port notebook pods listen on.
POD_PORT = 2718

# Per-chunk idle watchdog timeout in seconds. If no bytes flow from upstream for
# this many seconds, the proxy cancels the streaming response and returns 504.
# This is NOT a total response deadline — long-running kernels are unaffected as
# long as they emit at least one byte every IDLE_WATCHDOG_SECONDS seconds.
IDLE_WATCHDOG_SECONDS = 30

# httpx client timeouts for the shared proxy client.
PROXY_CONNECT_TIMEOUT_SECONDS = 5
PROXY_READ_TIMEOUT_SECONDS: float | None = None  # No total read deadline (SSE/long-poll)
PROXY_WRITE_TIMEOUT_SECONDS = 10
PROXY_POOL_TIMEOUT_SECONDS = 10

# Hop-by-hop headers that must be stripped on both inbound and outbound paths.
# This list is a code-constant — not configurable.
HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# Headers stripped from outbound (gateway → pod) requests.
# In addition to HOP_BY_HOP_HEADERS, Cookie and Authorization are stripped:
# - Cookie: forwarding Cookie would leak the Clerk __session cookie into pod logs.
# - Authorization: the caller's Clerk bearer JWT must never reach the pod
#   (the pod runs --no-token; the gateway proxy is the sole auth gate).
# - sec-websocket-protocol: carries our auth sentinel + JWT; must not reach the pod.
# Host is also not forwarded (let httpx synthesize it from the URL).
OUTBOUND_STRIP_HEADERS: frozenset[str] = HOP_BY_HOP_HEADERS | frozenset({
    "cookie", "authorization", "host",
    "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions",
    "sec-websocket-protocol", "sec-websocket-accept",
})

# Headers stripped from upstream responses before returning to the browser.
# Set-Cookie is stripped to prevent the notebook server's own session cookie from
# colliding with the gateway origin.
INBOUND_STRIP_HEADERS: frozenset[str] = HOP_BY_HOP_HEADERS | frozenset({"set-cookie"})
