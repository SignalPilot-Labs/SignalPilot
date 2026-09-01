"""Scoped gateway calls made by standalone Data Chat."""

from __future__ import annotations

from typing import Any, Self

import pytest

from signalpilot._server.api.endpoints import standalone_chat_gateway
from signalpilot._server.api.endpoints.standalone_chat_gateway import (
    StandaloneGatewayClient,
)


@pytest.mark.asyncio
async def test_dashboard_preview_is_bound_to_the_chat_project_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"id": "authoring-session-1", "definition": {"charts": []}}

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

    result = await client.create_dashboard_preview(
        request="Create an executive revenue dashboard",
        project_id="project-1",
        branch="main",
        commit_sha="a" * 40,
        timezone="America/Sao_Paulo",
    )

    assert result["id"] == "authoring-session-1"
    assert observed == {
        "timeout": 300.0,
        "url": "http://gateway:3300/api/dashboard-authoring/sessions",
        "json": {
            "prompt": "Create an executive revenue dashboard",
            "project_id": "project-1",
            "branch": "main",
            "commit_sha": "a" * 40,
            "timezone": "America/Sao_Paulo",
        },
        "headers": {"Authorization": "Bearer scoped-token"},
    }


@pytest.mark.asyncio
async def test_dashboard_preview_preserves_safe_gateway_error(
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
            "Dashboard preview could not be created: Dashboard authoring is "
            "temporarily unavailable"
        ),
    ):
        await client.create_dashboard_preview(
            request="Create a dashboard",
            project_id="project-1",
            branch="main",
            commit_sha="a" * 40,
            timezone="UTC",
        )


@pytest.mark.asyncio
async def test_dashboard_refinement_updates_the_active_authoring_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"id": "authoring-session-1", "definition": {"charts": []}}

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

    await client.create_dashboard_preview(
        request="Make the revenue trend a line chart",
        project_id="project-1",
        branch="main",
        commit_sha="a" * 40,
        timezone="UTC",
        authoring_session_id="authoring-session-1",
    )

    assert observed["url"].endswith(
        "/api/dashboard-authoring/sessions/authoring-session-1/messages"
    )
    assert observed["json"] == {"prompt": "Make the revenue trend a line chart"}
