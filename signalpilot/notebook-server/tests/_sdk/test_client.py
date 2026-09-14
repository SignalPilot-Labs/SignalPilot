"""GatewayClient: transient failures between the sandbox and the gateway are
retried; every other HTTP error is final."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from signalpilot._sdk import _client as client_module
from signalpilot._sdk._client import GatewayClient


class Response:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._raw


def _http_error(code: int) -> HTTPError:
    return HTTPError("http://gw/api/query", code, "err", {}, io.BytesIO(b"upstream unavailable"))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", lambda s: slept.append(s))
    return slept


def _client() -> GatewayClient:
    return GatewayClient("http://gw", token="t")


def test_retries_503_then_succeeds(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]):
    attempts = iter([_http_error(503), _http_error(502), Response({"rows": [1]})])
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        result = next(attempts)
        if isinstance(result, HTTPError):
            raise result
        return result

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    assert _client().post("/api/query", {"sql": "select 1"}) == {"rows": [1]}
    assert len(calls) == 3
    assert no_sleep == [0.5, 1.5]


def test_gives_up_after_the_retry_budget(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(1)
        raise _http_error(503)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match=r"Gateway error \(HTTP 503\)"):
        _client().get("/api/connections")
    assert len(calls) == client_module._RETRY_ATTEMPTS + 1
    assert no_sleep == list(client_module._RETRY_BACKOFF_SECONDS[: client_module._RETRY_ATTEMPTS])


@pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 422, 500])
def test_other_http_errors_are_final(code: int, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(1)
        raise _http_error(code)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match=rf"Gateway error \(HTTP {code}\)"):
        _client().post("/api/query", {})
    assert calls == [1]
    assert no_sleep == []


def test_connection_errors_retry_then_fail(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(1)
        raise URLError("connection reset")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Cannot reach gateway"):
        _client().get("/api/connections")
    assert len(calls) == client_module._RETRY_ATTEMPTS + 1


def test_connection_error_then_success(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]):
    attempts = iter([URLError("reset"), Response({"ok": True})])

    def fake_urlopen(req, timeout):
        result = next(attempts)
        if isinstance(result, URLError):
            raise result
        return result

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    assert _client().get("/api/connections") == {"ok": True}
    assert no_sleep == [0.5]


def test_download_retries_503_then_streams(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float], tmp_path):
    class Stream:
        def __init__(self, chunks):
            self._chunks = iter(chunks)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size):
            return next(self._chunks, b"")

    attempts = iter([_http_error(503), Stream([b"ab", b"cd"])])

    def fake_urlopen(req, timeout):
        result = next(attempts)
        if isinstance(result, HTTPError):
            raise result
        return result

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    target = tmp_path / "out.bin"
    _client().download("/api/obj", target)
    assert target.read_bytes() == b"abcd"
    assert no_sleep == [0.5]


def test_download_removes_a_partial_file_on_stream_failure(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float], tmp_path):
    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size):
            raise URLError("reset mid-stream")

    monkeypatch.setattr(client_module, "urlopen", lambda req, timeout: Broken())
    target = tmp_path / "out.bin"
    with pytest.raises(RuntimeError, match="Download interrupted"):
        _client().download("/api/obj", target)
    assert not target.exists()
    assert no_sleep == []
