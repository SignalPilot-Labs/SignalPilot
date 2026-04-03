from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from signalpilot.gateway.gateway.installer import checks
from signalpilot.gateway.gateway.installer.doctor import _DiagResult, _check_system, _check_configuration, _check_endpoints, run_doctor


# ---------------------------------------------------------------------------
# doctor._DiagResult
# ---------------------------------------------------------------------------

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
