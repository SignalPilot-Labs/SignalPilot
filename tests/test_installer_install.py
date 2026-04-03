import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from signalpilot.gateway.gateway.installer import checks, ui
from signalpilot.gateway.gateway.installer.install import (
    _configure_env,
    _find_repo_root,
    run_install,
    run_uninstall,
)


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
        assert (result / ".env.example").exists()

    def test_result_is_absolute(self):
        result = _find_repo_root()
        assert result.is_absolute()

    def test_fallback_returns_path_when_no_env_example(self, tmp_path):
        """When .env.example is nowhere in the tree, fallback uses parents[4]."""
        fake_installer = tmp_path / "a" / "b" / "c" / "d" / "install.py"
        fake_installer.parent.mkdir(parents=True)
        fake_installer.touch()

        import signalpilot.gateway.gateway.installer.install as install_mod
        with patch.object(install_mod, "__file__", str(fake_installer)):
            from signalpilot.gateway.gateway.installer.install import _find_repo_root as frr
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

        _configure_env(tmp_path, non_interactive=True)

    def test_missing_env_example_prints_hint(self, tmp_path, capsys):
        """When .env.example doesn't exist, prints a helpful hint."""
        _configure_env(tmp_path, non_interactive=True)

        env = tmp_path / ".env"
        assert not env.exists(), ".env should NOT be created without .env.example"

        out = capsys.readouterr().out
        assert "create .env manually" in out or "No .env.example" in out


# ---------------------------------------------------------------------------
# Shared fixtures for run_install tests
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

_DOCKER_OK = {
    "installed": True,
    "running": True,
    "version": "27.5.1",
    "compose_installed": True,
    "compose_version": "2.32.0",
}

_DOCKER_MISSING = {
    "installed": False,
    "running": False,
    "version": None,
    "compose_installed": False,
    "compose_version": None,
}

_DOCKER_NOT_RUNNING = {
    "installed": True,
    "running": False,
    "version": "24.0.0",
    "compose_installed": True,
    "compose_version": "2.20.0",
}


def _setup_fake_repo(tmp_path):
    """Create a minimal fake repo structure at tmp_path."""
    # .env.example so _configure_env works
    (tmp_path / ".env.example").write_text("GITHUB_REPO=\nGIT_TOKEN=\n")

    # compose file so _compose_file() returns an existing path
    docker_dir = tmp_path / "signalpilot" / "docker"
    docker_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.dev.yml").write_text("services: {}")
    (docker_dir / "docker-compose.yml").write_text("services: {}")

    return tmp_path


def _mock_successful_compose(*args, capture=False, **kwargs):
    """Return a successful CompletedProcess for any _run_compose call."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = '{"Service":"test","State":"running","Status":"Up 1m"}'
    proc.stderr = ""
    return proc


def _mock_failed_compose(*args, capture=False, **kwargs):
    """Return a failed CompletedProcess for _run_compose."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 1
    proc.stdout = ""
    proc.stderr = "error: build failed"
    return proc


class _BaseInstallTest:
    """Base class with shared mocking helpers for run_install tests."""

    def _apply_happy_path_mocks(self, monkeypatch, tmp_path):
        """Set up all mocks for a successful install run."""
        import signalpilot.gateway.gateway.installer.checks as _checks
        import signalpilot.gateway.gateway.installer.install as _install

        repo_root = _setup_fake_repo(tmp_path)

        # Platform and dependency checks
        monkeypatch.setattr(_checks, "detect_platform", lambda: _FAKE_PLATFORM)
        monkeypatch.setattr(_checks, "check_docker", lambda: _DOCKER_OK)
        monkeypatch.setattr(_checks, "check_command", lambda cmd, **kw: "2.43.0")
        monkeypatch.setattr(_checks, "check_port", lambda port: True)
        monkeypatch.setattr(_checks, "port_owner", lambda port: None)
        monkeypatch.setattr(_checks, "verify_endpoint", lambda url, **kw: (200, 25))
        monkeypatch.setattr(_checks, "verify_postgres", lambda cf, **kw: (True, 10))

        # Repo root resolution
        monkeypatch.setattr(_install, "_find_repo_root", lambda: repo_root)

        # Docker compose operations
        monkeypatch.setattr(_install, "_run_compose", _mock_successful_compose)

        # Avoid real sleeps in health check loops
        monkeypatch.setattr("time.sleep", lambda s: None)

        # Prevent input() from being called
        monkeypatch.setattr(
            "builtins.input",
            lambda *a: (_ for _ in ()).throw(AssertionError("input() should not be called")),
        )

        return repo_root


