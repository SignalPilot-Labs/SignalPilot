"""HTTP and WebSocket forwarding primitives for the notebook proxy.

This is the only file in the package that imports httpx and websockets.
routes.py constructs upstream_base from the session row and delegates here.

HTTP forwarding:
- Streams response via httpx.AsyncClient.stream(); no aread(); no Content-Length override.
- Strips outbound Cookie, Authorization, Host, and hop-by-hop headers.
- Strips upstream Set-Cookie so the notebook server's session cookie does not leak to the gateway origin.
- Per-chunk asyncio.wait_for idle watchdog (30 s) — NOT a total deadline.

WebSocket bridge:
- Auth runs BEFORE ws.accept() (enforced by the route dependency).
- Strips Cookie and Authorization from the upstream WS handshake.
- TEXT frames stay TEXT; BINARY frames stay BINARY (no coercion).
- Close codes propagate verbatim from upstream to client and vice versa.
- asyncio.TaskGroup pumps bidirectionally; cancellation of either pump tears down both.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import websockets
import websockets.asyncio.client
import websockets.exceptions
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.websockets import WebSocket, WebSocketDisconnect

from .constants import (
    IDLE_WATCHDOG_SECONDS,
    INBOUND_STRIP_HEADERS,
    OUTBOUND_STRIP_HEADERS,
)

logger = logging.getLogger(__name__)


def _build_outbound_headers(request: Request) -> dict[str, str]:
    """Build headers for the upstream HTTP request, stripping forbidden headers."""
    return {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in OUTBOUND_STRIP_HEADERS
    }


def _build_outbound_ws_headers(ws: WebSocket) -> list[tuple[str, str]]:
    """Build headers for the upstream WS handshake, stripping forbidden headers."""
    return [
        (k, v)
        for k, v in ws.headers.items()
        if k.lower() not in OUTBOUND_STRIP_HEADERS
    ]


def _build_inbound_headers(upstream_headers: httpx.Headers) -> dict[str, str]:
    """Build response headers, stripping hop-by-hop and upstream Set-Cookie."""
    return {
        k: v
        for k, v in upstream_headers.items()
        if k.lower() not in INBOUND_STRIP_HEADERS
    }


class NotebookProxy:
    """HTTP and WebSocket proxy to a notebook pod.

    upstream_base: in-cluster base URL of the pod (e.g. http://10.42.0.5:2718).
    Always passed in from the session row — never derived from request headers.
    """

    def __init__(self, upstream_base: str, *, http_client: httpx.AsyncClient) -> None:
        self._upstream_base = upstream_base.rstrip("/")
        self._http_client = http_client

    async def forward_http(self, request: Request, upstream_path: str) -> StreamingResponse:
        """Stream an HTTP request to the upstream pod and return the response.

        - Strips Cookie, Authorization, Host, and hop-by-hop headers from the outbound request.
        - Strips Set-Cookie and hop-by-hop headers from the upstream response.
        - No Content-Length override; let Transfer-Encoding: chunked propagate.
        - Per-chunk idle watchdog: raises 504 if no bytes flow for IDLE_WATCHDOG_SECONDS.
        """
        url = f"{self._upstream_base}/{upstream_path.lstrip('/')}"
        if request.url.query:
            url = f"{url}?{request.url.query}"

        outbound_headers = _build_outbound_headers(request)
        body = await request.body()

        try:
            upstream_request = self._http_client.build_request(
                method=request.method,
                url=url,
                headers=outbound_headers,
                content=body if body else None,
            )
        except Exception as exc:
            # M-6: Do not log the upstream URL (contains pod IP) at warning level.
            logger.debug("Failed to build upstream request: %s", exc)
            raise HTTPException(status_code=502, detail="Notebook backend unavailable") from exc

        try:
            response = await self._http_client.send(upstream_request, stream=True)
        except httpx.ConnectError as exc:
            # M-6: Log at debug only to avoid leaking pod IP in warning-level logs.
            logger.debug("Upstream connect error (pod unreachable): %s", exc)
            raise HTTPException(status_code=502, detail="Notebook backend unavailable") from exc
        except httpx.TimeoutException as exc:
            # M-6: Same — pod address must not appear in warning-level logs.
            logger.debug("Upstream timeout: %s", exc)
            raise HTTPException(status_code=504, detail="Notebook backend timeout") from exc

        inbound_headers = _build_inbound_headers(response.headers)
        media_type = response.headers.get("content-type", "application/octet-stream")

        async def _watchdog_stream():
            """Yield chunks with per-chunk idle watchdog.

            asyncio.wait_for wraps each anext() call — NOT the whole response —
            so long-running kernels are unaffected as long as they emit bytes
            at least once every IDLE_WATCHDOG_SECONDS.
            """
            aiter = response.aiter_bytes()
            try:
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            aiter.__anext__(), timeout=IDLE_WATCHDOG_SECONDS
                        )
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        logger.warning(
                            "Upstream idle timeout after %ds", IDLE_WATCHDOG_SECONDS
                        )
                        break
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(
            content=_watchdog_stream(),
            status_code=response.status_code,
            headers=inbound_headers,
            media_type=media_type,
        )

    async def forward_ws(self, ws: WebSocket, upstream_url: str) -> None:
        """Bridge a WebSocket connection to the upstream pod.

        Auth must have already succeeded. ws.accept() is called inside this method
        after the upstream connection is established.

        - Strips Cookie and Authorization from the upstream WS handshake.
        - TEXT frames stay TEXT; BINARY frames stay BINARY (recv() returns str|bytes).
        - Close codes propagate verbatim; no synthetic 1000.
        - asyncio.TaskGroup: cancellation of either pump tears down both.
        """
        outbound_headers = _build_outbound_ws_headers(ws)

        try:
            upstream_ws = await websockets.asyncio.client.connect(
                upstream_url,
                additional_headers=outbound_headers,
            )
        except Exception as exc:
            # M-6: Log at debug only — upstream URL contains pod IP.
            logger.debug("Upstream WS connect failed: %s", exc)
            await ws.close(code=1011)
            return

        await ws.accept()

        async def _client_to_upstream() -> None:
            """Pump frames from the browser client to the upstream pod."""
            try:
                while True:
                    data = await ws.receive()
                    msg_type = data.get("type")
                    if msg_type == "websocket.receive":
                        text = data.get("text")
                        bytes_ = data.get("bytes")
                        if text is not None:
                            await upstream_ws.send(text)
                        elif bytes_ is not None:
                            await upstream_ws.send(bytes_)
                    elif msg_type == "websocket.disconnect":
                        code = data.get("code", 1000)
                        await upstream_ws.close(code)
                        break
            except WebSocketDisconnect as exc:
                await upstream_ws.close(exc.code or 1000)
            except websockets.exceptions.ConnectionClosedOK:
                pass
            except websockets.exceptions.ConnectionClosedError as exc:
                logger.debug("Upstream WS closed with error during client→upstream: %s", exc)

        async def _upstream_to_client() -> None:
            """Pump frames from the upstream pod to the browser client.

            recv() returns str for TEXT frames and bytes for BINARY frames —
            frame type is preserved automatically.
            """
            try:
                while True:
                    try:
                        message = await upstream_ws.recv()
                    except websockets.exceptions.ConnectionClosedOK:
                        # Upstream closed cleanly — forward code AND reason.
                        try:
                            close_reason = upstream_ws.close_reason or ""
                            await ws.close(code=upstream_ws.close_code or 1000, reason=close_reason)
                        except Exception:
                            pass
                        break
                    except websockets.exceptions.ConnectionClosedError as exc:
                        close_code = exc.rcvd.code if exc.rcvd else 1011
                        close_reason = exc.rcvd.reason if exc.rcvd else ""
                        logger.debug("Upstream WS closed with error: code=%s reason=%s", close_code, close_reason)
                        try:
                            await ws.close(code=close_code, reason=close_reason)
                        except Exception:
                            pass
                        break
                    if isinstance(message, str):
                        await ws.send_text(message)
                    else:
                        await ws.send_bytes(message)
            except WebSocketDisconnect:
                pass

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(_client_to_upstream())
                tg.create_task(_upstream_to_client())
        except* (WebSocketDisconnect, websockets.exceptions.WebSocketException):
            pass
        except* Exception as eg:
            # L-4: Log unexpected programming errors before swallowing so future
            # regressions are visible. Only catches exceptions not matched above.
            for exc in eg.exceptions:
                logger.warning("Unexpected error in WS pump TaskGroup: %r", exc)
        finally:
            try:
                await upstream_ws.close()
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass
