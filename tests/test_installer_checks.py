import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from signalpilot.gateway.gateway.installer import checks
from signalpilot.gateway.gateway.installer import checks as installer_checks


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
# checks.required_ports()
# ---------------------------------------------------------------------------

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
