"""Tests verifying per-org isolation in governance singletons.

Each test confirms that BudgetLedger, QueryCache, SchemaCache, and annotations
are fully isolated between orgs — one org cannot see or affect another's data.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gateway.governance.budget import BudgetLedger
from gateway.governance.cache import QueryCache
from gateway.governance.context import current_org_id_var, require_org_id
from gateway.connectors.schema_cache import SchemaCache


class TestBudgetOrgIsolation:
    """BudgetLedger is isolated between orgs."""

    def test_budget_isolated_between_orgs(self):
        ledger = BudgetLedger()

        # Create session under org-A
        token_a = current_org_id_var.set("org-a")
        try:
            ledger.create_session("sess-1", 50.0)
            ledger.charge("sess-1", 10.0)
        finally:
            current_org_id_var.reset(token_a)

        # Switch to org-B — should see no session
        token_b = current_org_id_var.set("org-b")
        try:
            assert ledger.get_session("sess-1") is None
            # charge under org-B doesn't touch org-A's budget (no-tracking path returns True)
            result = ledger.charge("sess-1", 99.0)
            assert result is True  # No session found means no limit applied
        finally:
            current_org_id_var.reset(token_b)

        # Back to org-A — verify original session is intact and unaffected
        token_a2 = current_org_id_var.set("org-a")
        try:
            budget = ledger.get_session("sess-1")
            assert budget is not None
            assert budget.spent_usd == 10.0
        finally:
            current_org_id_var.reset(token_a2)

    def test_total_spent_scoped_to_org(self):
        ledger = BudgetLedger()

        token_a = current_org_id_var.set("org-a")
        try:
            ledger.create_session("s1", 100.0)
            ledger.charge("s1", 20.0)
        finally:
            current_org_id_var.reset(token_a)

        token_b = current_org_id_var.set("org-b")
        try:
            ledger.create_session("s1", 100.0)
            ledger.charge("s1", 5.0)
            assert ledger.total_spent() == 5.0
        finally:
            current_org_id_var.reset(token_b)

        token_a2 = current_org_id_var.set("org-a")
        try:
            assert ledger.total_spent() == 20.0
        finally:
            current_org_id_var.reset(token_a2)


class TestQueryCacheOrgIsolation:
    """QueryCache entries are keyed by org_id."""

    def test_query_cache_keyed_by_org(self):
        cache = QueryCache(max_entries=100, ttl_seconds=300)
        rows_a = [{"id": 1, "org": "a"}]
        rows_b = [{"id": 2, "org": "b"}]

        token_a = current_org_id_var.set("org-a")
        try:
            cache.put("conn1", "SELECT 1", 100, rows_a, ["t"], 1.0, "SELECT 1")
            hit = cache.get("conn1", "SELECT 1", 100)
            assert hit is not None
            assert hit.rows == rows_a
        finally:
            current_org_id_var.reset(token_a)

        token_b = current_org_id_var.set("org-b")
        try:
            # org-b should not see org-a's entry
            assert cache.get("conn1", "SELECT 1", 100) is None
            # org-b stores its own entry
            cache.put("conn1", "SELECT 1", 100, rows_b, ["t"], 1.0, "SELECT 1")
            hit = cache.get("conn1", "SELECT 1", 100)
            assert hit is not None
            assert hit.rows == rows_b
        finally:
            current_org_id_var.reset(token_b)

    def test_invalidate_does_not_affect_other_org(self):
        cache = QueryCache(max_entries=100, ttl_seconds=300)

        token_a = current_org_id_var.set("org-a")
        try:
            cache.put("conn1", "SELECT 1", 100, [{"a": 1}], ["t"], 1.0, "SELECT 1")
        finally:
            current_org_id_var.reset(token_a)

        token_b = current_org_id_var.set("org-b")
        try:
            cache.put("conn1", "SELECT 1", 100, [{"b": 2}], ["t"], 1.0, "SELECT 1")
            # invalidate under org-b
            cache.invalidate("conn1", all_orgs=False)
            # org-b entry is gone
            assert cache.get("conn1", "SELECT 1", 100) is None
        finally:
            current_org_id_var.reset(token_b)

        # org-a entry should still exist
        token_a2 = current_org_id_var.set("org-a")
        try:
            hit = cache.get("conn1", "SELECT 1", 100)
            assert hit is not None
        finally:
            current_org_id_var.reset(token_a2)


class TestSchemaCacheOrgIsolation:
    """SchemaCache entries are keyed by org_id."""

    def test_schema_cache_keyed_by_org(self):
        cache = SchemaCache(ttl_seconds=300)
        schema_a = {"users": {"columns": [], "name": "users"}}
        schema_b = {"orders": {"columns": [], "name": "orders"}}

        token_a = current_org_id_var.set("org-a")
        try:
            cache.put("conn1", schema_a)
            result = cache.get("conn1")
            assert result is not None
            assert "users" in result
        finally:
            current_org_id_var.reset(token_a)

        token_b = current_org_id_var.set("org-b")
        try:
            # org-b should not see org-a's schema
            assert cache.get("conn1") is None
            cache.put("conn1", schema_b)
            result = cache.get("conn1")
            assert result is not None
            assert "orders" in result
        finally:
            current_org_id_var.reset(token_b)

        # org-a schema still intact
        token_a2 = current_org_id_var.set("org-a")
        try:
            result = cache.get("conn1")
            assert result is not None
            assert "users" in result
        finally:
            current_org_id_var.reset(token_a2)


class TestAnnotationsOrgIsolation:
    """load_annotations is keyed by (org_id, connection_name)."""

    def test_annotations_cache_keyed_by_org(self, tmp_path: Path):
        """load_annotations returns independent results for different orgs."""
        import os
        from gateway.governance.annotations import load_annotations, _annotations_cache

        # Clear the global annotations cache so prior tests don't interfere
        _annotations_cache.clear()

        # Write a YAML file only for org-a
        org_a_dir = tmp_path / "annotations" / "org-a"
        org_a_dir.mkdir(parents=True)
        (org_a_dir / "myconn.yml").write_text(
            "tables:\n  users:\n    description: Org A users\n    blocked: false\n"
        )

        old_data_dir = os.environ.get("SP_DATA_DIR")
        os.environ["SP_DATA_DIR"] = str(tmp_path)
        try:
            # org-a can load annotations
            result_a = load_annotations("org-a", "myconn")
            assert "users" in result_a.tables

            # org-b gets empty annotations — cloud fallback is disabled
            result_b = load_annotations("org-b", "myconn")
            assert len(result_b.tables) == 0
        finally:
            if old_data_dir is None:
                os.environ.pop("SP_DATA_DIR", None)
            else:
                os.environ["SP_DATA_DIR"] = old_data_dir
            _annotations_cache.clear()

    def test_cloud_mode_flat_fallback_disabled(self, tmp_path: Path):
        """Cloud-mode org_id must not fall back to flat-path files."""
        import os
        from gateway.governance.annotations import load_annotations, _annotations_cache

        _annotations_cache.clear()

        # Write only a flat-path file (no per-org directory)
        ann_dir = tmp_path / "annotations"
        ann_dir.mkdir(parents=True)
        (ann_dir / "myconn.yml").write_text(
            "tables:\n  orders:\n    description: Flat path orders\n    blocked: false\n"
        )

        old_data_dir = os.environ.get("SP_DATA_DIR")
        os.environ["SP_DATA_DIR"] = str(tmp_path)
        try:
            # Cloud-mode org (non-"local") must NOT read flat file
            result = load_annotations("cloud-org-xyz", "myconn")
            assert len(result.tables) == 0
        finally:
            if old_data_dir is None:
                os.environ.pop("SP_DATA_DIR", None)
            else:
                os.environ["SP_DATA_DIR"] = old_data_dir
            _annotations_cache.clear()


class TestRequireOrgIdFails:
    """require_org_id raises when no org is set."""

    def test_require_org_id_raises_when_unset(self):
        """Calling require_org_id() without setting the var raises RuntimeError."""
        # Use a fresh context to avoid the autouse fixture's value
        import contextvars
        ctx = contextvars.copy_context()

        def _check():
            current_org_id_var.set(None)
            with pytest.raises(RuntimeError, match="governance call requires org_id"):
                require_org_id()

        ctx.run(_check)

    def test_query_cache_raises_when_unset(self):
        """QueryCache.get raises when no org context is set."""
        import contextvars
        ctx = contextvars.copy_context()
        cache = QueryCache()

        def _check():
            current_org_id_var.set(None)
            with pytest.raises(RuntimeError):
                cache.get("conn1", "SELECT 1", 100)

        ctx.run(_check)


class TestContextVarPropagation:
    """Verify that current_org_id_var is inherited by asyncio child tasks."""

    def test_contextvar_propagates_to_asyncio_create_task(self):
        """Python snapshots the context at create_task so the child sees the parent's org_id."""

        async def _run():
            token = current_org_id_var.set("org-parent")
            try:
                async def child():
                    return current_org_id_var.get()

                result = await asyncio.create_task(child())
                assert result == "org-parent", (
                    "Child task did not inherit parent's current_org_id_var. "
                    "This would break api/connections.py:382 _auto_schema_refresh."
                )
            finally:
                current_org_id_var.reset(token)

        asyncio.run(_run())
