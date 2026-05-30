"""F-11: Tests for assert_cloud_hardening_intact() kill-switch validator.

Covers:
- Local mode skips all checks (even with kill-switches set to forbidden values).
- Cloud mode with clean env passes.
- Each of the four kill-switches triggers a RuntimeError with the correct env var name.
- Multiple violations are listed together.
- Violation messages never leak env var values (no secret URL embedding).
- Orchestrator runtime ratchet (skip_netpol is False in cloud mode regardless of env var).
"""

from __future__ import annotations

import pytest


class TestLocalModeSkipsChecks:
    def test_local_mode_skips_check(self, monkeypatch):
        """Local mode: all four kill-switches set to forbidden values → no exception."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        monkeypatch.setenv("SP_NOTEBOOK_NETWORK_POLICY", "false")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "")
        monkeypatch.setenv("SP_NOTEBOOK_DIRECT_URL", "http://secret@gateway")
        monkeypatch.setenv("SP_DISABLE_SANDBOX", "true")

        from gateway.runtime.mode import assert_cloud_hardening_intact

        # Must not raise
        assert_cloud_hardening_intact() is None


class TestCloudModeCleanEnvPasses:
    def test_cloud_mode_clean_env_passes(self, monkeypatch):
        """Cloud mode with all kill-switches unset / set to safe values → no exception."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_NETWORK_POLICY", "true")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
        monkeypatch.delenv("SP_DISABLE_SANDBOX", raising=False)

        from gateway.runtime.mode import assert_cloud_hardening_intact

        assert_cloud_hardening_intact() is None


class TestIndividualKillSwitches:
    def test_cloud_mode_with_netpol_false_raises(self, monkeypatch):
        """SP_NOTEBOOK_NETWORK_POLICY=false in cloud mode → RuntimeError naming the var."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_NETWORK_POLICY", "false")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
        monkeypatch.delenv("SP_DISABLE_SANDBOX", raising=False)

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        assert "SP_NOTEBOOK_NETWORK_POLICY" in str(exc_info.value)

    def test_cloud_mode_with_empty_runtime_class_raises(self, monkeypatch):
        """SP_NOTEBOOK_RUNTIME_CLASS="" in cloud mode → RuntimeError naming the var."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_NOTEBOOK_NETWORK_POLICY", raising=False)
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "")
        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
        monkeypatch.delenv("SP_DISABLE_SANDBOX", raising=False)

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        assert "SP_NOTEBOOK_RUNTIME_CLASS" in str(exc_info.value)

    def test_cloud_mode_with_direct_url_raises(self, monkeypatch):
        """SP_NOTEBOOK_DIRECT_URL set in cloud mode → RuntimeError naming the var."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_NOTEBOOK_NETWORK_POLICY", raising=False)
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.setenv("SP_NOTEBOOK_DIRECT_URL", "http://10.0.0.1:2718")
        monkeypatch.delenv("SP_DISABLE_SANDBOX", raising=False)

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        assert "SP_NOTEBOOK_DIRECT_URL" in str(exc_info.value)

    def test_cloud_mode_with_disable_sandbox_raises(self, monkeypatch):
        """SP_DISABLE_SANDBOX=true in cloud mode → RuntimeError naming the var."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_NOTEBOOK_NETWORK_POLICY", raising=False)
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
        monkeypatch.setenv("SP_DISABLE_SANDBOX", "true")

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        assert "SP_DISABLE_SANDBOX" in str(exc_info.value)

    def test_cloud_mode_disable_sandbox_value_1(self, monkeypatch):
        """SP_DISABLE_SANDBOX=1 is also a forbidden value."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.delenv("SP_NOTEBOOK_NETWORK_POLICY", raising=False)
        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
        monkeypatch.setenv("SP_DISABLE_SANDBOX", "1")

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        assert "SP_DISABLE_SANDBOX" in str(exc_info.value)

    def test_cloud_mode_disable_sandbox_value_yes(self, monkeypatch):
        """SP_DISABLE_SANDBOX=yes is also a forbidden value."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.delenv("SP_NOTEBOOK_NETWORK_POLICY", raising=False)
        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
        monkeypatch.setenv("SP_DISABLE_SANDBOX", "yes")

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        assert "SP_DISABLE_SANDBOX" in str(exc_info.value)


class TestMultipleViolations:
    def test_cloud_mode_multiple_violations_listed(self, monkeypatch):
        """Two kill-switches both reported in the error message."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_NETWORK_POLICY", "false")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.setenv("SP_DISABLE_SANDBOX", "true")
        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        msg = str(exc_info.value)
        assert "SP_NOTEBOOK_NETWORK_POLICY" in msg
        assert "SP_DISABLE_SANDBOX" in msg


class TestNoValueLeakage:
    def test_cloud_mode_violation_message_does_not_leak_value(self, monkeypatch):
        """Error message must not contain the actual value of a kill-switch."""
        secret_url = "http://secret-token@gateway.internal/repo.git"
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.delenv("SP_NOTEBOOK_NETWORK_POLICY", raising=False)
        monkeypatch.setenv("SP_NOTEBOOK_DIRECT_URL", secret_url)
        monkeypatch.delenv("SP_DISABLE_SANDBOX", raising=False)

        from gateway.runtime.mode import assert_cloud_hardening_intact

        with pytest.raises(RuntimeError) as exc_info:
            assert_cloud_hardening_intact()

        assert "secret-token" not in str(exc_info.value)
        assert secret_url not in str(exc_info.value)


class TestOrchestratorRatchet:
    def test_cloud_mode_orchestrator_ignores_netpol_kill_switch(self, monkeypatch):
        """In cloud mode, skip_netpol is False regardless of SP_NOTEBOOK_NETWORK_POLICY."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_NETWORK_POLICY", "false")

        from gateway.runtime.mode import is_cloud_mode

        # Replicate the ratchet expression from kubernetes.py
        import os
        skip_netpol = (not is_cloud_mode()) and os.getenv("SP_NOTEBOOK_NETWORK_POLICY", "true").lower() == "false"

        assert skip_netpol is False, (
            "skip_netpol must be False in cloud mode regardless of SP_NOTEBOOK_NETWORK_POLICY"
        )

    def test_local_mode_orchestrator_respects_netpol_kill_switch(self, monkeypatch):
        """In local mode, SP_NOTEBOOK_NETWORK_POLICY=false is still honoured."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        monkeypatch.setenv("SP_NOTEBOOK_NETWORK_POLICY", "false")

        from gateway.runtime.mode import is_cloud_mode

        import os
        skip_netpol = (not is_cloud_mode()) and os.getenv("SP_NOTEBOOK_NETWORK_POLICY", "true").lower() == "false"

        assert skip_netpol is True
