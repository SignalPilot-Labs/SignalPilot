"""Tests for WorkspaceKey validation."""

from __future__ import annotations

import pytest

from gateway.storage.workspace_store import WorkspaceKey


class TestWorkspaceKeyValidation:
    def test_valid_key_constructs(self):
        """Valid fields construct without error."""
        key = WorkspaceKey(org_id="org1", user_id="user1", notebook_id="abc123")
        assert key.org_id == "org1"
        assert key.user_id == "user1"
        assert key.notebook_id == "abc123"

    def test_valid_key_with_hyphens_and_underscores(self):
        """Hyphens and underscores are allowed."""
        key = WorkspaceKey(org_id="org-1", user_id="user_1", notebook_id="abc-def_123")
        assert key.org_id == "org-1"

    def test_empty_org_id_raises(self):
        """Empty org_id raises ValueError."""
        with pytest.raises(ValueError, match="org_id"):
            WorkspaceKey(org_id="", user_id="user1", notebook_id="nb1")

    def test_empty_user_id_raises(self):
        """Empty user_id raises ValueError."""
        with pytest.raises(ValueError, match="user_id"):
            WorkspaceKey(org_id="org1", user_id="", notebook_id="nb1")

    def test_empty_notebook_id_raises(self):
        """Empty notebook_id raises ValueError."""
        with pytest.raises(ValueError, match="notebook_id"):
            WorkspaceKey(org_id="org1", user_id="user1", notebook_id="")

    def test_dotdot_in_org_id_raises(self):
        """'..' in org_id raises ValueError (no traversal)."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="..", user_id="user1", notebook_id="nb1")

    def test_slash_in_user_id_raises(self):
        """'/' in user_id raises ValueError."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="org1", user_id="user/1", notebook_id="nb1")

    def test_backslash_in_notebook_id_raises(self):
        r"""'\' in notebook_id raises ValueError."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="org1", user_id="user1", notebook_id="nb\\1")

    def test_nul_byte_raises(self):
        """NUL byte in any field raises ValueError."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="org\x001", user_id="user1", notebook_id="nb1")

    def test_non_ascii_raises(self):
        """Non-ASCII characters raise ValueError."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="orgé", user_id="user1", notebook_id="nb1")

    def test_frozen_immutable(self):
        """WorkspaceKey is frozen (immutable)."""
        key = WorkspaceKey(org_id="org1", user_id="user1", notebook_id="nb1")
        with pytest.raises((AttributeError, TypeError)):
            key.org_id = "other"  # type: ignore[misc]

    def test_equality_and_hash(self):
        """Equal keys have the same hash (usable in sets/dicts)."""
        k1 = WorkspaceKey(org_id="org1", user_id="user1", notebook_id="nb1")
        k2 = WorkspaceKey(org_id="org1", user_id="user1", notebook_id="nb1")
        assert k1 == k2
        assert hash(k1) == hash(k2)
