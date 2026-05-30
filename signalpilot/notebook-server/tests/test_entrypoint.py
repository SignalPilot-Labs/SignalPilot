"""Unit tests for signalpilot._server.entrypoint."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestLoadAndDestroyJwt:
    def test_load_and_destroy_unlinks_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """File present → env-var set, file removed."""
        jwt_file = tmp_path / "session_jwt"
        jwt_file.write_text("test-token\n")

        import signalpilot._server.entrypoint as ep
        monkeypatch.setattr(ep, "_JWT_PATH", str(jwt_file))
        monkeypatch.delenv("SP_SESSION_JWT", raising=False)

        ep._load_and_destroy_jwt()

        assert os.environ.get("SP_SESSION_JWT") == "test-token"
        assert not jwt_file.exists()

        monkeypatch.delenv("SP_SESSION_JWT", raising=False)

    def test_no_jwt_file_is_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """FileNotFoundError → returns cleanly, env unchanged."""
        missing = str(tmp_path / "nonexistent")

        import signalpilot._server.entrypoint as ep
        monkeypatch.setattr(ep, "_JWT_PATH", missing)
        monkeypatch.delenv("SP_SESSION_JWT", raising=False)

        ep._load_and_destroy_jwt()

        assert "SP_SESSION_JWT" not in os.environ

    def test_unlink_eperm_propagates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """PermissionError on unlink must NOT be silenced — fail-fast contract."""
        jwt_file = tmp_path / "session_jwt"
        jwt_file.write_text("tok")

        import signalpilot._server.entrypoint as ep
        monkeypatch.setattr(ep, "_JWT_PATH", str(jwt_file))
        monkeypatch.delenv("SP_SESSION_JWT", raising=False)

        with patch("os.unlink", side_effect=PermissionError("EROFS")):
            with pytest.raises(PermissionError):
                ep._load_and_destroy_jwt()

        monkeypatch.delenv("SP_SESSION_JWT", raising=False)

    def test_main_invokes_execvp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """main() calls os.execvp with ('sp', ['sp', 'edit', ...])."""
        import sys

        import signalpilot._server.entrypoint as ep
        monkeypatch.setattr(ep, "_JWT_PATH", str(tmp_path / "missing"))
        monkeypatch.delenv("SP_SESSION_JWT", raising=False)
        monkeypatch.setattr(sys, "argv", ["entrypoint.py", "--port", "2718"])

        execvp_calls: list[tuple] = []

        def fake_execvp(file: str, args: list) -> None:
            execvp_calls.append((file, args))

        with patch("os.execvp", side_effect=fake_execvp):
            ep.main()

        assert len(execvp_calls) == 1
        file, args = execvp_calls[0]
        assert file == "sp"
        assert args[0] == "sp"
        assert args[1] == "edit"
        assert "--port" in args
        assert "2718" in args