# ---------------------------------------------------------------------------
# run_install() — non-interactive failure paths
# ---------------------------------------------------------------------------


class TestRunInstallNonInteractive(_BaseInstallTest):
    """run_install(non_interactive=True) must exit with code 1 and never call input()."""

    def test_exits_when_docker_missing(self, monkeypatch, tmp_path):
        """Exits with code 1 when Docker is not installed."""
        import signalpilot.gateway.gateway.installer.checks as _checks

        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        monkeypatch.setattr(_checks, "check_docker", lambda: _DOCKER_MISSING)

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)

        assert exc_info.value.code == 1

    def test_exits_when_docker_not_running(self, monkeypatch, tmp_path):
        """Exits with code 1 when Docker daemon is not running."""
        import signalpilot.gateway.gateway.installer.checks as _checks

        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        monkeypatch.setattr(_checks, "check_docker", lambda: _DOCKER_NOT_RUNNING)

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)

        assert exc_info.value.code == 1

    def test_exits_when_git_not_found(self, monkeypatch, tmp_path):
        """Exits with code 1 when git is not installed."""
        import signalpilot.gateway.gateway.installer.checks as _checks

        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        monkeypatch.setattr(_checks, "check_command", lambda cmd, **kw: None)

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)

        assert exc_info.value.code == 1

    def test_exits_when_port_in_use(self, monkeypatch, tmp_path):
        """Exits with code 1 when a required port is occupied."""
        import signalpilot.gateway.gateway.installer.checks as _checks

        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        # First port check fails, rest succeed
        port_results = iter([False, True, True, True, True])
        monkeypatch.setattr(_checks, "check_port", lambda port: next(port_results))

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)

        assert exc_info.value.code == 1

    def test_exits_when_compose_file_missing(self, monkeypatch, tmp_path):
        """Exits with code 1 when the docker-compose file doesn't exist."""
        import signalpilot.gateway.gateway.installer.install as _install

        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        # Override compose file to a nonexistent path
        monkeypatch.setattr(
            _install, "_compose_file",
            lambda root, dev=False: tmp_path / "nonexistent" / "docker-compose.yml",
        )

        with pytest.raises(SystemExit) as exc_info:
            run_install(dev=True, non_interactive=True)

        assert exc_info.value.code == 1

    def test_exits_when_build_fails(self, monkeypatch, tmp_path):
        """Exits with code 1 when docker compose build fails."""
        import signalpilot.gateway.gateway.installer.install as _install

        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        monkeypatch.setattr(_install, "_run_compose", _mock_failed_compose)

        with pytest.raises(SystemExit) as exc_info:
            # skip_build=False to exercise the build path
            run_install(dev=True, skip_build=False, non_interactive=True)

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# run_install() — verbose mode
# ---------------------------------------------------------------------------


class TestRunInstallVerbose(_BaseInstallTest):
    """run_install(verbose=True) shows additional debug output."""

    def test_verbose_completes(self, monkeypatch, tmp_path, capsys):
        """Verbose mode completes successfully."""
        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        run_install(dev=True, skip_build=True, non_interactive=True, verbose=True)
        out = capsys.readouterr().out
        assert "SignalPilot is running" in out


# ---------------------------------------------------------------------------
# run_install() — version validation
# ---------------------------------------------------------------------------


class TestRunInstallVersionValidation(_BaseInstallTest):
    """run_install fails when dependency versions are too old."""

    _OLD_DOCKER = {
        "installed": True,
        "running": True,
        "version": "20.10.0",
        "compose_installed": True,
        "compose_version": "2.32.0",
    }

    _OLD_COMPOSE = {
        "installed": True,
        "running": True,
        "version": "27.5.1",
        "compose_installed": True,
        "compose_version": "1.29.0",
    }

    def test_exits_when_docker_version_too_old(self, monkeypatch, tmp_path):
        import signalpilot.gateway.gateway.installer.checks as _checks
        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        monkeypatch.setattr(_checks, "check_docker", lambda: self._OLD_DOCKER)

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)
        assert exc_info.value.code == 1

    def test_exits_when_compose_version_too_old(self, monkeypatch, tmp_path):
        import signalpilot.gateway.gateway.installer.checks as _checks
        self._apply_happy_path_mocks(monkeypatch, tmp_path)
        monkeypatch.setattr(_checks, "check_docker", lambda: self._OLD_COMPOSE)

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# run_install() — end-to-end happy path
# ---------------------------------------------------------------------------


