"""Jupyter REST + WebSocket adapter for VS Code "Existing Jupyter Server".

Maps Jupyter REST API calls to gateway session API. The WebSocket endpoint
at /kernels/{id}/channels implements enough of the Jupyter wire protocol
for VS Code's Run Cell button to work.

VS Code setup:
  1. Cmd+Shift+P → "Jupyter: Specify Jupyter Server for Connections"
  2. Enter: http://localhost:3300/jupyter
  3. Open any .ipynb → select "SignalPilot Python 3" kernel
  4. Run cells normally
"""

from __future__ import annotations

import json
import logging
import os
import struct
import time
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..auth import OrgID, UserID
from ..models.sessions import SessionExecuteRequest
from ..security.scope_guard import RequireScope
from ..store.sessions import delete_session, get_session, list_sessions, upsert_session
from .deps import StoreD, get_sandbox_client_with_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jupyter/api")
root_router = APIRouter(prefix="/jupyter")


def _gateway_url() -> str:
    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")


# ─── Root-level endpoints VS Code probes on connect ─────────────────────────


@root_router.get("")
@root_router.get("/")
async def jupyter_root():
    return {"status": "ok", "implementation": "signalpilot"}


@root_router.get("/tree")
async def jupyter_tree():
    return {"status": "ok"}


@root_router.get("/login")
async def jupyter_login():
    return {"status": "ok"}


@root_router.get("/hub/api")
async def jupyter_hub_api():
    return {"status": "ok"}


# ─── REST endpoints ─────────────────────────────────────────────────────────


@router.get("")
async def jupyter_server_info():
    return {
        "version": "7.0.0",
        "implementation": "signalpilot",
        "implementation_version": "0.1.0",
    }


@router.get("/kernelspecs")
async def jupyter_kernelspecs():
    return {
        "default": "python3",
        "kernelspecs": {
            "python3": {
                "name": "python3",
                "display_name": "SignalPilot Python 3",
                "language": "python",
                "resources": {},
            }
        },
    }


@router.get("/kernels")
async def jupyter_list_kernels(_: UserID, org_id: OrgID):
    """GET /jupyter/api/kernels — VS Code probes this on connect."""
    sessions = list_sessions(org_id)
    return [
        {
            "id": s.id,
            "name": "python3",
            "last_activity": _iso(s.last_active),
            "execution_state": _map_status(s.status),
            "connections": 1,
        }
        for s in sessions
    ]


