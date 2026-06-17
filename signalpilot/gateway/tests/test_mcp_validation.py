"""Tests for MCP input validation helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gateway.governance import plan_limits
from gateway.governance import annotations as annotations_mod
from gateway.governance.context import current_org_id_var
from gateway.governance.annotations import SchemaAnnotations
from gateway.mcp.tools import query as query_tools
from gateway.mcp.validation import _MODEL_NAME_RE


class TestModelNameRe:
    def test_model_name_re_rejects_empty_segments(self) -> None:
        assert _MODEL_NAME_RE.match("a..b") is None

    def test_model_name_re_accepts_three_segments(self) -> None:
        assert _MODEL_NAME_RE.match("db.schema.tbl") is not None

    def test_model_name_re_rejects_leading_dot(self) -> None:
        assert _MODEL_NAME_RE.match(".foo") is None

    def test_model_name_re_rejects_trailing_dot(self) -> None:
        assert _MODEL_NAME_RE.match("foo.") is None

    def test_model_name_re_accepts_single_segment(self) -> None:
        assert _MODEL_NAME_RE.match("my_model") is not None

    def test_model_name_re_accepts_two_segments(self) -> None:
        assert _MODEL_NAME_RE.match("schema.table") is not None

    def test_model_name_re_rejects_four_segments(self) -> None:
        assert _MODEL_NAME_RE.match("a.b.c.d") is None


@pytest.mark.asyncio
async def test_query_database_uses_connection_dialect_for_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStore:
        org_id = "org-1"

        async def get_connection(self, connection_name: str):
            return SimpleNamespace(
                name=connection_name,
                db_type="duckdb",
                pii_enabled=False,
                pii_rules={},
            )

        async def list_connections(self):
            return []

        async def get_connection_string(self, connection_name: str):
            raise AssertionError("blocked SQL must not reach connector credentials")

    @asynccontextmanager
    async def fake_store_session():
        token = current_org_id_var.set("org-1")
        try:
            yield FakeStore()
        finally:
            current_org_id_var.reset(token)

    async def fake_get_org_limits(org_id: str):
        return plan_limits.PLAN_TIERS["unlimited"]

    monkeypatch.setattr(query_tools, "_store_session", fake_store_session)
    monkeypatch.setattr(plan_limits, "get_org_limits", fake_get_org_limits)
    monkeypatch.setattr(plan_limits, "check_query_limit", lambda org_id, plan: None)
    monkeypatch.setattr(annotations_mod, "load_annotations", lambda org_id, connection_name: SchemaAnnotations())

    result = await query_tools.query_database.__wrapped__(
        "duck",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
    )

    assert result.startswith("Query blocked:")
    assert "read_csv_auto" in result.lower()
