"""Tests for compute_notebook_id."""

from __future__ import annotations

import inspect

import pytest

from gateway.storage.notebook_id import compute_notebook_id


class TestNotebookId:
    def test_deterministic(self):
        """Same inputs always produce the same id."""
        assert compute_notebook_id("org1", "user1", "proj1") == compute_notebook_id(
            "org1", "user1", "proj1"
        )

    def test_returns_32_hex_chars(self):
        """Output is 32 hex characters."""
        result = compute_notebook_id("org1", "user1", "proj1")
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_none_and_empty_project_id_collapse(self):
        """project_id=None and project_id='' produce the same id."""
        assert compute_notebook_id("org1", "user1", None) == compute_notebook_id(
            "org1", "user1", ""
        )

    def test_different_org_id_produces_different_id(self):
        """Different org_id → different notebook_id."""
        a = compute_notebook_id("org-a", "user1", "proj1")
        b = compute_notebook_id("org-b", "user1", "proj1")
        assert a != b

    def test_different_user_id_produces_different_id(self):
        """Different user_id → different notebook_id."""
        a = compute_notebook_id("org1", "user-a", "proj1")
        b = compute_notebook_id("org1", "user-b", "proj1")
        assert a != b

    def test_different_project_id_produces_different_id(self):
        """Different project_id → different notebook_id."""
        a = compute_notebook_id("org1", "user1", "proj-a")
        b = compute_notebook_id("org1", "user1", "proj-b")
        assert a != b

    def test_branch_parameter_does_not_exist(self):
        """compute_notebook_id signature has no 'branch' parameter (C3)."""
        sig = inspect.signature(compute_notebook_id)
        assert "branch" not in sig.parameters, (
            "compute_notebook_id must NOT have a 'branch' parameter (C3 — branch excluded from notebook_id)"
        )

    def test_known_value(self):
        """Cross-check against a known SHA-256 computation."""
        import hashlib

        payload = "org1:user1:proj1"
        expected = hashlib.sha256(payload.encode()).hexdigest()[:32]
        assert compute_notebook_id("org1", "user1", "proj1") == expected