@router.get("/kernels/{kernel_id}")
async def jupyter_get_kernel(kernel_id: str, _: UserID, org_id: OrgID):
    """GET /jupyter/api/kernels/{kernel_id} — VS Code polls this."""
    session = get_session(kernel_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Kernel not found")
    return {
        "id": session.id,
        "name": "python3",
        "last_activity": _iso(session.last_active),
        "execution_state": _map_status(session.status),
        "connections": 1,
    }


@router.get("/sessions")
async def jupyter_list_sessions(_: UserID, org_id: OrgID):
    sessions = list_sessions(org_id)
    return [_session_to_jupyter(s) for s in sessions]


@router.post("/sessions", status_code=201)
async def jupyter_create_session(store: StoreD):
    session_token = str(uuid.uuid4())
    org_id = store.org_id or ""

    client = await get_sandbox_client_with_store(store)
    result = await client.create_kernel_session(
        session_token=session_token,
        gateway_url=_gateway_url(),
    )

    from ..models.sessions import SessionInfoResponse

    session_info = SessionInfoResponse(
        id=result.get("session_id", str(uuid.uuid4())),
        org_id=org_id,
        status=result.get("status", "idle"),
        created_at=time.time(),
        last_active=time.time(),
    )
    upsert_session(session_info)
    return _session_to_jupyter(session_info)


@router.delete("/sessions/{session_id}", status_code=204)
async def jupyter_delete_session(session_id: str, store: StoreD):
    org_id = store.org_id or ""
    session = get_session(session_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    client = await get_sandbox_client_with_store(store)
    await client.delete_kernel_session(session_id)
    delete_session(session_id, org_id)


@router.post("/kernels/{kernel_id}/execute", dependencies=[RequireScope("execute")])
async def jupyter_execute(kernel_id: str, req: SessionExecuteRequest, store: StoreD):
    """REST-based cell execution (non-standard, for programmatic clients)."""
    org_id = store.org_id or ""
    session = get_session(kernel_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Kernel not found")

    client = await get_sandbox_client_with_store(store)
    result = await client.execute_in_session(
        session_id=kernel_id, code=req.code,
        timeout=req.timeout, cell_id=req.cell_id,
    )

    session.last_active = time.time()
    session.cell_count = result.get("cell_count", session.cell_count + 1)
    upsert_session(session)

    outputs = result.get("outputs", [])
    if not outputs:
        outputs = [
            {
                "output_type": "stream" if result.get("success") else "error",
                "name": "stdout" if result.get("success") else "stderr",
                "text": result.get("output", "") if result.get("success") else result.get("error", ""),
            }
        ]

    return {
        "status": "ok" if result.get("success") else "error",
        "execution_count": result.get("execution_count", session.cell_count),
        "outputs": outputs,
    }


# ─── WebSocket — Jupyter wire protocol for VS Code Run Cell ─────────────────


async def jupyter_websocket(websocket: WebSocket):
    """Jupyter kernel WebSocket channels.

    Mounted as a standalone Starlette app to bypass BaseHTTPMiddleware.
    kernel_id comes from websocket.path_params (Starlette routing).
    """
    kernel_id = websocket.path_params.get("kernel_id", "unknown")
    requested = websocket.headers.get("sec-websocket-protocol", "")
    subprotocol = requested.split(",")[0].strip() if requested else None
    use_v1 = bool(subprotocol and "v1.kernel" in subprotocol)
    await websocket.accept(subprotocol=subprotocol)
    logger.info("jupyter ws connect: kernel=%s proto=%s", kernel_id[:8], "v1" if use_v1 else "v0")

    # Proactively send the full startup sequence a real kernel would send.
    # VS Code waits for kernel_info_reply + status:idle before it considers
    # the kernel ready. Sending both up front avoids a round-trip requirement
    # that may fail through proxies that don't forward client→server WS frames.
    _startup_header = {
        "msg_id": str(uuid.uuid4()), "msg_type": "status",
        "session": "", "username": "", "date": _iso(time.time()), "version": "5.3",
    }
    await _send_jupyter_msg(websocket, "status", {"execution_state": "busy"}, _startup_header, "iopub", use_v1)
    await _send_kernel_info_reply(websocket, _startup_header, use_v1)
    await _send_jupyter_msg(websocket, "status", {"execution_state": "idle"}, _startup_header, "iopub", use_v1)
    logger.info("jupyter ws startup sent: kernel=%s", kernel_id[:8])

    execution_count = 0

    try:
        while True:
            data = await _ws_receive(websocket)
            if data is None:
                continue
            header = data.get("header", {})
            msg_type = header.get("msg_type", "")
            logger.debug("jupyter ws msg: kernel=%s type=%s", kernel_id[:8], msg_type)

            if msg_type == "kernel_info_request":
                await _send_kernel_info_reply(websocket, header, use_v1)
                await _send_jupyter_msg(
                    websocket, "status", {"execution_state": "idle"},
                    header, "iopub", use_v1,
                )

            elif msg_type == "execute_request":
                execution_count += 1
                execution_count = await _handle_execute(websocket, data, kernel_id, execution_count, use_v1)

            elif msg_type == "complete_request":
                await _handle_complete(websocket, data, kernel_id, use_v1)

            elif msg_type == "inspect_request":
                await _handle_inspect(websocket, data, kernel_id, use_v1)

            elif msg_type == "interrupt_request":
                await _handle_interrupt(websocket, data, kernel_id, use_v1)

            elif msg_type == "is_complete_request":
                code = data.get("content", {}).get("code", "")
                await _send_jupyter_msg(
                    websocket, "is_complete_reply",
                    {"status": "incomplete" if code.rstrip().endswith(":") else "complete"},
                    header, "shell", use_v1,
                )

            elif msg_type == "comm_info_request":
                await _send_jupyter_msg(
                    websocket, "comm_info_reply",
                    {"status": "ok", "comms": {}},
                    header, "shell", use_v1,
                )

            elif msg_type == "shutdown_request":
                await _send_jupyter_msg(
                    websocket, "shutdown_reply",
                    {"status": "ok", "restart": False},
                    header, "shell", use_v1,
                )
                break

    except WebSocketDisconnect:
        logger.info("jupyter ws disconnect: kernel=%s", kernel_id[:8])
    except Exception:
        logger.exception("jupyter ws error: kernel=%s", kernel_id[:8])


async def _handle_execute(
    websocket: WebSocket, request: dict, kernel_id: str, execution_count: int,
    use_v1: bool = False,
) -> int:
    """Translate execute_request → sandbox session API → Jupyter iopub messages.

    Returns the execution_count from the kernel (may differ from the local counter).
    """
    parent = request.get("header", {})
    code = request.get("content", {}).get("code", "")

    await _send_jupyter_msg(
        websocket, "status", {"execution_state": "busy"}, parent, "iopub", use_v1,
    )
    await _send_jupyter_msg(
        websocket, "execute_input",
        {"code": code, "execution_count": execution_count},
        parent, "iopub", use_v1,
    )

    from .sessions import get_sandbox_client_from_cache

    client = get_sandbox_client_from_cache()
    success = True
    if client is None:
        success = False
        await _send_jupyter_msg(
            websocket, "error",
            {"ename": "RuntimeError", "evalue": "Sandbox not initialized", "traceback": []},
            parent, "iopub", use_v1,
        )
    else:
        try:
            result = await client.execute_in_session(
                session_id=kernel_id, code=code, timeout=30,
            )

            ec = result.get("execution_count", execution_count)
            if ec:
                execution_count = ec

            outputs = result.get("outputs", [])
            if outputs:
                for out in outputs:
                    out_type = out.get("type", "")
                    if out_type == "stream":
                        await _send_jupyter_msg(
                            websocket, "stream",
                            {"name": out.get("name", "stdout"), "text": out.get("text", "")},
                            parent, "iopub", use_v1,
                        )
                    elif out_type == "execute_result":
                        await _send_jupyter_msg(
                            websocket, "execute_result",
                            {
                                "execution_count": out.get("execution_count", execution_count),
                                "data": out.get("data", {}),
                                "metadata": out.get("metadata", {}),
                            },
                            parent, "iopub", use_v1,
                        )
                    elif out_type in ("display_data", "update_display_data"):
                        await _send_jupyter_msg(
                            websocket, out_type,
                            {
                                "data": out.get("data", {}),
                                "metadata": out.get("metadata", {}),
                                "transient": out.get("transient", {}),
                            },
                            parent, "iopub", use_v1,
                        )
                    elif out_type == "error":
                        success = False
                        await _send_jupyter_msg(
                            websocket, "error",
                            {
                                "ename": out.get("ename", "Error"),
                                "evalue": out.get("evalue", ""),
                                "traceback": out.get("traceback", []),
                            },
                            parent, "iopub", use_v1,
                        )
            elif result.get("success"):
                output = result.get("output", "")
                if output:
                    await _send_jupyter_msg(
                        websocket, "execute_result",
                        {
                            "execution_count": execution_count,
                            "data": {"text/plain": output},
                            "metadata": {},
                        },
                        parent, "iopub", use_v1,
                    )
            else:
                success = False
                error_text = result.get("error", "")
                lines = error_text.split("\n") if error_text else []
                await _send_jupyter_msg(
                    websocket, "error",
                    {
                        "ename": "Error",
                        "evalue": lines[-1] if lines else "",
                        "traceback": lines,
                    },
                    parent, "iopub", use_v1,
                )
        except Exception as e:
            success = False
            await _send_jupyter_msg(
                websocket, "error",
                {"ename": type(e).__name__, "evalue": str(e), "traceback": []},
                parent, "iopub", use_v1,
            )

    await _send_jupyter_msg(
        websocket, "status", {"execution_state": "idle"}, parent, "iopub", use_v1,
    )
    await _send_jupyter_msg(
        websocket, "execute_reply",
        {"status": "ok" if success else "error", "execution_count": execution_count},
        parent, "shell", use_v1,
    )
    return execution_count


async def _handle_complete(
    websocket: WebSocket, request: dict, kernel_id: str, use_v1: bool = False,
) -> None:
    """Forward complete_request to sandbox kernel."""
    parent = request.get("header", {})
    content = request.get("content", {})
    code = content.get("code", "")
    cursor_pos = content.get("cursor_pos", len(code))

    from .sessions import get_sandbox_client_from_cache

    client = get_sandbox_client_from_cache()
    if client:
        try:
            result = await client.complete_in_session(kernel_id, code, cursor_pos)
            await _send_jupyter_msg(
                websocket, "complete_reply",
                {
                    "status": "ok",
                    "matches": result.get("matches", []),
                    "cursor_start": result.get("cursor_start", cursor_pos),
                    "cursor_end": result.get("cursor_end", cursor_pos),
                    "metadata": result.get("metadata", {}),
                },
                parent, "shell", use_v1,
            )
            return
        except Exception:
            pass

    await _send_jupyter_msg(
        websocket, "complete_reply",
        {"status": "ok", "matches": [], "cursor_start": cursor_pos, "cursor_end": cursor_pos, "metadata": {}},
        parent, "shell", use_v1,
    )


async def _handle_inspect(
    websocket: WebSocket, request: dict, kernel_id: str, use_v1: bool = False,
) -> None:
    """Forward inspect_request to sandbox kernel."""
    parent = request.get("header", {})
    content = request.get("content", {})
    code = content.get("code", "")
    cursor_pos = content.get("cursor_pos", len(code))
    detail_level = content.get("detail_level", 0)

    from .sessions import get_sandbox_client_from_cache

    client = get_sandbox_client_from_cache()
    if client:
        try:
            result = await client.inspect_in_session(kernel_id, code, cursor_pos, detail_level)
            await _send_jupyter_msg(
                websocket, "inspect_reply",
                {
                    "status": "ok",
                    "found": result.get("found", False),
                    "data": result.get("data", {}),
                    "metadata": result.get("metadata", {}),
                },
                parent, "shell", use_v1,
            )
            return
        except Exception:
            pass

    await _send_jupyter_msg(
        websocket, "inspect_reply",
        {"status": "ok", "found": False, "data": {}, "metadata": {}},
        parent, "shell", use_v1,
    )


async def _handle_interrupt(
    websocket: WebSocket, request: dict, kernel_id: str, use_v1: bool = False,
) -> None:
    """Forward interrupt_request to sandbox kernel."""
    parent = request.get("header", {})

    from .sessions import get_sandbox_client_from_cache

    client = get_sandbox_client_from_cache()
    if client:
        try:
            await client.interrupt_session(kernel_id)
        except Exception:
            pass

    await _send_jupyter_msg(
        websocket, "interrupt_reply",
        {"status": "ok"},
        parent, "shell", use_v1,
    )


async def _send_kernel_info_reply(websocket: WebSocket, parent: dict, use_v1: bool = False) -> None:
    await _send_jupyter_msg(
        websocket, "kernel_info_reply",
        {
            "status": "ok",
            "protocol_version": "5.3",
            "implementation": "signalpilot",
            "implementation_version": "0.1.0",
            "language_info": {
                "name": "python",
                "version": "3.12",
                "mimetype": "text/x-python",
                "file_extension": ".py",
                "codemirror_mode": {"name": "ipython", "version": 3},
            },
            "banner": "SignalPilot Kernel",
            "help_links": [],
        },
        parent, "shell", use_v1,
    )


# ─── Jupyter v0/v1 wire protocol ────────────────────────────────────────────


async def _ws_receive(websocket: WebSocket) -> dict | None:
    """Receive a Jupyter message, handling both text (v0) and binary (v1)."""
    raw = await websocket.receive()
    msg_type = raw.get("type", "")
    if msg_type == "websocket.disconnect":
        raise WebSocketDisconnect(code=raw.get("code", 1000))
    try:
        if "text" in raw:
            return json.loads(raw["text"])
        if "bytes" in raw and raw["bytes"]:
            return _v1_deserialize(raw["bytes"])
    except Exception:
        logger.debug("failed to parse ws message", exc_info=True)
    return None


def _v1_deserialize(data: bytes) -> dict:
    """Deserialize Jupyter v1 binary wire protocol.

    @jupyterlab/services uses ABSOLUTE offsets from the start of the message.
    Format: n_offsets(uint64 LE) + offsets(n * uint64 LE, absolute) + parts...
    """
    n_offsets = struct.unpack_from("<Q", data, 0)[0]
    offsets = list(struct.unpack_from(f"<{n_offsets}Q", data, 8))

    def part(i: int) -> bytes:
        start = offsets[i]
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        return data[start:end]

    channel = part(0).decode("utf-8")
    header = json.loads(part(1))
    parent_header = json.loads(part(2)) if n_offsets > 2 else {}
    metadata = json.loads(part(3)) if n_offsets > 3 else {}
    content = json.loads(part(4)) if n_offsets > 4 else {}

    return {
        "channel": channel,
        "header": header,
        "parent_header": parent_header,
        "metadata": metadata,
        "content": content,
    }


def _v1_serialize(channel: str, header: dict, parent_header: dict, metadata: dict, content: dict) -> bytes:
    """Serialize a Jupyter message to v1 binary wire protocol.

    Uses ABSOLUTE offsets from the start of the message (matching @jupyterlab/services).
    """
    parts = [
        channel.encode("utf-8"),
        json.dumps(header).encode("utf-8"),
        json.dumps(parent_header).encode("utf-8"),
        json.dumps(metadata).encode("utf-8"),
        json.dumps(content).encode("utf-8"),
    ]
    n = len(parts)
    header_size = 8 + n * 8
    offsets = []
    pos = header_size
    for p in parts:
        offsets.append(pos)
        pos += len(p)

    pre = struct.pack(f"<Q{n}Q", n, *offsets)
    return pre + b"".join(parts)


async def _send_jupyter_msg(
    websocket: WebSocket,
    msg_type: str,
    content: dict,
    parent_header: dict,
    channel: str,
    use_v1: bool = False,
) -> None:
    """Send a Jupyter message over WebSocket (v0 text or v1 binary)."""
    header = {
        "msg_id": str(uuid.uuid4()),
        "msg_type": msg_type,
        "session": parent_header.get("session", ""),
        "username": "",
        "date": _iso(time.time()),
        "version": "5.3",
    }

    if use_v1:
        payload = _v1_serialize(channel, header, parent_header, {}, content)
        await websocket.send_bytes(payload)
        logger.debug("ws send: %s/%s (%d bytes)", channel, msg_type, len(payload))
    else:
        await websocket.send_json({
            "header": header,
            "parent_header": parent_header,
            "metadata": {},
            "content": content,
            "buffers": [],
            "channel": channel,
        })


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _session_to_jupyter(s) -> dict:
    return {
        "id": s.id,
        "name": getattr(s, "label", "") or s.id,
        "path": getattr(s, "label", "") or s.id,
        "type": "notebook",
        "kernel": {
            "id": s.id,
            "name": "python3",
            "last_activity": _iso(s.last_active),
            "execution_state": _map_status(s.status),
            "connections": 1,
        },
    }


def _iso(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


def _map_status(status: str) -> str:
    return {"running": "busy", "idle": "idle", "dead": "dead"}.get(status, "idle")


# ─── Standalone WebSocket ASGI app (bypasses BaseHTTPMiddleware stack) ──────

import re as _re

_CHANNELS_RE = _re.compile(r"^/(?P<kernel_id>[^/]+)/channels")


async def jupyter_ws_asgi(scope, receive, send):
    """Raw ASGI app for Jupyter WebSocket — bypasses all middleware."""
    if scope["type"] != "websocket":
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"Not found"})
        return

    path = scope.get("path", "")
    m = _CHANNELS_RE.match(path)
    if not m:
        await send({"type": "websocket.close", "code": 1008})
        return

    kernel_id = m.group("kernel_id")
    ws = WebSocket(scope, receive, send)
    scope["path_params"] = {"kernel_id": kernel_id}
    await jupyter_websocket(ws)
