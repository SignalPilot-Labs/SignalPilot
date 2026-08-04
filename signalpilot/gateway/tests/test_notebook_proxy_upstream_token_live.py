"""Live proof that the proxy's injected credential actually authenticates upstream.

The unit tests assert the header is built; only a real token-enabled notebook proves
the notebook accepts it (and rejects its absence). Point at a throwaway instance:

    docker run -d --name sp-tokentest -p 127.0.0.1:2798:2718 signalpilot-notebook
    SP_NB_LIVE_BASE_URL=http://127.0.0.1:2798 \
    SP_NB_LIVE_TOKEN=$(docker exec sp-tokentest cat /home/notebook/.sp/notebook_token) \
        pytest tests/test_notebook_proxy_upstream_token_live.py
"""

from __future__ import annotations

import os

import pytest

BASE_URL = (os.environ.get("SP_NB_LIVE_BASE_URL") or "").rstrip("/")
TOKEN = os.environ.get("SP_NB_LIVE_TOKEN") or ""

pytestmark = pytest.mark.skipif(
    not (BASE_URL and TOKEN),
    reason="set SP_NB_LIVE_BASE_URL and SP_NB_LIVE_TOKEN (see module docstring)",
)

# Edit-gated on the notebook side, so it answers 401 without a credential.
PROBE_PATH = "api/dbt/project_info"


def _request(headers: dict[str, str]):
    """Minimal Starlette Request that NotebookProxy.forward_http accepts."""
    from starlette.requests import Request

    raw = [(k.encode(), v.encode()) for k, v in headers.items()]
    body = b"{}"
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": f"/notebook/sess-1/{PROBE_PATH}",
            "raw_path": f"/notebook/sess-1/{PROBE_PATH}".encode(),
            "query_string": b"",
            "headers": raw,
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 3300),
        },
        receive,
    )


async def _drain(response) -> tuple[int, bytes]:
    chunks = [chunk async for chunk in response.body_iterator]
    return response.status_code, b"".join(chunks)


@pytest.mark.asyncio
async def test_proxy_without_token_is_rejected_upstream():
    """Control: proves the target really has auth on, so the next test means something."""
    import httpx

    from gateway.notebook_proxy.proxy import NotebookProxy

    async with httpx.AsyncClient() as client:
        proxy = NotebookProxy(BASE_URL, http_client=client, upstream_token=None)
        status, _ = await _drain(
            await proxy.forward_http(
                _request({"content-type": "application/json"}), PROBE_PATH
            )
        )
    assert status == 401, f"target is not token-enabled (got {status})"


@pytest.mark.asyncio
async def test_proxy_with_token_reaches_the_handler():
    import httpx

    from gateway.notebook_proxy.proxy import NotebookProxy

    async with httpx.AsyncClient() as client:
        proxy = NotebookProxy(BASE_URL, http_client=client, upstream_token=TOKEN)
        status, body = await _drain(
            await proxy.forward_http(
                _request({"content-type": "application/json"}), PROBE_PATH
            )
        )
    assert status == 200, f"proxy credential was not accepted: {status} {body[:200]!r}"


@pytest.mark.asyncio
async def test_caller_bearer_is_replaced_not_forwarded():
    """A browser's own bearer must not be what authenticates to the notebook."""
    import httpx

    from gateway.notebook_proxy.proxy import NotebookProxy

    headers = {
        "content-type": "application/json",
        "authorization": "Bearer not-the-notebook-token",
        "cookie": "__session=clerk",
    }
    async with httpx.AsyncClient() as client:
        proxy = NotebookProxy(BASE_URL, http_client=client, upstream_token=TOKEN)
        status, _ = await _drain(
            await proxy.forward_http(_request(headers), PROBE_PATH)
        )
    assert status == 200, status

    async with httpx.AsyncClient() as client:
        proxy = NotebookProxy(BASE_URL, http_client=client, upstream_token=None)
        status, _ = await _drain(
            await proxy.forward_http(_request(headers), PROBE_PATH)
        )
    assert status == 401, f"caller bearer leaked through to upstream (got {status})"


def _ensure_probe_notebook(name: str) -> None:
    """Create a notebook in the target's workspace so /ws can open a session."""
    import httpx

    response = httpx.post(
        f"{BASE_URL}/api/files/create",
        headers={"Authorization": f"Bearer {TOKEN}"},
        data={"path": "", "type": "file", "name": name},
        timeout=30.0,
    )
    assert response.status_code == 200, response.text[:300]


@pytest.mark.asyncio
async def test_websocket_handshake_authenticates_with_the_token():
    """The WS upstream path carries the credential too.

    /ws closes pre-accept on auth failure, which the client sees as HTTP 403; a
    successful handshake reaches 101 and the kernel's first frame. The probe needs a
    resolvable file_key, hence the scaffolded notebook.
    """
    import asyncio

    import websockets
    import websockets.asyncio.client

    name = "sp_proxy_token_probe.py"
    _ensure_probe_notebook(name)
    url = (
        "ws://"
        + BASE_URL.removeprefix("http://")
        + f"/ws?session_id=live-probe&file={name}"
    )

    with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
        await websockets.asyncio.client.connect(url)
    assert exc.value.response.status_code in (401, 403)

    conn = await websockets.asyncio.client.connect(
        url, additional_headers=[("authorization", f"Bearer {TOKEN}")]
    )
    try:
        assert await asyncio.wait_for(conn.recv(), 30) is not None
    finally:
        await conn.close()
