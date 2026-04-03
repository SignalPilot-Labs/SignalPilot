from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from signalpilot.gateway.gateway.installer import checks, ui
from signalpilot.gateway.gateway.installer.install import _configure_env, _find_repo_root, run_install


# ---------------------------------------------------------------------------
# install._find_repo_root()
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    """_find_repo_root() should return the path containing .env.example."""

    def test_returns_path_object(self):
        result = _find_repo_root()
        assert isinstance(result, Path)

    def test_returned_path_exists(self):
        result = _find_repo_root()
        assert result.exists()

    def test_returned_path_is_directory(self):
        result = _find_repo_root()
        assert result.is_dir()

    def test_env_example_present_at_root(self):
        result = _find_repo_root()
        # The function walks up to find .env.example
        assert (result / ".env.example").exists()

    def test_result_is_absolute(self):
        result = _find_repo_root()
        assert result.is_absolute()

    def test_fallback_returns_path_when_no_env_example(self, tmp_path):
        """When .env.example is nowhere in the tree, fallback uses parents[4]."""
        # Construct a fake installer file deeply nested without a .env.example
        fake_installer = tmp_path / "a" / "b" / "c" / "d" / "install.py"
        fake_installer.parent.mkdir(parents=True)
        fake_installer.touch()

        # Patch __file__ inside the install module so parents[4] == tmp_path
        import signalpilot.gateway.gateway.installer.install as install_mod
        with patch.object(install_mod, "__file__", str(fake_installer)):
            from signalpilot.gateway.gateway.installer.install import _find_repo_root as frr
            # Since the fake tree has no .env.example or signalpilot/ dir,
            # the function should raise FileNotFoundError with a clear message.
            with pytest.raises(FileNotFoundError, match="repo root"):
                frr()


# ---------------------------------------------------------------------------
# install._configure_env() — non-interactive mode
# ---------------------------------------------------------------------------


class TestConfigureEnvNonInteractive:
    """_configure_env() with non_interactive=True must never call input()."""

    def test_copies_env_example(self, tmp_path):
        """Copies .env.example to .env and chmods to 600 when .env is absent."""
        example = tmp_path / ".env.example"
        example.write_text("KEY=value\n")

        _configure_env(tmp_path, non_interactive=True)

        env = tmp_path / ".env"
        assert env.exists(), ".env should have been created"
        assert env.read_text() == "KEY=value\n", ".env content should match .env.example"
        mode = oct(env.stat().st_mode & 0o777)
        assert env.stat().st_mode & 0o777 == 0o600, f"Expected 0o600, got {mode}"

    def test_skips_when_env_exists(self, tmp_path, capsys):
        """Returns early and prints 'already exists' when .env is already present."""
        env = tmp_path / ".env"
        env.write_text("EXISTING=1\n")
        example = tmp_path / ".env.example"
        example.write_text("KEY=value\n")

        _configure_env(tmp_path, non_interactive=True)

        out = capsys.readouterr().out
        assert "already exists" in out

    def test_no_input_called(self, tmp_path, monkeypatch):
        """Does not call input() in non-interactive mode."""
        example = tmp_path / ".env.example"
        example.write_text("KEY=value\n")

        monkeypatch.setattr(
            "builtins.input",
            lambda *a: (_ for _ in ()).throw(AssertionError("input() should not be called")),
        )

        # Should complete without raising AssertionError
        _configure_env(tmp_path, non_interactive=True)


# ---------------------------------------------------------------------------
# install.run_install() — non-interactive mode
# ---------------------------------------------------------------------------

_FAKE_PLATFORM = {
    "os": "Linux",
    "os_pretty": "Linux (x86_64)",
    "arch": "x86_64",
    "shell": "bash",
    "user": "test",
    "docker_url": "https://example.com",
    "open_cmd": "echo",
    "is_wsl": False,
}


class TestRunInstallNonInteractive:
    """run_install(non_interactive=True) must exit with code 1 and never call input()."""

    def _mock_ui(self, monkeypatch):
        """Silence all ui output functions."""
        import signalpilot.gateway.gateway.installer.ui as _ui
        for fn in ("header", "section", "kv", "fail", "hint", "check", "dot", "error_block"):
            if hasattr(_ui, fn):
                monkeypatch.setattr(_ui, fn, lambda *a, **kw: None)
        monkeypatch.setattr(_ui, "bold_text", lambda s: s)
        monkeypatch.setattr(_ui, "dim_text", lambda s: s)

    def test_exits_when_docker_missing(self, monkeypatch):
        """Exits with code 1 and never calls input() when Docker is not installed."""
        import signalpilot.gateway.gateway.installer.checks as _checks

        self._mock_ui(monkeypatch)
        monkeypatch.setattr(_checks, "detect_platform", lambda: _FAKE_PLATFORM)
        monkeypatch.setattr(_checks, "check_docker", lambda: {
            "installed": False,
            "running": False,
            "version": None,
            "compose_installed": False,
            "compose_version": None,
        })
        monkeypatch.setattr(
            "builtins.input",
            lambda *a: (_ for _ in ()).throw(AssertionError("input() should not be called")),
        )

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)

        assert exc_info.value.code == 1

    def test_exits_when_docker_not_running(self, monkeypatch):
        """Exits with code 1 and never calls input() when Docker daemon is not running."""
        import signalpilot.gateway.gateway.installer.checks as _checks

        self._mock_ui(monkeypatch)
        monkeypatch.setattr(_checks, "detect_platform", lambda: _FAKE_PLATFORM)
        monkeypatch.setattr(_checks, "check_docker", lambda: {
            "installed": True,
            "running": False,
            "version": "24.0.0",
            "compose_installed": True,
            "compose_version": "2.20.0",
        })
        monkeypatch.setattr(
            "builtins.input",
            lambda *a: (_ for _ in ()).throw(AssertionError("input() should not be called")),
        )

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)

        assert exc_info.value.code == 1
