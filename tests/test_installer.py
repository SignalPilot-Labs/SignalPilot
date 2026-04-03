"""
Tests for the SignalPilot CLI installer module.

Covers:
- checks.detect_platform()  — dict shape and key presence
- checks.check_command()    — found / not-found via mocked subprocess
- checks.check_docker()     — installed+running, installed+not-running, not-installed
- checks.check_port()       — available and in-use ports
- ui.header()               — prints without error
- ui.section()              — output format
- ui.check()                — output format with label and detail
- ui.Spinner                — start/stop lifecycle
- install._find_repo_root() — locates the repo root
"""

import socket
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from signalpilot.gateway.gateway.installer import checks, ui
from signalpilot.gateway.gateway.installer.install import _configure_env, _find_repo_root, run_install


# ---------------------------------------------------------------------------
# checks.detect_platform()
# ---------------------------------------------------------------------------

class TestDetectPlatform:
    """detect_platform() must always return a dict with every expected key."""

    EXPECTED_KEYS = {"os", "os_pretty", "arch", "shell", "user", "docker_url", "open_cmd", "is_wsl"}

    def test_returns_dict(self):
        result = checks.detect_platform()
        assert isinstance(result, dict)

    def test_all_expected_keys_present(self):
        result = checks.detect_platform()
        assert self.EXPECTED_KEYS == set(result.keys())

    def test_os_is_non_empty_string(self):
        result = checks.detect_platform()
        assert isinstance(result["os"], str)
        assert result["os"]

    def test_os_pretty_is_non_empty_string(self):
        result = checks.detect_platform()
        assert isinstance(result["os_pretty"], str)
        assert result["os_pretty"]

    def test_arch_normalised(self):
        result = checks.detect_platform()
        # Must be one of the normalised forms or a raw value
        assert isinstance(result["arch"], str)
        assert result["arch"]

    def test_shell_is_string(self):
        result = checks.detect_platform()
        assert isinstance(result["shell"], str)

    def test_user_is_string(self):
        result = checks.detect_platform()
        assert isinstance(result["user"], str)

    def test_docker_url_is_https_url(self):
        result = checks.detect_platform()
        assert result["docker_url"].startswith("https://")

    def test_open_cmd_is_string(self):
        result = checks.detect_platform()
        assert isinstance(result["open_cmd"], str)
        assert result["open_cmd"]

    def test_is_wsl_is_bool(self):
        result = checks.detect_platform()
        assert isinstance(result["is_wsl"], bool)

    def test_wsl_detected_when_proc_version_contains_microsoft(self):
        proc_version_content = "Linux version 5.15 (Microsoft WSL2)"
        mock_open = MagicMock()
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value=proc_version_content)

        with patch("platform.system", return_value="Linux"), \
             patch("builtins.open", mock_open):
            result = checks.detect_platform()

        assert result["is_wsl"] is True
        assert result["os"] == "WSL2"
        assert result["open_cmd"] == "explorer.exe"

    def test_non_wsl_linux_open_cmd(self):
        with patch("platform.system", return_value="Linux"), \
             patch("builtins.open", side_effect=OSError):
            result = checks.detect_platform()

        assert result["is_wsl"] is False
        assert result["os"] == "Linux"
        assert result["open_cmd"] == "xdg-open"

    def test_macos_platform(self):
        with patch("platform.system", return_value="Darwin"), \
             patch("platform.mac_ver", return_value=("14.2", ("", "", ""), "")), \
             patch("platform.machine", return_value="arm64"):
            result = checks.detect_platform()

        assert result["os"] == "macOS"
        assert result["open_cmd"] == "open"
        assert "docker.com" in result["docker_url"]

    def test_arch_x86_64_normalised(self):
        with patch("platform.machine", return_value="AMD64"):
            result = checks.detect_platform()
        assert result["arch"] == "x86_64"

    def test_arch_arm64_normalised(self):
        with patch("platform.machine", return_value="aarch64"):
            result = checks.detect_platform()
        assert result["arch"] == "arm64"


# ---------------------------------------------------------------------------
# checks.check_command()
# ---------------------------------------------------------------------------

