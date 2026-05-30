"""F-10: Tests for _cwd_validation.validate_terminal_cwd.

Covers both cloud and local modes per spec S7 mandate:
- Both modes must be covered for every case where mode matters.

/tmp is NOT allowed in either mode (S2) — the round-5 carve-out is removed.
Tests that need a writable scratch dir set PROJECTS_ROOT to a tmp path;
they do NOT extend the allow-list.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _patch_projects_root(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(
        "signalpilot._server.files.project_sync.PROJECTS_ROOT",
        path,
    )


def _set_cloud(monkeypatch) -> None:
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")


def _set_local(monkeypatch) -> None:
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")


# ─── Basic cases ──────────────────────────────────────────────────────────────


class TestNoneReturnsNone:
    def test_none_returns_none(self, monkeypatch, tmp_path):
        _set_local(monkeypatch)
        _patch_projects_root(monkeypatch, tmp_path)

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        assert validate_terminal_cwd(None) is None

    def test_empty_string_returns_none(self, monkeypatch, tmp_path):
        _set_local(monkeypatch)
        _patch_projects_root(monkeypatch, tmp_path)

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        assert validate_terminal_cwd("") is None


# ─── Valid path under PROJECTS_ROOT ──────────────────────────────────────────


class TestValidPathUnderProjectsRoot:
    @pytest.mark.parametrize("mode", ["cloud", "local"])
    def test_valid_path_under_projects_root_returns_resolved(self, monkeypatch, tmp_path, mode):
        """Valid subdirectory under PROJECTS_ROOT is accepted in both modes."""
        if mode == "cloud":
            _set_cloud(monkeypatch)
        else:
            _set_local(monkeypatch)

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        _patch_projects_root(monkeypatch, projects_root)

        valid_dir = projects_root / "my-project" / "workdir"
        valid_dir.mkdir(parents=True)

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        result = validate_terminal_cwd(str(valid_dir))
        assert result == str(valid_dir.resolve())


# ─── Parent traversal rejection ───────────────────────────────────────────────


class TestParentTraversalRaises:
    @pytest.mark.parametrize("mode", ["cloud", "local"])
    def test_parent_traversal_in_raw_input_raises(self, monkeypatch, tmp_path, mode):
        """Path containing '..' raises ValueError in both modes."""
        if mode == "cloud":
            _set_cloud(monkeypatch)
        else:
            _set_local(monkeypatch)

        _patch_projects_root(monkeypatch, tmp_path / "projects")

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        with pytest.raises(ValueError, match="parent traversal"):
            validate_terminal_cwd("~/.sp/projects/foo/../../../etc")

    @pytest.mark.parametrize("mode", ["cloud", "local"])
    def test_double_dot_component_raises(self, monkeypatch, tmp_path, mode):
        """Standalone '..' component in path raises ValueError."""
        if mode == "cloud":
            _set_cloud(monkeypatch)
        else:
            _set_local(monkeypatch)

        _patch_projects_root(monkeypatch, tmp_path / "projects")

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        with pytest.raises(ValueError, match="parent traversal"):
            validate_terminal_cwd("/some/valid/../../../etc/passwd")


# ─── Symlink escape rejection ─────────────────────────────────────────────────


class TestSymlinkEscapeRaises:
    @pytest.mark.parametrize("mode", ["cloud", "local"])
    def test_symlink_escape_raises(self, monkeypatch, tmp_path, mode):
        """Symlink pointing outside the project root raises ValueError."""
        if mode == "cloud":
            _set_cloud(monkeypatch)
        else:
            _set_local(monkeypatch)

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        _patch_projects_root(monkeypatch, projects_root)

        # Create a symlink inside the projects dir that points to /etc (outside)
        escape_link = projects_root / "escape"
        try:
            escape_link.symlink_to("/etc")
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        with pytest.raises(ValueError):
            validate_terminal_cwd(str(escape_link))


# ─── Nonexistent path rejection ───────────────────────────────────────────────


class TestNonexistentPathRaises:
    @pytest.mark.parametrize("mode", ["cloud", "local"])
    def test_nonexistent_path_raises(self, monkeypatch, tmp_path, mode):
        """Path that does not exist raises ValueError."""
        if mode == "cloud":
            _set_cloud(monkeypatch)
        else:
            _set_local(monkeypatch)

        _patch_projects_root(monkeypatch, tmp_path / "projects")

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        with pytest.raises(ValueError, match="invalid cwd"):
            validate_terminal_cwd("/nonexistent/path/that/does/not/exist/xyzzy")


# ─── Cloud mode: home dir rejected ───────────────────────────────────────────


class TestCloudModeRejectsHomeDir:
    def test_cloud_mode_rejects_home_dir(self, monkeypatch, tmp_path):
        """Cloud mode: home directory is not an allowed root."""
        _set_cloud(monkeypatch)

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        _patch_projects_root(monkeypatch, projects_root)

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        home = Path.home()
        if not home.exists():
            pytest.skip("Home directory does not exist")

        with pytest.raises(ValueError, match="outside allowed roots"):
            validate_terminal_cwd(str(home))


# ─── Local mode: home dir allowed ─────────────────────────────────────────────


class TestLocalModeAllowsHomeDir:
    def test_local_mode_allows_home_dir(self, monkeypatch, tmp_path):
        """Local mode: home directory is an allowed root."""
        _set_local(monkeypatch)

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        _patch_projects_root(monkeypatch, projects_root)

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        home = Path.home()
        if not home.exists():
            pytest.skip("Home directory does not exist")

        result = validate_terminal_cwd(str(home))
        assert result == str(home.resolve())


# ─── /tmp is rejected in both modes (S2) ─────────────────────────────────────


class TestTmpRejected:
    def test_cloud_mode_rejects_tmp(self, monkeypatch, tmp_path):
        """Cloud mode: /tmp is not an allowed root."""
        _set_cloud(monkeypatch)

        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        _patch_projects_root(monkeypatch, projects_root)

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        # Create a real path under /tmp to pass the strict=True check
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="outside allowed roots"):
                validate_terminal_cwd(tmpdir)

    def test_local_mode_rejects_tmp(self, monkeypatch, tmp_path):
        """Local mode: /tmp is NOT allowed (S2 — carve-out removed)."""
        _set_local(monkeypatch)

        # Set PROJECTS_ROOT to something that is NOT under /tmp
        projects_root = Path.home() / ".sp" / "projects"
        _patch_projects_root(monkeypatch, projects_root)

        # Also patch home so it doesn't help
        monkeypatch.setattr(
            "signalpilot._server.api.endpoints._cwd_validation.Path.home",
            lambda: Path("/home/testuser_not_tmp"),
        )

        from signalpilot._server.api.endpoints._cwd_validation import validate_terminal_cwd

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # /tmp is not under projects_root or fake home
            with pytest.raises(ValueError, match="outside allowed roots"):
                validate_terminal_cwd(tmpdir)
