"""Branch endpoints over the S3 workspace store.

Branch names that could be used for injection (leading '-', traversal)
are rejected before any gateway call; switching just repoints the
session's working branch.
"""
from __future__ import annotations

import json as json_mod
from unittest.mock import patch

import pytest

from signalpilot._server.files import workspace

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_request(
    body: dict,
    project_id: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
) -> object:
    """Build a real Starlette Request with auth so @requires('edit') passes."""
    from starlette.authentication import AuthCredentials, SimpleUser
    from starlette.requests import Request

    body_bytes = json_mod.dumps(body).encode()

    async def _receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/create",
        "query_string": b"",
        "headers": [
            (b"x-gateway-project-id", project_id.encode()),
            (b"content-type", b"application/json"),
        ],
        "auth": AuthCredentials(["edit"]),
        "user": SimpleUser("test-user"),
    }
    return Request(scope, receive=_receive)


@pytest.fixture
def s3_mode(monkeypatch):
    monkeypatch.setenv("SP_WORKSPACE_MODE", "s3")
    monkeypatch.setenv("SP_PROJECT_ID", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    monkeypatch.setattr(workspace, "_current_branch", "main")


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestBranchValidation:
    """Branch name validation rejects injection strings before any gateway call."""

    @pytest.mark.asyncio
    async def test_create_branch_rejects_dash_prefix(self, s3_mode) -> None:
        from signalpilot._server.api.endpoints.branches import create_branch

        request = _make_request({"name": "-rf"})
        with patch(
            "signalpilot._server.files.workspace.create_file_system"
        ) as mock_fs:
            response = await create_branch(request=request)

        assert response.status_code == 400
        body = json_mod.loads(response.body)
        assert "Invalid branch name" in body["error"]
        mock_fs.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_branch_rejects_dash_prefix_in_from_branch(
        self, s3_mode
    ) -> None:
        from signalpilot._server.api.endpoints.branches import create_branch

        request = _make_request(
            {"name": "ok", "from_branch": "--upload-pack=evil"}
        )
        with patch(
            "signalpilot._server.files.workspace.create_file_system"
        ) as mock_fs:
            response = await create_branch(request=request)

        assert response.status_code == 400
        body = json_mod.loads(response.body)
        assert "Invalid branch name" in body["error"]
        mock_fs.assert_not_called()

    @pytest.mark.asyncio
    async def test_switch_branch_rejects_dash_prefix(self, s3_mode) -> None:
        from signalpilot._server.api.endpoints.branches import switch_branch

        request = _make_request({"branch": "-rf"})
        response = await switch_branch(request=request)

        assert response.status_code == 400
        body = json_mod.loads(response.body)
        assert "Invalid branch name" in body["error"]
        assert workspace.current_branch() == "main"

    @pytest.mark.asyncio
    async def test_switch_branch_rejects_traversal(self, s3_mode) -> None:
        from signalpilot._server.api.endpoints.branches import switch_branch

        request = _make_request({"branch": "a/../b"})
        response = await switch_branch(request=request)

        assert response.status_code == 400
        assert workspace.current_branch() == "main"


class TestBranchSwitch:
    """Switching a branch is just repointing the working branch (S3 has
    every branch); the next GatewayFileSystem is constructed against it."""

    @pytest.mark.asyncio
    async def test_switch_updates_current_branch(self, s3_mode) -> None:
        from signalpilot._server.api.endpoints.branches import switch_branch

        request = _make_request({"branch": "agent/feature-1"})
        response = await switch_branch(request=request)

        assert response.status_code == 200
        body = json_mod.loads(response.body)
        assert body == {"branch": "agent/feature-1", "switched": True}
        assert workspace.current_branch() == "agent/feature-1"

    @pytest.mark.asyncio
    async def test_switch_to_same_branch_is_noop(self, s3_mode) -> None:
        from signalpilot._server.api.endpoints.branches import switch_branch

        request = _make_request({"branch": "main"})
        response = await switch_branch(request=request)

        assert response.status_code == 200
        assert json_mod.loads(response.body) == {
            "branch": "main",
            "switched": False,
        }

    @pytest.mark.asyncio
    async def test_current_reports_active_branch(self, s3_mode) -> None:
        from signalpilot._server.api.endpoints.branches import (
            get_current_branch,
        )

        response = await get_current_branch(request=_make_request({}))
        assert json_mod.loads(response.body) == {"active_branch": "main"}

    @pytest.mark.asyncio
    async def test_non_s3_mode_rejects_switch(self, monkeypatch) -> None:
        from signalpilot._server.api.endpoints.branches import switch_branch

        monkeypatch.delenv("SP_WORKSPACE_MODE", raising=False)
        monkeypatch.setattr(workspace, "_current_branch", "main")
        response = await switch_branch(
            request=_make_request({"branch": "other"})
        )
        assert response.status_code == 400