class TestCheckCommand:
    """check_command() returns a version string when found, None when absent."""

    def test_returns_none_when_command_not_on_path(self):
        with patch("shutil.which", return_value=None):
            result = checks.check_command("nonexistent-tool")
        assert result is None

    def test_returns_version_string_when_found(self):
        mock_proc = MagicMock()
        mock_proc.stdout = "git version 2.40.1\n"
        mock_proc.stderr = ""

        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", return_value=mock_proc):
            result = checks.check_command("git")

        assert result == "2.40.1"

    def test_returns_version_from_stderr_when_stdout_empty(self):
        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.stderr = "tool 1.2.3\n"

        with patch("shutil.which", return_value="/usr/bin/tool"), \
             patch("subprocess.run", return_value=mock_proc):
            result = checks.check_command("tool")

        assert result == "1.2.3"

    def test_returns_installed_when_no_version_in_output(self):
        mock_proc = MagicMock()
        mock_proc.stdout = "some output without a version\n"
        mock_proc.stderr = ""

        with patch("shutil.which", return_value="/usr/bin/tool"), \
             patch("subprocess.run", return_value=mock_proc):
            result = checks.check_command("tool")

        assert result == "installed"

    def test_returns_installed_on_timeout(self):
        import subprocess
        with patch("shutil.which", return_value="/usr/bin/tool"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tool", timeout=10)):
            result = checks.check_command("tool")

        assert result == "installed"

    def test_returns_installed_on_os_error(self):
        with patch("shutil.which", return_value="/usr/bin/tool"), \
             patch("subprocess.run", side_effect=OSError("exec failed")):
            result = checks.check_command("tool")

        assert result == "installed"

    def test_uses_custom_version_flag(self):
        mock_proc = MagicMock()
        mock_proc.stdout = "v3.0.0\n"
        mock_proc.stderr = ""

        with patch("shutil.which", return_value="/usr/bin/tool"), \
             patch("subprocess.run", return_value=mock_proc) as mock_run:
            checks.check_command("tool", version_flag="-V")

        call_args = mock_run.call_args
        assert "-V" in call_args[0][0]


# ---------------------------------------------------------------------------
# checks.check_docker()
# ---------------------------------------------------------------------------

class TestCheckDocker:
    """check_docker() returns the correct shape under all scenarios."""

    RESULT_KEYS = {"installed", "running", "version", "compose_installed", "compose_version"}

    def _make_proc(self, returncode=0, stdout="", stderr=""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_returns_all_false_when_docker_not_installed(self):
        with patch("signalpilot.gateway.gateway.installer.checks.check_command", return_value=None):
            result = checks.check_docker()

        assert result["installed"] is False
        assert result["running"] is False
        assert result["version"] is None
        assert result["compose_installed"] is False
        assert result["compose_version"] is None

    def test_result_has_all_expected_keys(self):
        with patch("signalpilot.gateway.gateway.installer.checks.check_command", return_value=None):
            result = checks.check_docker()
        assert self.RESULT_KEYS == set(result.keys())

    def test_docker_installed_and_running_with_compose(self):
        info_proc = self._make_proc(returncode=0)
        compose_proc = self._make_proc(returncode=0, stdout="Docker Compose version v2.24.0")

        with patch("signalpilot.gateway.gateway.installer.checks.check_command", return_value="24.0.5"), \
             patch("subprocess.run", side_effect=[info_proc, compose_proc]):
            result = checks.check_docker()

        assert result["installed"] is True
        assert result["running"] is True
        assert result["version"] == "24.0.5"
        assert result["compose_installed"] is True
        assert result["compose_version"] == "2.24.0"

    def test_docker_installed_but_daemon_not_running(self):
        info_proc = self._make_proc(returncode=1)
        compose_proc = self._make_proc(returncode=0, stdout="Docker Compose version v2.24.0")

        with patch("signalpilot.gateway.gateway.installer.checks.check_command", return_value="24.0.5"), \
             patch("subprocess.run", side_effect=[info_proc, compose_proc]):
            result = checks.check_docker()

        assert result["installed"] is True
        assert result["running"] is False
        assert result["compose_installed"] is True

    def test_docker_installed_compose_not_available(self):
        info_proc = self._make_proc(returncode=0)
        compose_proc = self._make_proc(returncode=1, stdout="")

        with patch("signalpilot.gateway.gateway.installer.checks.check_command", return_value="24.0.5"), \
             patch("subprocess.run", side_effect=[info_proc, compose_proc]):
            result = checks.check_docker()

        assert result["installed"] is True
        assert result["running"] is True
        assert result["compose_installed"] is False
        assert result["compose_version"] is None

    def test_docker_info_timeout_leaves_running_false(self):
        import subprocess as _subprocess
        compose_proc = self._make_proc(returncode=0, stdout="Docker Compose version v2.0.0")

        with patch("signalpilot.gateway.gateway.installer.checks.check_command", return_value="24.0.5"), \
             patch("subprocess.run", side_effect=[
                 _subprocess.TimeoutExpired(cmd="docker", timeout=10),
                 compose_proc,
             ]):
            result = checks.check_docker()

        assert result["installed"] is True
        assert result["running"] is False

    def test_compose_version_installed_fallback_when_no_version_string(self):
        info_proc = self._make_proc(returncode=0)
        compose_proc = self._make_proc(returncode=0, stdout="Docker Compose")

        with patch("signalpilot.gateway.gateway.installer.checks.check_command", return_value="24.0.5"), \
             patch("subprocess.run", side_effect=[info_proc, compose_proc]):
            result = checks.check_docker()

        assert result["compose_installed"] is True
        assert result["compose_version"] == "installed"


# ---------------------------------------------------------------------------
# checks.check_port()
# ---------------------------------------------------------------------------

class TestCheckPort:
    """check_port() returns True for a free port and False for a bound one."""

    def test_available_port_returns_true(self):
        # Let the OS pick a free ephemeral port, then confirm it reports available
        # after we release it.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        # Port is now released — check_port should find it free
        assert checks.check_port(free_port) is True

    def test_in_use_port_returns_false(self):
        # Bind a socket ourselves to occupy a port, then verify check_port sees it.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupier:
            occupier.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            occupier.bind(("127.0.0.1", 0))
            occupied_port = occupier.getsockname()[1]
            assert checks.check_port(occupied_port) is False

    def test_returns_bool(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        result = checks.check_port(port)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# ui.header()
# ---------------------------------------------------------------------------

class TestUiHeader:
    """header() should print a multi-line branded box to stdout."""

    def test_prints_without_error(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        assert captured.out  # something was printed

    def test_output_contains_signalpilot_name(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        # The header renders the name spaced out: "s i g n a l p i l o t"
        assert "s i g n a l p i l o t" in captured.out.lower()

    def test_output_contains_box_characters(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        # The box uses Unicode box-drawing characters
        assert "┌" in captured.out or "─" in captured.out

    def test_output_contains_version(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        assert "v0.1.0" in captured.out

    def test_no_stderr_output(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# ui.section()
# ---------------------------------------------------------------------------

class TestUiSection:
    """section() should print the title with surrounding whitespace."""

    def test_title_appears_in_output(self, capsys):
        ui.section("Dependencies")
        captured = capsys.readouterr()
        assert "Dependencies" in captured.out

    def test_output_has_leading_whitespace(self, capsys):
        ui.section("System")
        captured = capsys.readouterr()
        # The format is "\n  {BOLD}title{RESET}\n"
        assert "  " in captured.out

    def test_no_stderr(self, capsys):
        ui.section("Anything")
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_different_titles_appear_correctly(self, capsys):
        for title in ("Building", "Starting services", "Configuration"):
            ui.section(title)
            captured = capsys.readouterr()
            assert title in captured.out


# ---------------------------------------------------------------------------
# ui.check()
# ---------------------------------------------------------------------------

class TestUiCheck:
    """check() should print the label and optional detail on one line."""

    def test_label_appears_in_output(self, capsys):
        ui.check("Docker Desktop")
        captured = capsys.readouterr()
        assert "Docker Desktop" in captured.out

    def test_detail_appears_when_provided(self, capsys):
        ui.check("Docker Desktop", "v24.0.5")
        captured = capsys.readouterr()
        assert "v24.0.5" in captured.out

    def test_no_detail_still_prints_label(self, capsys):
        ui.check("Git")
        captured = capsys.readouterr()
        assert "Git" in captured.out

    def test_check_mark_present(self, capsys):
        ui.check("Port 3200")
        captured = capsys.readouterr()
        assert "✓" in captured.out

    def test_no_stderr(self, capsys):
        ui.check("Something", "detail")
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_label_and_detail_on_same_line(self, capsys):
        ui.check("Port 3200", "available")
        captured = capsys.readouterr()
        lines = [l for l in captured.out.splitlines() if "Port 3200" in l]
        assert len(lines) == 1
        assert "available" in lines[0]


# ---------------------------------------------------------------------------
# ui.Spinner
# ---------------------------------------------------------------------------

class TestUiSpinner:
    """Spinner.start() / stop() lifecycle must be safe and non-blocking."""

    def test_start_returns_self(self):
        spinner = ui.Spinner("loading")
        returned = spinner.start()
        spinner.stop(clear=False)
        assert returned is spinner

    def test_stop_after_start_does_not_raise(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        spinner.stop(clear=False)  # must not raise

    def test_thread_is_alive_after_start(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        assert spinner._thread is not None
        assert spinner._thread.is_alive()
        spinner.stop(clear=False)

    def test_thread_is_stopped_after_stop(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        spinner.stop(clear=False)
        # Give the thread a moment to finish (stop() joins with timeout=1)
        spinner._thread.join(timeout=2)
        assert not spinner._thread.is_alive()

    def test_stop_without_start_does_not_raise(self):
        spinner = ui.Spinner("loading")
        spinner.stop(clear=False)  # no thread started — must not raise

    def test_stop_sets_stop_event(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        spinner.stop(clear=False)
        assert spinner._stop.is_set()

    def test_multiple_start_stop_cycles(self):
        spinner = ui.Spinner("loading")
        for _ in range(3):
            spinner.start()
            spinner.stop(clear=False)

    def test_default_message_stored(self):
        spinner = ui.Spinner("testing spinner")
        assert spinner._message == "testing spinner"

    def test_empty_message_is_valid(self):
        spinner = ui.Spinner()
        spinner.start()
        spinner.stop(clear=False)


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
# ui.Timer
# ---------------------------------------------------------------------------


class TestUiTimer:
    def test_start_returns_self(self):
        t = ui.Timer()
        assert t.start() is t

    def test_elapsed_ms_is_non_negative(self):
        t = ui.Timer().start()
        assert t.elapsed_ms() >= 0

    def test_elapsed_ms_increases_over_time(self):
        import time
        t = ui.Timer().start()
        time.sleep(0.05)
        assert t.elapsed_ms() >= 30  # allow some slack

    def test_elapsed_display_ms_format(self):
        t = ui.Timer().start()
        # Immediate — should be under 1000ms
        display = t.elapsed_display()
        assert display.endswith("ms")

    def test_elapsed_display_seconds_format(self):
        t = ui.Timer()
        t._start = 0  # fake a very old start time
        import time
        # Patch perf_counter to return a large value
        with patch("time.perf_counter", return_value=2.5):
            display = t.elapsed_display()
        assert display == "2.5s"


# ---------------------------------------------------------------------------
# ui.section() with step counters
# ---------------------------------------------------------------------------


class TestUiSectionSteps:
    def test_step_counter_appears(self, capsys):
        ui.section("Building", step=3, total=6)
        out = capsys.readouterr().out
        assert "[3/6]" in out
        assert "Building" in out

    def test_no_step_counter_when_none(self, capsys):
        ui.section("System")
        out = capsys.readouterr().out
        assert "System" in out
        assert "[" not in out

    def test_step_counter_zero_values(self, capsys):
        ui.section("Config", step=0, total=0)
        out = capsys.readouterr().out
        assert "[0/0]" in out


# ---------------------------------------------------------------------------
# checks.verify_endpoint()
# ---------------------------------------------------------------------------


class TestVerifyEndpoint:
    def test_returns_tuple(self):
        result = checks.verify_endpoint("http://127.0.0.1:19999")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_unreachable_returns_none_status(self):
        status, ms = checks.verify_endpoint("http://127.0.0.1:19999", timeout=1)
        assert status is None
        assert isinstance(ms, int)

    def test_elapsed_is_non_negative(self):
        _, ms = checks.verify_endpoint("http://127.0.0.1:19999", timeout=1)
        assert ms >= 0


# ---------------------------------------------------------------------------
# checks.verify_postgres()
# ---------------------------------------------------------------------------


class TestVerifyPostgres:
    def test_returns_tuple(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, ms = checks.verify_postgres("/fake/compose.yml")
        assert isinstance(ok, bool)
        assert isinstance(ms, int)

    def test_success_when_returncode_zero(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, _ = checks.verify_postgres("/fake/compose.yml")
        assert ok is True

    def test_failure_when_returncode_nonzero(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            ok, _ = checks.verify_postgres("/fake/compose.yml")
        assert ok is False

    def test_failure_on_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=5)):
            ok, _ = checks.verify_postgres("/fake/compose.yml")
        assert ok is False


# ---------------------------------------------------------------------------
# doctor._DiagResult
# ---------------------------------------------------------------------------

from signalpilot.gateway.gateway.installer.doctor import _DiagResult


class TestDiagResult:
    def test_initial_counts_are_zero(self):
        d = _DiagResult()
        assert d.passed == 0
        assert d.failed == 0
        assert d.total == 0
        assert d.issues == []

    def test_ok_increments_passed(self, capsys):
        d = _DiagResult()
        d.ok("test", "detail")
        assert d.passed == 1
        assert d.failed == 0
        out = capsys.readouterr().out
        assert "test" in out

    def test_fail_increments_failed_and_records_issue(self, capsys):
        d = _DiagResult()
        d.fail("Docker", "not installed", "install Docker")
        assert d.failed == 1
        assert d.passed == 0
        assert len(d.issues) == 1
        assert "Docker" in d.issues[0]
        assert "install Docker" in d.issues[0]

    def test_total_sums_pass_and_fail(self, capsys):
        d = _DiagResult()
        d.ok("a", "")
        d.ok("b", "")
        d.fail("c", "bad")
        assert d.total == 3
        assert d.passed == 2
        assert d.failed == 1

    def test_fail_without_fix_hint(self, capsys):
        d = _DiagResult()
        d.fail("Port 3300", "in use")
        assert "Port 3300: in use" in d.issues[0]
        # No " — " suffix when fix is empty
        assert "—" not in d.issues[0]


# ---------------------------------------------------------------------------
# doctor._check_system
# ---------------------------------------------------------------------------

from signalpilot.gateway.gateway.installer.doctor import _check_system


class TestCheckSystem:
    def test_passes_when_all_present(self, capsys):
        d = _DiagResult()
        with patch.object(checks, "detect_platform", return_value={
            "os_pretty": "Linux (x86_64)", "os": "Linux", "arch": "x86_64",
            "shell": "bash", "user": "test", "docker_url": "", "open_cmd": "", "is_wsl": False,
        }), patch.object(checks, "check_docker", return_value={
            "installed": True, "running": True, "version": "27.5.1",
            "compose_installed": True, "compose_version": "2.32.0",
        }), patch.object(checks, "check_command", return_value="2.43.0"):
            _check_system(d, 1, 5)
        # Docker + daemon + compose + git = 4 passes
        assert d.passed == 4
        assert d.failed == 0

    def test_fails_when_docker_missing(self, capsys):
        d = _DiagResult()
        with patch.object(checks, "detect_platform", return_value={
            "os_pretty": "Linux", "os": "Linux", "arch": "x86_64",
            "shell": "bash", "user": "test", "docker_url": "https://docker.com", "open_cmd": "", "is_wsl": False,
        }), patch.object(checks, "check_docker", return_value={
            "installed": False, "running": False, "version": None,
            "compose_installed": False, "compose_version": None,
        }), patch.object(checks, "check_command", return_value="2.43.0"):
            _check_system(d, 1, 5)
        assert d.failed >= 1
        assert any("Docker" in i for i in d.issues)


# ---------------------------------------------------------------------------
# doctor._check_configuration
# ---------------------------------------------------------------------------

from signalpilot.gateway.gateway.installer.doctor import _check_configuration


class TestCheckConfiguration:
    def test_fails_when_env_missing(self, capsys, tmp_path):
        d = _DiagResult()
        _check_configuration(d, tmp_path, 2, 5)
        assert d.failed == 1
        assert any(".env" in i for i in d.issues)

    def test_passes_with_valid_env(self, capsys, tmp_path):
        env = tmp_path / ".env"
        env.write_text("GITHUB_REPO=Org/Repo\nGIT_TOKEN=ghp_realtoken1234\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-real1234\n")
        env.chmod(0o600)
        d = _DiagResult()
        _check_configuration(d, tmp_path, 2, 5)
        assert d.failed == 0
        assert d.passed >= 4  # .env + 3 keys

    def test_fails_on_placeholder_values(self, capsys, tmp_path):
        env = tmp_path / ".env"
        env.write_text("GITHUB_REPO=Org/Repo\nGIT_TOKEN=ghp_...\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...\n")
        env.chmod(0o600)
        d = _DiagResult()
        _check_configuration(d, tmp_path, 2, 5)
        assert d.failed == 2  # two placeholder keys

    def test_warns_on_world_readable_permissions(self, capsys, tmp_path):
        env = tmp_path / ".env"
        env.write_text("GITHUB_REPO=Org/Repo\nGIT_TOKEN=real\nCLAUDE_CODE_OAUTH_TOKEN=real\n")
        env.chmod(0o644)
        d = _DiagResult()
        _check_configuration(d, tmp_path, 2, 5)
        assert any("world-readable" in i or "644" in i for i in d.issues)


# ---------------------------------------------------------------------------
# doctor._check_endpoints
# ---------------------------------------------------------------------------

from signalpilot.gateway.gateway.installer.doctor import _check_endpoints


class TestCheckEndpoints:
    def test_passes_on_200(self, capsys):
        d = _DiagResult()
        with patch.object(checks, "verify_endpoint", return_value=(200, 25)):
            _check_endpoints(d, 4, 5)
        assert d.passed == 2
        assert d.failed == 0

    def test_fails_on_unreachable(self, capsys):
        d = _DiagResult()
        with patch.object(checks, "verify_endpoint", return_value=(None, 0)):
            _check_endpoints(d, 4, 5)
        assert d.failed == 2

    def test_fails_on_502(self, capsys):
        d = _DiagResult()
        with patch.object(checks, "verify_endpoint", return_value=(502, 15)):
            _check_endpoints(d, 4, 5)
        assert d.failed == 2
        assert any("502" in i for i in d.issues)


# ---------------------------------------------------------------------------
# doctor.run_doctor (integration)
# ---------------------------------------------------------------------------

from signalpilot.gateway.gateway.installer.doctor import run_doctor


class TestRunDoctor:
    def test_runs_without_error(self, capsys, tmp_path):
        """Smoke test: run_doctor completes without raising."""
        env = tmp_path / ".env"
        env.write_text("GITHUB_REPO=Org/Repo\nGIT_TOKEN=realtoken\nCLAUDE_CODE_OAUTH_TOKEN=realtoken\n")
        env.chmod(0o600)
        compose = tmp_path / "signalpilot" / "docker"
        compose.mkdir(parents=True)
        (compose / "docker-compose.yml").write_text("services: {}")

        with patch("signalpilot.gateway.gateway.installer.doctor._find_repo_root", return_value=tmp_path), \
             patch("signalpilot.gateway.gateway.installer.doctor._compose_file", return_value=compose / "docker-compose.yml"), \
             patch.object(checks, "check_docker", return_value={
                 "installed": True, "running": True, "version": "27.5.1",
                 "compose_installed": True, "compose_version": "2.32.0",
             }), \
             patch.object(checks, "check_command", return_value="2.43.0"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="")), \
             patch.object(checks, "verify_endpoint", return_value=(200, 20)):
            run_doctor(dev=False)

        out = capsys.readouterr().out
        assert "System" in out
        assert "Configuration" in out

    def test_summary_shows_all_passed(self, capsys, tmp_path):
        """When everything passes, summary says 'All checks passed'."""
        env = tmp_path / ".env"
        env.write_text("GITHUB_REPO=Org/Repo\nGIT_TOKEN=realtoken\nCLAUDE_CODE_OAUTH_TOKEN=realtoken\n")
        env.chmod(0o600)

        with patch("signalpilot.gateway.gateway.installer.doctor._find_repo_root", return_value=tmp_path), \
             patch("signalpilot.gateway.gateway.installer.doctor._compose_file",
                   return_value=tmp_path / "docker-compose.yml"), \
             patch.object(checks, "detect_platform", return_value={
                 "os_pretty": "Linux", "os": "Linux", "arch": "x86_64",
                 "shell": "bash", "user": "test", "docker_url": "", "open_cmd": "", "is_wsl": False,
             }), \
             patch.object(checks, "check_docker", return_value={
                 "installed": True, "running": True, "version": "27.5.1",
                 "compose_installed": True, "compose_version": "2.32.0",
             }), \
             patch.object(checks, "check_command", return_value="2.43.0"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout='{"Service":"gateway","State":"running","Status":"Up 2h"}\n{"Service":"web","State":"running","Status":"Up 2h"}\n{"Service":"postgres","State":"running","Status":"Up 2h"}\n')), \
             patch.object(checks, "verify_endpoint", return_value=(200, 20)):
            run_doctor(dev=False)

        out = capsys.readouterr().out
        assert "All checks passed" in out

    def test_summary_shows_issues_on_failure(self, capsys, tmp_path):
        """When checks fail, summary lists issues."""
        # No .env file → at least one failure
        with patch("signalpilot.gateway.gateway.installer.doctor._find_repo_root", return_value=tmp_path), \
             patch("signalpilot.gateway.gateway.installer.doctor._compose_file",
                   return_value=tmp_path / "docker-compose.yml"), \
             patch.object(checks, "detect_platform", return_value={
                 "os_pretty": "Linux", "os": "Linux", "arch": "x86_64",
                 "shell": "bash", "user": "test", "docker_url": "", "open_cmd": "", "is_wsl": False,
             }), \
             patch.object(checks, "check_docker", return_value={
                 "installed": True, "running": True, "version": "27.5.1",
                 "compose_installed": True, "compose_version": "2.32.0",
             }), \
             patch.object(checks, "check_command", return_value="2.43.0"), \
             patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")), \
             patch.object(checks, "verify_endpoint", return_value=(None, 0)):
            run_doctor(dev=False)

        out = capsys.readouterr().out
        assert "issue" in out
        assert "⚠" in out


# ---------------------------------------------------------------------------
# config._deep_merge()
# ---------------------------------------------------------------------------

from signalpilot.gateway.gateway.installer import config as installer_config


class TestDeepMerge:
    """_deep_merge() performs a recursive merge without mutating inputs."""

    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = installer_config._deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"gateway": {"host": "0.0.0.0", "port": 3300}}
        override = {"gateway": {"port": 4400}}
        result = installer_config._deep_merge(base, override)
        assert result["gateway"]["port"] == 4400
        assert result["gateway"]["host"] == "0.0.0.0"

    def test_override_with_new_section(self):
        base = {"gateway": {"port": 3300}}
        override = {"newkey": {"nested": True}}
        result = installer_config._deep_merge(base, override)
        assert "gateway" in result
        assert result["newkey"] == {"nested": True}

    def test_no_mutation(self):
        base = {"gateway": {"port": 3300}}
        override = {"gateway": {"port": 4400}}
        import copy
        base_copy = copy.deepcopy(base)
        override_copy = copy.deepcopy(override)
        installer_config._deep_merge(base, override)
        assert base == base_copy
        assert override == override_copy


# ---------------------------------------------------------------------------
# config._load_yaml()
# ---------------------------------------------------------------------------


class TestLoadYaml:
    """_load_yaml() returns file contents or {} on any failure."""

    def test_valid_file(self, tmp_path):
        yaml_file = tmp_path / "config.yml"
        yaml_file.write_text("gateway:\n  port: 4400\n")
        result = installer_config._load_yaml(yaml_file)
        assert result == {"gateway": {"port": 4400}}

    def test_missing_file(self, tmp_path):
        result = installer_config._load_yaml(tmp_path / "nonexistent.yml")
        assert result == {}

    def test_invalid_yaml(self, tmp_path):
        bad_file = tmp_path / "bad.yml"
        bad_file.write_text("key: [\nnot closed")
        result = installer_config._load_yaml(bad_file)
        assert result == {}


# ---------------------------------------------------------------------------
# config._apply_env()
# ---------------------------------------------------------------------------


class TestApplyEnv:
    """_apply_env() reads SP_* env vars into config, respecting known keys."""

    def test_known_key_override(self, monkeypatch):
        monkeypatch.setenv("SP_GATEWAY_PORT", "9999")
        cfg = {"gateway": {"port": 3300, "host": "0.0.0.0"}}
        result = installer_config._apply_env(cfg)
        assert result["gateway"]["port"] == 9999

    def test_unknown_section_ignored(self, monkeypatch):
        monkeypatch.setenv("SP_UNKNOWN_KEY", "val")
        cfg = {"gateway": {"port": 3300}}
        result = installer_config._apply_env(cfg)
        assert "unknown" not in result
        assert result == {"gateway": {"port": 3300}}

    def test_unknown_key_ignored(self, monkeypatch):
        monkeypatch.setenv("SP_GATEWAY_UNKNOWN", "val")
        cfg = {"gateway": {"port": 3300}}
        result = installer_config._apply_env(cfg)
        assert "unknown" not in result["gateway"]
        assert result["gateway"] == {"port": 3300}

    def test_int_coercion(self, monkeypatch):
        monkeypatch.setenv("SP_DATABASE_PORT", "1234")
        cfg = {"database": {"port": 5600, "host": "localhost"}}
        result = installer_config._apply_env(cfg)
        assert result["database"]["port"] == 1234
        assert isinstance(result["database"]["port"], int)


# ---------------------------------------------------------------------------
# config.load_config()
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """load_config() cascades defaults → repo config → user config → project config → env."""

    def test_defaults_only(self, tmp_path, monkeypatch):
        # Prevent user/project config files from being picked up
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        result = installer_config.load_config(None)
        assert result["gateway"]["port"] == 3300
        assert result["web"]["port"] == 3200
        assert result["database"]["port"] == 5600

    def test_repo_config_merge(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("gateway:\n  port: 4400\n")
        result = installer_config.load_config(tmp_path)
        assert result["gateway"]["port"] == 4400
        # Other defaults must still be present
        assert result["web"]["port"] == 3200
        assert result["gateway"]["host"] == "0.0.0.0"

    def test_env_overrides_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("gateway:\n  port: 4400\n")
        monkeypatch.setenv("SP_GATEWAY_PORT", "5500")
        result = installer_config.load_config(tmp_path)
        assert result["gateway"]["port"] == 5500


# ---------------------------------------------------------------------------
# config.resolve_with_sources()
# ---------------------------------------------------------------------------


class TestResolveWithSources:
    """resolve_with_sources() returns a flat dict of (value, source_label) pairs."""

    def test_defaults_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        result = installer_config.resolve_with_sources(None)
        for flat_key, (val, source) in result.items():
            assert source == "default", f"{flat_key} expected 'default', got '{source}'"

    def test_file_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("gateway:\n  port: 4400\n")
        result = installer_config.resolve_with_sources(tmp_path)
        assert result["gateway.port"] == (4400, "repo config")
        # Key not in repo config stays default
        assert result["web.port"][1] == "default"

    def test_env_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SP_WEB_PORT", "9200")
        result = installer_config.resolve_with_sources(None)
        val, source = result["web.port"]
        assert val == 9200
        assert source == "env"


# ---------------------------------------------------------------------------
# checks.required_ports()
# ---------------------------------------------------------------------------

from signalpilot.gateway.gateway.installer import checks as installer_checks


class TestRequiredPorts:
    """required_ports() returns the correct list of ports."""

    def test_default_ports(self):
        result = installer_checks.required_ports(None)
        assert result == [3200, 3300, 3400, 3401, 5600]

    def test_config_ports(self):
        cfg = {
            "web": {"port": 8080},
            "gateway": {"port": 8081},
            "monitor": {"port": 8082, "api_port": 8083},
            "database": {"port": 9432},
        }
        result = installer_checks.required_ports(cfg)
        assert result == [8080, 8081, 8082, 8083, 9432]


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
            lambda _: (_ for _ in ()).throw(AssertionError("input() should not be called")),
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
            lambda _: (_ for _ in ()).throw(AssertionError("input() should not be called")),
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
            lambda _: (_ for _ in ()).throw(AssertionError("input() should not be called")),
        )

        with pytest.raises(SystemExit) as exc_info:
            run_install(non_interactive=True)

        assert exc_info.value.code == 1
