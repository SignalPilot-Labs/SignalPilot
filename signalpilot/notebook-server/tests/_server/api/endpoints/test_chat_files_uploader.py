"""Multipart contract, retry, and never-raise behavior of the uploader."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Self

import httpx
import pytest

from signalpilot._server.api.endpoints.chat_files.capture import CapturedFile
from signalpilot._server.api.endpoints.chat_files.uploader import (
    RuntimeFileUploader,
)


def _file(path: str = "artifacts/x.png", data: bytes = b"\x89PNGdata") -> CapturedFile:
    return CapturedFile(
        path=path, data=data, content_hash=hashlib.sha256(data).hexdigest()
    )


def _uploader(
    handler: Any, **kwargs: Any
) -> RuntimeFileUploader:
    return RuntimeFileUploader(
        gateway_api_url="http://gateway:3300/",
        scoped_token="scoped-token",
        run_id="run-1",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_multipart_shape_matches_the_gateway_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            201,
            json={
                "file_id": "f1",
                "path": "artifacts/x.png",
                "kind": "image",
                "byte_size": 8,
                "content_hash": "h",
            },
        )

    file = _file()
    outcomes = await _uploader(handler).upload_many(
        [file], reason="tool", tool_call_id="toolu_1"
    )

    assert [(o.path, o.ok, o.status_code, o.unchanged) for o in outcomes] == [
        ("artifacts/x.png", True, 201, False)
    ]
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://gateway:3300/api/chat/runtime-files"
    assert request.headers["authorization"] == "Bearer scoped-token"
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    body = request.read()
    assert b'name="path"\r\n\r\nartifacts/x.png\r\n' in body
    assert (
        f'name="content_hash"\r\n\r\n{file.content_hash}\r\n'.encode() in body
    )
    assert b'name="tool_call_id"\r\n\r\ntoolu_1\r\n' in body
    assert b'name="reason"\r\n\r\ntool\r\n' in body
    assert b'name="file"; filename="x.png"' in body
    assert b"Content-Type: application/octet-stream" in body
    assert b"\x89PNGdata" in body
    assert b'name="deleted"' not in body


@pytest.mark.asyncio
async def test_deleted_file_sends_the_flag_and_no_file_part() -> None:
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.read())
        return httpx.Response(200, json={"file_id": "f1", "deleted": True})

    deleted = CapturedFile(
        path="artifacts/gone.csv",
        data=b"",
        content_hash=hashlib.sha256(b"").hexdigest(),
        deleted=True,
    )
    outcomes = await _uploader(handler).upload_many(
        [deleted], reason="run_end", tool_call_id=None
    )

    assert outcomes[0].ok is True
    assert outcomes[0].deleted is True
    body = seen[0]
    assert b'name="deleted"\r\n\r\n1\r\n' in body
    assert b'name="path"\r\n\r\nartifacts/gone.csv\r\n' in body
    assert b'name="tool_call_id"' not in body
    assert b'name="file"' not in body


@pytest.mark.asyncio
async def test_unchanged_response_is_reported() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"file_id": "f1", "unchanged": True})

    outcome = await _uploader(handler).upload_one(
        _file(), reason="tool", tool_call_id="t"
    )
    assert outcome.ok is True
    assert outcome.unchanged is True


@pytest.mark.asyncio
async def test_retries_once_on_5xx_then_gives_up() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"detail": "busy"})

    outcome = await _uploader(handler).upload_one(
        _file(), reason="tool", tool_call_id="t"
    )
    assert attempts == 2
    assert outcome.ok is False
    assert outcome.status_code == 503
    assert outcome.retried is True


@pytest.mark.asyncio
async def test_retries_once_on_connection_error_then_succeeds() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(201, json={"file_id": "f1"})

    outcome = await _uploader(handler).upload_one(
        _file(), reason="tool", tool_call_id="t"
    )
    assert attempts == 2
    assert outcome.ok is True
    assert outcome.retried is True


@pytest.mark.asyncio
async def test_client_errors_are_not_retried() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(413, json={"detail": "too large"})

    outcome = await _uploader(handler).upload_one(
        _file(), reason="tool", tool_call_id="t"
    )
    assert attempts == 1
    assert outcome.ok is False
    assert outcome.status_code == 413


@pytest.mark.asyncio
async def test_timeout_and_unexpected_errors_never_raise() -> None:
    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    outcome = await _uploader(timeout_handler).upload_one(
        _file(), reason="tool", tool_call_id="t"
    )
    assert outcome.ok is False

    def broken_handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("unexpected")

    outcome = await _uploader(broken_handler).upload_one(
        _file(), reason="tool", tool_call_id="t"
    )
    assert outcome.ok is False

    # A fake client installed by other tests must not break the run either.
    class BrokenClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, _url: str, **kwargs: Any) -> Any:
            return kwargs["json"]

    uploader = RuntimeFileUploader(
        gateway_api_url="http://gateway:3300",
        scoped_token="t",
        run_id="run-1",
    )
    uploader._client = lambda: BrokenClient()  # type: ignore[method-assign]
    outcomes = await uploader.upload_many(
        [_file()], reason="tool", tool_call_id="t"
    )
    assert [o.ok for o in outcomes] == [False]


@pytest.mark.asyncio
async def test_concurrency_is_bounded() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return httpx.Response(201, json={"file_id": "f"})

    files = [_file(path=f"artifacts/{index}.csv") for index in range(10)]
    outcomes = await _uploader(handler, concurrency=3).upload_many(
        files, reason="tool", tool_call_id="t"
    )
    assert all(o.ok for o in outcomes)
    assert peak <= 3
    assert peak >= 2


def test_default_limits() -> None:
    uploader = RuntimeFileUploader(
        gateway_api_url="http://gateway:3300",
        scoped_token="t",
        run_id="run-1",
    )
    assert uploader.concurrency == 4
    assert uploader.timeout == 30.0
    assert json.dumps({"url": uploader.url}) == json.dumps(
        {"url": "http://gateway:3300/api/chat/runtime-files"}
    )
