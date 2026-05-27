# Copyright 2026 SignalPilot. All rights reserved.
"""Proxy endpoints for the SignalPilot gateway chat API.

Uses a keep-alive HTTP connection to avoid the 2s TCP connect penalty
caused by Windows IPv6 fallback on localhost.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import threading
from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse

from signalpilot._server.router import APIRouter

router = APIRouter()

_GATEWAY_URL = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
_SESSION_JWT = os.environ.get("SP_SESSION_JWT", "")
_API_KEY = os.environ.get("SP_API_KEY", "")

_parsed = urlparse(_GATEWAY_URL)
# Use 127.0.0.1 instead of localhost to avoid Windows IPv6 DNS fallback
_GW_HOST = "127.0.0.1" if (_parsed.hostname or "").lower() == "localhost" else (_parsed.hostname or "localhost")
_GW_PORT = _parsed.port or 3300

_lock = threading.Lock()
_conn: http.client.HTTPConnection | None = None


def _get_conn() -> http.client.HTTPConnection:
    global _conn
    if _conn is None:
        _conn = http.client.HTTPConnection(_GW_HOST, _GW_PORT, timeout=10)
    return _conn


def _reset_conn() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None


def _gw_sync(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    headers = {
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }
    if _SESSION_JWT:
        headers["Authorization"] = f"Bearer {_SESSION_JWT}"
    elif _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"

    data = json.dumps(body).encode() if body else None

    with _lock:
        for attempt in range(2):
            try:
                conn = _get_conn()
                conn.request(method, path, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
                if resp.status >= 400:
                    return {"_error": True, "status": resp.status, "detail": raw.decode("utf-8", errors="replace")[:500]}
                return json.loads(raw) if raw else None
            except (ConnectionError, OSError, http.client.RemoteDisconnected):
                _reset_conn()
                if attempt == 1:
                    return {"_error": True, "status": 502, "detail": "Gateway unreachable"}


async def _gw(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    return await asyncio.to_thread(_gw_sync, method, path, body)


def _respond(result: Any) -> JSONResponse:
    if isinstance(result, dict) and result.get("_error"):
        return JSONResponse(
            {"detail": result.get("detail", "Gateway error")},
            status_code=result.get("status", 502),
        )
    return JSONResponse(result)


# ── Conversations ────────────────────────────────────────────────

@router.post("/conversations")
async def create_conversation(request: Request) -> JSONResponse:
    body = await request.json()
    return _respond(await _gw("POST", "/api/chat/conversations", body))


@router.get("/conversations")
async def list_conversations(request: Request) -> JSONResponse:
    qs = ""
    params = dict(request.query_params)
    if params:
        from urllib.parse import urlencode
        qs = "?" + urlencode(params)
    return _respond(await _gw("GET", f"/api/chat/conversations{qs}"))


@router.get("/conversations/{conversation_id}")
async def get_conversation(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    return _respond(await _gw("GET", f"/api/chat/conversations/{cid}"))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    return _respond(await _gw("DELETE", f"/api/chat/conversations/{cid}"))


# ── Messages ─────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/messages")
async def append_message(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    body = await request.json()
    return _respond(await _gw("POST", f"/api/chat/conversations/{cid}/messages", body))


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    qs = ""
    params = dict(request.query_params)
    if params:
        from urllib.parse import urlencode
        qs = "?" + urlencode(params)
    return _respond(await _gw("GET", f"/api/chat/conversations/{cid}/messages{qs}"))