class TestRunInstallHappyPath(_BaseInstallTest):
    """Full happy path: run_install completes without SystemExit."""

    def test_completes_without_exit(self, monkeypatch, tmp_path, capsys):
        """Full install flow with skip_build completes successfully."""
        self._apply_happy_path_mocks(monkeypatch, tmp_path)

        # Should NOT raise SystemExit
        run_install(dev=True, skip_build=True, non_interactive=True)

        out = capsys.readouterr().out
        assert "SignalPilot is running" in out

    def test_output_contains_box(self, monkeypatch, tmp_path, capsys):
        """Completion banner renders with box-drawing characters."""
        self._apply_happy_path_mocks(monkeypatch, tmp_path)

        run_install(dev=True, skip_build=True, non_interactive=True)

        out = capsys.readouterr().out
        assert "┌" in out
        assert "┘" in out
        assert "│" in out

    def test_output_contains_service_urls(self, monkeypatch, tmp_path, capsys):
        """Completion banner shows all service endpoints."""
        self._apply_happy_path_mocks(monkeypatch, tmp_path)

        run_install(dev=True, skip_build=True, non_interactive=True)

        out = capsys.readouterr().out
        assert "localhost:3200" in out
        assert "localhost:3300" in out
        assert "localhost:5600" in out

    def test_output_contains_next_steps(self, monkeypatch, tmp_path, capsys):
        """Completion output includes next steps guidance."""
        self._apply_happy_path_mocks(monkeypatch, tmp_path)

        run_install(dev=True, skip_build=True, non_interactive=True)

        out = capsys.readouterr().out
        assert "Next steps" in out
        assert "sp connect" in out

    def test_env_file_created(self, monkeypatch, tmp_path):
        """Non-interactive mode creates .env from .env.example."""
        repo_root = self._apply_happy_path_mocks(monkeypatch, tmp_path)

        run_install(dev=True, skip_build=True, non_interactive=True)

        env_file = repo_root / ".env"
        assert env_file.exists()
        assert env_file.stat().st_mode & 0o777 == 0o600

    def test_all_sections_appear(self, monkeypatch, tmp_path, capsys):
        """Output contains all 6 install sections."""
        self._apply_happy_path_mocks(monkeypatch, tmp_path)

        run_install(dev=True, skip_build=True, non_interactive=True)

        out = capsys.readouterr().out
        for section in ["System", "Dependencies", "Configuration", "Building", "Starting", "Verifying"]:
            assert section in out, f"Missing section: {section}"

    def test_dependency_checks_reported(self, monkeypatch, tmp_path, capsys):
        """Output shows Docker, Compose, and Git check results."""
        self._apply_happy_path_mocks(monkeypatch, tmp_path)

        run_install(dev=True, skip_build=True, non_interactive=True)

        out = capsys.readouterr().out
        assert "Docker Desktop" in out
        assert "Docker Compose" in out
        assert "Git" in out


# ---------------------------------------------------------------------------
# run_uninstall()
# ---------------------------------------------------------------------------


class TestRunUninstall:
    """run_uninstall() tears down containers via docker compose down -v."""

    def test_successful_teardown(self, monkeypatch, tmp_path, capsys):
        """Successful uninstall removes containers and shows confirmation."""
        import signalpilot.gateway.gateway.installer.install as _install

        repo_root = _setup_fake_repo(tmp_path)
        monkeypatch.setattr(_install, "_find_repo_root", lambda: repo_root)
        monkeypatch.setattr(_install, "_run_compose", _mock_successful_compose)

        run_uninstall(dev=True)

        out = capsys.readouterr().out
        assert "removed" in out
        assert "✓" in out
        assert "sp install" in out

    def test_compose_down_failure(self, monkeypatch, tmp_path):
        """Exits with code 1 when docker compose down fails."""
        import signalpilot.gateway.gateway.installer.install as _install

        repo_root = _setup_fake_repo(tmp_path)
        monkeypatch.setattr(_install, "_find_repo_root", lambda: repo_root)
        monkeypatch.setattr(_install, "_run_compose", _mock_failed_compose)

        with pytest.raises(SystemExit) as exc_info:
            run_uninstall(dev=True)

        assert exc_info.value.code == 1
