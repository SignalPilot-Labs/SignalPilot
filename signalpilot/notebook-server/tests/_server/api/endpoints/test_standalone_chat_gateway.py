"""Scoped gateway calls made by standalone Data Chat."""

from __future__ import annotations

from typing import Any, Self

import pytest

from signalpilot._server.api.endpoints import standalone_chat_gateway
from signalpilot._server.api.endpoints.standalone_chat_gateway import (
    StandaloneGatewayClient,
)


@pytest.mark.asyncio
async def test_begin_dashboard_authoring_is_bound_to_the_active_chat_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class Response:
        def json(self) -> dict[str, Any]:
            return {
                "status": "planning",
                "authoring_session_id": "authoring-session-1",
            }

    class Client:
        def __init__(self, *, timeout: float) -> None:
            observed["timeout"] = timeout

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> Response:
            observed.update(url=url, **kwargs)
            return Response()

    monkeypatch.setattr(standalone_chat_gateway.httpx, "AsyncClient", Client)
    client = StandaloneGatewayClient(
        gateway_url="http://gateway:3300",
        token="scoped-token",
        run_id="run-dashboard-1",
    )

    result = await client.dashboard_authoring_tool(
        "begin_dashboard_authoring",
        {
            "request": "Create an executive revenue dashboard",
            "timezone": "America/Sao_Paulo",
        },
    )

    assert result["authoring_session_id"] == "authoring-session-1"
    assert observed == {
        "timeout": 1_200.0,
        "url": "http://gateway:3300/api/dashboard-authoring/begin",
        "json": {
            "request": "Create an executive revenue dashboard",
            "timezone": "America/Sao_Paulo",
        },
        "headers": {"Authorization": "Bearer scoped-token"},
    }


@pytest.mark.asyncio
async def test_dashboard_authoring_tool_preserves_safe_gateway_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        is_error = True

        def json(self) -> dict[str, str]:
            return {
                "detail": "Dashboard authoring is temporarily unavailable. Please try again."
            }

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
        run_id="run-dashboard-1",
    )

    with pytest.raises(
        ValueError,
        match=(
            "Dashboard authoring tool failed: Dashboard authoring is "
            "temporarily unavailable"
        ),
    ):
        await client.dashboard_authoring_tool(
            "set_dashboard_plan",
            {
                "authoring_session_id": "authoring-session-1",
                "authoring_contract_version": "2026-09-02.1",
                "expected_plan_revision": 0,
                "plan": {},
            },
        )


@pytest.mark.asyncio
async def test_dashboard_chart_tool_routes_by_session_and_chart_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class Response:
        def json(self) -> dict[str, Any]:
            return {
                "status": "ready",
                "authoring_session_id": "authoring-session-1",
                "chart_id": "revenue-trend",
            }

    class Client:
        def __init__(self, *, timeout: float) -> None:
            observed["timeout"] = timeout

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> Response:
            observed.update(url=url, **kwargs)
            return Response()

    monkeypatch.setattr(standalone_chat_gateway.httpx, "AsyncClient", Client)
    client = StandaloneGatewayClient(
        gateway_url="http://gateway:3300",
        token="scoped-token",
        run_id="run-dashboard-2",
    )

    await client.dashboard_authoring_tool(
        "upsert_dashboard_chart",
        {
            "authoring_session_id": "authoring-session-1",
            "chart_id": "revenue-trend",
            "authoring_contract_version": "2026-09-02.1",
            "plan_revision": 1,
            "chart": {"id": "revenue-trend"},
            "tool_call_id": "tool-chart-1",
        },
    )

    assert observed["url"].endswith(
        "/api/dashboard-authoring/sessions/authoring-session-1/charts/revenue-trend"
    )
    assert observed["json"] == {
        "authoring_contract_version": "2026-09-02.1",
        "plan_revision": 1,
        "chart": {"id": "revenue-trend"},
        "tool_call_id": "tool-chart-1",
    }
