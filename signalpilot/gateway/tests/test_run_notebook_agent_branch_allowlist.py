"""Tests for APP-L-3: agent-branch push allowlist via _validate_agent_branch.

Class: TestAgentBranchAllowlist

Pure-function tests against _validate_agent_branch — no k8s, no store, no async.
"""

from __future__ import annotations

from gateway.mcp.tools.notebook import _validate_agent_branch


class TestAgentBranchAllowlist:
    """APP-L-3: _validate_agent_branch enforces the signalpilot-agent/ prefix allowlist."""

    def test_accepts_freshly_minted_agent_branch(self) -> None:
        """Mirrors the uuid hex tail at notebook.py line 139 (12 hex chars)."""
        result = _validate_agent_branch("signalpilot-agent/" + "a" * 12)
        assert result is None

    def test_accepts_agent_branch_with_dots_and_dashes(self) -> None:
        """Proves canonical syntactic chars still flow through the composed helper."""
        result = _validate_agent_branch("signalpilot-agent/feature.test-1")
        assert result is None

    def test_rejects_main(self) -> None:
        """Branch 'main' lacks the required prefix."""
        result = _validate_agent_branch("main")
        assert result is not None
        assert "must start with 'signalpilot-agent/'" in result

    def test_rejects_master(self) -> None:
        """Branch 'master' lacks the required prefix."""
        result = _validate_agent_branch("master")
        assert result is not None
        assert "must start with 'signalpilot-agent/'" in result

    def test_rejects_user_branch_no_prefix(self) -> None:
        """A branch without the agent prefix is rejected."""
        result = _validate_agent_branch("feature/my-work")
        assert result is not None
        assert "must start with 'signalpilot-agent/'" in result

    def test_rejects_reserved_tail_main(self) -> None:
        """signalpilot-agent/main targets a reserved name."""
        result = _validate_agent_branch("signalpilot-agent/main")
        assert result is not None
        assert "reserved name" in result

    def test_rejects_reserved_tail_master(self) -> None:
        """signalpilot-agent/master targets a reserved name."""
        result = _validate_agent_branch("signalpilot-agent/master")
        assert result is not None
        assert "reserved name" in result

    def test_rejects_reserved_tail_release(self) -> None:
        """signalpilot-agent/release/1.0 targets a reserved name."""
        result = _validate_agent_branch("signalpilot-agent/release/1.0")
        assert result is not None
        assert "reserved name" in result

    def test_rejects_reserved_tail_HEAD(self) -> None:
        """signalpilot-agent/HEAD targets a reserved name."""
        result = _validate_agent_branch("signalpilot-agent/HEAD")
        assert result is not None
        assert "reserved name" in result

    def test_rejects_empty_tail(self) -> None:
        """signalpilot-agent/ with empty tail is rejected (non-None error)."""
        result = _validate_agent_branch("signalpilot-agent/")
        assert result is not None

    def test_rejects_garbage_chars_via_canonical_validator(self) -> None:
        """Canonical syntactic check fires inside the composed helper for shell-inject attempts."""
        result = _validate_agent_branch("signalpilot-agent/x; rm -rf /")
        assert result is not None
        assert result.startswith("Error: agent_branch")

    def test_rejects_leading_dash_via_canonical_validator(self) -> None:
        """Canonical validator catches leading '-' before prefix check."""
        result = _validate_agent_branch("-signalpilot-agent/x")
        assert result is not None
