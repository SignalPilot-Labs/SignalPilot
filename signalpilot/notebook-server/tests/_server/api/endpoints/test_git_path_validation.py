"""R11-S-3: Path-traversal validation on git_stage and git_unstage.

Verifies that absolute paths and parent-directory traversal are rejected
before any subprocess is called.
"""
from __future__ import annotations

import json as json_mod
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_request(body: dict) -> MagicMock:
    """Build a minimal Starlette Request using real scope so @requires works."""
    from starlette.authentication import AuthCredentials, SimpleUser
    from starlette.requests import Request

    body_bytes = json_mod.dumps(body).encode()

    async def _receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/stage",
        "query_string": b"",
        "headers": [
            (b"x-gateway-project-id", b"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            (b"content-type", b"application/json"),
        ],
        "auth": AuthCredentials(["edit"]),
        "user": SimpleUser("test-user"),
    }
    return Request(scope, receive=_receive)


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestGitStagePathValidation:
    """R11-S-3: git_stage and git_unstage reject unsafe paths before run_git."""

    @pytest.mark.asyncio
    async def test_stage_rejects_absolute_path(self, tmp_path: Path) -> None:
        """POST /stage with an absolute path returns 400; run_git is never called."""
        from signalpilot._server.api.endpoints.git import git_stage

        request = _make_request({"paths": ["/etc/passwd"]})

        with patch("signalpilot._server.api.endpoints.git._get_repo_dir", return_value=tmp_path), \
             patch("signalpilot._server.api.endpoints.git.run_git") as mock_run_git:
            response = await git_stage(request=request)

        assert response.status_code == 400
        body = response.body
        assert b"Absolute path" in body or b"not allowed" in body
        mock_run_git.assert_not_called()

    @pytest.mark.asyncio
    async def test_stage_rejects_parent_traversal(self, tmp_path: Path) -> None:
        """POST /stage with '../../etc/passwd' returns 400; run_git never called."""
        from signalpilot._server.api.endpoints.git import git_stage

        request = _make_request({"paths": ["../../etc/passwd"]})

        with patch("signalpilot._server.api.endpoints.git._get_repo_dir", return_value=tmp_path), \
             patch("signalpilot._server.api.endpoints.git.run_git") as mock_run_git:
            response = await git_stage(request=request)

        assert response.status_code == 400
        assert b"traversal" in response.body
        mock_run_git.assert_not_called()

    @pytest.mark.asyncio
    async def test_stage_rejects_embedded_parent(self, tmp_path: Path) -> None:
        """POST /stage with 'a/../../b' returns 400; run_git never called."""
        from signalpilot._server.api.endpoints.git import git_stage

        request = _make_request({"paths": ["a/../../b"]})

        with patch("signalpilot._server.api.endpoints.git._get_repo_dir", return_value=tmp_path), \
             patch("signalpilot._server.api.endpoints.git.run_git") as mock_run_git:
            response = await git_stage(request=request)

        assert response.status_code == 400
        assert b"traversal" in response.body
        mock_run_git.assert_not_called()

    @pytest.mark.asyncio
    async def test_stage_accepts_normal_path(self, tmp_path: Path) -> None:
        """POST /stage with 'src/foo.py' succeeds; run_git called with correct args."""
        from signalpilot._server.api.endpoints.git import git_stage

        request = _make_request({"paths": ["src/foo.py"]})

        with patch("signalpilot._server.api.endpoints.git._get_repo_dir", return_value=tmp_path), \
             patch("signalpilot._server.api.endpoints.git.run_git", return_value=(0, "", "")) as mock_run_git:
            response = await git_stage(request=request)

        assert response.status_code == 200
        mock_run_git.assert_called_once_with(tmp_path, "add", "--", "src/foo.py")

    @pytest.mark.asyncio
    async def test_unstage_rejects_absolute_path(self, tmp_path: Path) -> None:
        """POST /unstage with an absolute path returns 400; run_git never called."""
        from signalpilot._server.api.endpoints.git import git_unstage

        request = _make_request({"paths": ["/etc/shadow"]})

        with patch("signalpilot._server.api.endpoints.git._get_repo_dir", return_value=tmp_path), \
             patch("signalpilot._server.api.endpoints.git.run_git") as mock_run_git:
            response = await git_unstage(request=request)

        assert response.status_code == 400
        assert b"Absolute path" in response.body or b"not allowed" in response.body
        mock_run_git.assert_not_called()
