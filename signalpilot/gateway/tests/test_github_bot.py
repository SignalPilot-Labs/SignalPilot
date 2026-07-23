"""Tests for the PipelineProof GitHub bot: model parsing, report rendering,
webhook signature verification, and scan orchestration with a fake connector."""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, patch

import pytest

from gateway.api.github_bot import _verify_signature
from gateway.github_bot.client import COMMENT_MARKER
from gateway.github_bot.scanner import (
    ModelCheck,
    ScanReport,
    parse_changed_models,
    render_report_markdown,
)


class TestParseChangedModels:
    def test_models_dir_sql_only(self):
        files = [
            {"filename": "models/marts/fct_orders.sql", "status": "modified"},
            {"filename": "models/staging/stg_payments.sql", "status": "added"},
            {"filename": "macros/helpers.sql", "status": "modified"},
            {"filename": "models/marts/schema.yml", "status": "modified"},
            {"filename": "README.md", "status": "modified"},
        ]
        assert parse_changed_models(files) == ["fct_orders", "stg_payments"]

    def test_removed_files_excluded(self):
        files = [{"filename": "models/old_model.sql", "status": "removed"}]
        assert parse_changed_models(files) == []

    def test_dedup_and_invalid_names(self):
        files = [
            {"filename": "models/a/fct_x.sql", "status": "modified"},
            {"filename": "models/b/fct_x.sql", "status": "modified"},
            {"filename": "models/1bad-name.sql", "status": "added"},
        ]
        assert parse_changed_models(files) == ["fct_x"]

    def test_sql_outside_models_skipped(self):
        assert parse_changed_models([{"filename": "analyses/probe.sql", "status": "added"}]) == []


class TestReportRendering:
    def _report(self, checks, skipped=None):
        return ScanReport(
            repo="o/r", pr_number=1, connection="conn", checks=checks,
            skipped=skipped or [], started_at=time.time(), duration_s=1.2,
        )

    def test_marker_present_and_verdict_fail_wins(self):
        report = self._report([
            ModelCheck(model="a", verdict="pass", exists=True, row_count=10),
            ModelCheck(model="b", verdict="fail", error="table not found"),
        ])
        assert report.verdict == "fail"
        md = render_report_markdown(report)
        assert md.startswith(COMMENT_MARKER)
        assert "table not found" in md and "`a`" in md and "`b`" in md

    def test_warn_verdict(self):
        report = self._report([ModelCheck(model="a", verdict="warn", exists=True, row_count=0)])
        assert report.verdict == "warn"

    def test_empty_pr(self):
        md = render_report_markdown(self._report([]))
        assert "No dbt models changed" in md

    def test_grain_dup_shown(self):
        c = ModelCheck(model="fct", verdict="fail", exists=True, row_count=100,
                       grain_key="fct_id", grain_duplicates=7,
                       notes=["7 duplicate value(s) on key 'fct_id' — possible join fan-out"])
        md = render_report_markdown(self._report([c]))
        assert "7 dup" in md and "fan-out" in md


class TestWebhookSignature:
    def test_valid_signature(self):
        secret, body = "s3cret", b'{"x":1}'
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert _verify_signature(secret, body, sig)

    def test_invalid_signature(self):
        assert not _verify_signature("s3cret", b"{}", "sha256=" + "0" * 64)

    def test_missing_or_malformed_header(self):
        assert not _verify_signature("s3cret", b"{}", None)
        assert not _verify_signature("s3cret", b"{}", "sha1=abc")


class _FakeConnector:
    """Connector stub returning one aggregate row (the single-pass scan)."""

    def __init__(self, agg_row: dict | None, raise_on: str | None = None):
        self.agg_row = agg_row
        self.raise_on = raise_on
        self.queries: list[str] = []

    async def execute(self, sql: str, params=None, timeout=None):
        self.queries.append(sql)
        if self.raise_on and self.raise_on in sql:
            raise RuntimeError("query exploded")
        return [self.agg_row] if self.agg_row is not None else []


