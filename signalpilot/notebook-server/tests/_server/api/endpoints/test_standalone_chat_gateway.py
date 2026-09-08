"""Scoped gateway calls made by standalone Data Chat."""

from __future__ import annotations

from typing import Any, Self

import pytest

from signalpilot._server.api.endpoints import standalone_chat_gateway
from signalpilot._server.api.endpoints.standalone_chat_gateway import (
    StandaloneGatewayClient,
    gateway_api_base_url,
)


def test_gateway_api_base_url_strips_the_mcp_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SP_GATEWAY_INTERNAL_URL", "http://gateway:3300/mcp/")
    assert gateway_api_base_url() == "http://gateway:3300"


def test_gateway_client_has_no_dashboard_authoring_surface() -> None:
    assert not hasattr(StandaloneGatewayClient, "dashboard_authoring_tool")
    assert not hasattr(
        standalone_chat_gateway, "DASHBOARD_AUTHORING_TIMEOUT_SECONDS"
    )


@pytest.mark.asyncio
async def test_post_json_preserves_safe_gateway_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        is_error = True

        def json(self) -> dict[str, str]:
            return {"detail": "Gateway is temporarily unavailable."}

    class Client:
        def __init__(self, *, timeout: float) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, *_args: Any, **_kwargs: Any) -> Response:
            return Response()

    monkeypatch.setattr(standalone_chat_gateway.httpx, "AsyncClient", Client)
    client = StandaloneGatewayClient(
        gateway_url="http://gateway:3300",
        token="scoped-token",
        run_id="run-1",
    )

    with pytest.raises(
        ValueError,
        match="Tool failed: Gateway is temporarily unavailable",
    ):
        await client._post_json(
            "/api/anything",
            payload={},
            invalid="Invalid result",
            failed="Tool failed",
        )
