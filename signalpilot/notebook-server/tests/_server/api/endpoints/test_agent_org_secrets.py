from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self

import pytest

if TYPE_CHECKING:
    from types import TracebackType


class _Response:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _clear_ai_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in (
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OAUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "SP_API_KEY",
        "SP_SESSION_JWT",
    ):
        monkeypatch.delenv(name, raising=False)
    config_dir = tmp_path / "claude-config"
    config_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("SP_GATEWAY_URL", "https://gateway.test")


@pytest.mark.asyncio
async def test_agent_auth_status_checks_gateway_org_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _clear_ai_env(monkeypatch, tmp_path)
    calls: list[str] = []

    class AsyncClient:
        def __init__(self, *, timeout: float):
            assert timeout == 5.0

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> bool:
            return False

        async def get(self, url: str, **kwargs: object) -> _Response:
            calls.append(url)
            assert "headers" in kwargs
            return _Response({"has_key": True})

    monkeypatch.setattr("httpx.AsyncClient", AsyncClient)

    from signalpilot._server.api.endpoints.agent import agent_auth_status

    response = await agent_auth_status(request=object())
    body = json.loads(response.body)

    assert calls == ["https://gateway.test/api/org/secrets"]
    assert body == {"configured": True, "method": "gateway"}


def test_claude_auth_config_checks_org_secrets_but_does_not_fetch_raw_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _clear_ai_env(monkeypatch, tmp_path)
    calls: list[str] = []

    def get(url: str, **kwargs: object):
        calls.append(url)
        assert kwargs["timeout"] == 5.0
        return _Response({"has_key": True})

    monkeypatch.setattr("httpx.get", get)

    from signalpilot._server.ai.claude_agent import _get_auth_config

    with pytest.raises(ValueError, match="integrations page"):
        _get_auth_config()

    assert calls == ["https://gateway.test/api/org/secrets"]
