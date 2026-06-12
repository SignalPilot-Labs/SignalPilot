"""R11-S-2: _validate_branch called in create/delete/switch branch handlers.

Verifies that branch names starting with '-' (and other invalid patterns)
are rejected before any git subprocess is called.
"""
from __future__ import annotations

import json as json_mod
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_repo(tmp_path: Path) -> Path:
    """Return a temp dir with a .git subdirectory so _get_repo returns it."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


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


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestBranchValidation:
    """R11-S-2: branch name validation rejects injection strings before subprocess."""

    @pytest.mark.asyncio
    async def test_create_branch_rejects_dash_prefix(self, tmp_path: Path) -> None:
        """POST /create with name='-rf' returns 400; run_git never called."""
        from signalpilot._server.api.endpoints.branches import create_branch

        repo = _make_repo(tmp_path)
        request = _make_request({"name": "-rf"})

        with patch("signalpilot._server.api.endpoints.branches._get_repo", return_value=repo), \
             patch("signalpilot._server.api.endpoints.branches.run_git") as mock_git, \
             patch("signalpilot._server.api.endpoints.branches.run_git_authed") as mock_git_authed:
            response = await create_branch(request=request)

        assert response.status_code == 400
        body = json_mod.loads(response.body)
        assert "Invalid branch name" in body["error"]
        mock_git.assert_not_called()
        mock_git_authed.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_branch_rejects_dash_prefix_in_from_branch(self, tmp_path: Path) -> None:
        """POST /create with from_branch='--upload-pack=evil' returns 400; run_git never called."""
        from signalpilot._server.api.endpoints.branches import create_branch

        repo = _make_repo(tmp_path)
        request = _make_request({"name": "ok", "from_branch": "--upload-pack=evil"})

        with patch("signalpilot._server.api.endpoints.branches._get_repo", return_value=repo), \
             patch("signalpilot._server.api.endpoints.branches.run_git") as mock_git, \
             patch("signalpilot._server.api.endpoints.branches.run_git_authed") as mock_git_authed:
            response = await create_branch(request=request)

        assert response.status_code == 400
        body = json_mod.loads(response.body)
        assert "Invalid branch name" in body["error"]
        mock_git.assert_not_called()
        mock_git_authed.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_branch_rejects_dash_prefix(self, tmp_path: Path) -> None:
        """POST /delete with name='-D' returns 400; run_git never called."""
        from signalpilot._server.api.endpoints.branches import delete_branch

        repo = _make_repo(tmp_path)
        request = _make_request({"name": "-D"})

        with patch("signalpilot._server.api.endpoints.branches._get_repo", return_value=repo), \
             patch("signalpilot._server.api.endpoints.branches.run_git") as mock_git, \
             patch("signalpilot._server.api.endpoints.branches.run_git_authed") as mock_git_authed:
            response = await delete_branch(request=request)

        assert response.status_code == 400
        body = json_mod.loads(response.body)
        assert "Invalid branch name" in body["error"]
        mock_git.assert_not_called()
        mock_git_authed.assert_not_called()

    @pytest.mark.asyncio
    async def test_switch_branch_rejects_dash_prefix(self, tmp_path: Path) -> None:
        """POST /switch with branch='-rf' returns 400; run_git never called."""
        from signalpilot._server.api.endpoints.branches import switch_branch

        repo = _make_repo(tmp_path)
        request = _make_request({"branch": "-rf"})

        with patch("signalpilot._server.api.endpoints.branches._get_repo", return_value=repo), \
             patch("signalpilot._server.api.endpoints.branches.run_git") as mock_git, \
             patch("signalpilot._server.api.endpoints.branches.run_git_authed") as mock_git_authed:
            response = await switch_branch(request=request)

        assert response.status_code == 400
        body = json_mod.loads(response.body)
        assert "Invalid branch name" in body["error"]
        mock_git.assert_not_called()
        mock_git_authed.assert_not_called()
