"""Public capability redemption; storage stays private behind the gateway."""

import asyncio
import hashlib
import re
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from gateway.agent_execution.downloads import DOWNLOAD_PATH, redeem_download
from gateway.db.engine import get_session_factory
from gateway.standalone_chat.object_storage import chat_object_storage, conversation_prefix

router = APIRouter()
MAX_BYTES = 100 * 1024 * 1024
HEADERS = {
    "Cache-Control": "no-store", "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
}


@router.get(DOWNLOAD_PATH, include_in_schema=False)
async def download_page():
    nonce = secrets.token_urlsafe(24)
    html = Path(__file__).with_name("artifact_download.html").read_text(encoding="utf-8")
    headers = {**HEADERS, "Content-Security-Policy":
               f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}
    return HTMLResponse(html.replace("__NONCE__", nonce), headers=headers)


def unavailable(status=404):
    return JSONResponse({"detail": "Download unavailable. Request a new link through SignalPilot."}, status_code=status, headers=HEADERS)


@router.post(DOWNLOAD_PATH, include_in_schema=False)
async def download_file(request: Request):
    if request.headers.get("range"):
        return unavailable(416)
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        return unavailable(400)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 256:
            return unavailable(400)
    try:
        import json
        data = json.loads(body)
        token = data.get("token") if isinstance(data, dict) else None
    except (ValueError, UnicodeDecodeError):
        return unavailable(400)
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return unavailable()
    async with get_session_factory()() as db:
        grant = await redeem_download(db, token)
    if grant is None:
        return unavailable()
    if not grant.object_key.startswith(conversation_prefix(grant.org_id, grant.conversation_id) + "/exports/"):
        return unavailable()
    try:
        content = await chat_object_storage().get_bytes(grant.object_key, max_bytes=MAX_BYTES)
        digest = await asyncio.to_thread(lambda: hashlib.sha256(content).hexdigest())
        if len(content) != grant.byte_size or digest != grant.content_hash:
            return unavailable(502)
    except Exception:
        return unavailable(502)

    async def chunks():
        for offset in range(0, len(content), 64 * 1024):
            yield content[offset:offset + 64 * 1024]

    return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
        **HEADERS, "Content-Length": str(len(content)),
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(grant.filename, safe=""),
    })