class TestCheckModel:
    async def test_healthy_model_passes(self):
        from gateway.github_bot.scanner import _check_model

        connector = _FakeConnector({"row_n": 42, "key_distinct": 42, "null_0": 0, "null_1": 2})
        with patch("gateway.github_bot.scanner._get_columns", new=AsyncMock(return_value=("public.fct_orders", ["id", "amount"]))):
            check = await _check_model(connector, "postgres", "fct_orders")
        assert check.verdict == "pass"
        assert check.exists and check.row_count == 42
        assert check.grain_key == "id" and check.grain_duplicates == 0
        # single-pass: exactly one aggregate query issued
        assert len(connector.queries) == 1

    async def test_missing_table_fails(self):
        from gateway.github_bot.scanner import _check_model

        connector = _FakeConnector(None)
        with patch("gateway.github_bot.scanner._get_columns", new=AsyncMock(return_value=(None, []))):
            check = await _check_model(connector, "postgres", "ghost")
        assert check.verdict == "fail"
        assert "not found" in (check.error or "")

    async def test_grain_duplicates_fail_on_declared_key(self):
        from gateway.github_bot.scanner import _check_model

        connector = _FakeConnector({"row_n": 100, "key_distinct": 93, "null_0": 0})
        with patch("gateway.github_bot.scanner._get_columns", new=AsyncMock(return_value=("public.t", ["id"]))):
            check = await _check_model(connector, "postgres", "fct")
        assert check.verdict == "fail" and check.grain_duplicates == 7

    async def test_fallback_fk_key_dups_only_warn(self):
        """First-column *_id fallback can be a foreign key - dup rows warn, not fail."""
        from gateway.github_bot.scanner import _check_model

        connector = _FakeConnector({"row_n": 100, "key_distinct": 25, "null_0": 0})
        with patch("gateway.github_bot.scanner._get_columns", new=AsyncMock(return_value=("public.t", ["order_id", "amount"]))):
            check = await _check_model(connector, "postgres", "fct_lines")
        assert check.verdict == "warn"
        assert "4.0x" in check.notes[-1]

    async def test_zero_rows_warns(self):
        from gateway.github_bot.scanner import _check_model

        connector = _FakeConnector({"row_n": 0, "key_distinct": 0, "null_0": 0})
        with patch("gateway.github_bot.scanner._get_columns", new=AsyncMock(return_value=("public.t", ["id"]))):
            check = await _check_model(connector, "postgres", "empty_model")
        assert check.verdict == "warn"

    async def test_null_saturated_column_warns(self):
        from gateway.github_bot.scanner import _check_model

        connector = _FakeConnector({"row_n": 100, "null_0": 100, "null_1": 3})
        with patch("gateway.github_bot.scanner._get_columns", new=AsyncMock(return_value=("public.m", ["ghost_col", "ok_col"]))):
            check = await _check_model(connector, "postgres", "m")
        assert check.verdict == "warn"
        assert check.null_saturated == ["ghost_col"]

    async def test_aggregate_failure_warns_not_fails(self):
        from gateway.github_bot.scanner import _check_model

        connector = _FakeConnector(None, raise_on="SELECT")
        with patch("gateway.github_bot.scanner._get_columns", new=AsyncMock(return_value=("public.t", ["id"]))):
            check = await _check_model(connector, "postgres", "m")
        assert check.verdict == "warn"
        assert any("aggregate scan failed" in n for n in check.notes)


class TestGetColumns:
    """Exercise the real _get_columns logic (no patching)."""

    class _Conn:
        def __init__(self, rows):
            self.rows = rows
            self.queries = []

        async def execute(self, sql, params=None, timeout=None):
            self.queries.append(sql)
            return self.rows

    async def test_bare_name_resolves_across_schemas_alphabetical(self):
        from gateway.github_bot.scanner import _get_columns

        conn = self._Conn([
            {"table_schema": "b_schema", "column_name": "x"},
            {"table_schema": "a_schema", "column_name": "id"},
            {"table_schema": "a_schema", "column_name": "y"},
        ])
        resolved, cols = await _get_columns(conn, "postgres", "my_model")
        assert resolved == "a_schema.my_model"
        assert cols == ["id", "y"]

    async def test_bare_name_not_found(self):
        from gateway.github_bot.scanner import _get_columns

        resolved, cols = await _get_columns(self._Conn([]), "postgres", "ghost")
        assert resolved is None and cols == []

    async def test_qualified_name(self):
        from gateway.github_bot.scanner import _get_columns

        conn = self._Conn([{"column_name": "a"}, {"column_name": "b"}])
        resolved, cols = await _get_columns(conn, "postgres", "marts.orders")
        assert resolved == "marts.orders" and cols == ["a", "b"]

    async def test_duckdb_pragma_path(self):
        from gateway.github_bot.scanner import _get_columns

        conn = self._Conn([{"name": "c1"}, {"name": "c2"}])
        resolved, cols = await _get_columns(conn, "duckdb", "t")
        assert resolved == "t" and cols == ["c1", "c2"]
        assert "PRAGMA" in conn.queries[0]
