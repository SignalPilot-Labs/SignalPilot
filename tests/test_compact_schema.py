"""Tests for compact schema compression with sample value injection.

Verifies that _compress_schema produces correct DDL-style output and
properly inlines sample values for ENUM-like columns (Spider2.0 optimization).
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))
from gateway.main import _compress_schema


def _make_table(name: str, columns: list[dict], **kwargs) -> dict:
    """Helper to build a schema table dict."""
    return {
        "schema": "public",
        "name": name,
        "type": kwargs.get("type", "table"),
        "columns": columns,
        "foreign_keys": kwargs.get("foreign_keys", []),
        "row_count": kwargs.get("row_count", 100),
        "indexes": kwargs.get("indexes", []),
        **{k: v for k, v in kwargs.items() if k not in ("type", "foreign_keys", "row_count", "indexes")},
    }


def _col(name: str, dtype: str = "text", **kwargs) -> dict:
    """Helper to build a column dict."""
    return {"name": name, "type": dtype, "nullable": kwargs.get("nullable", True),
            "primary_key": kwargs.get("primary_key", False),
            "comment": kwargs.get("comment", ""), "stats": kwargs.get("stats", {}),
            "low_cardinality": kwargs.get("low_cardinality", False)}


class TestBasicCompression:
    def test_creates_ddl(self):
        schema = {"public.users": _make_table("users", [
            _col("id", "integer", primary_key=True),
            _col("name", "text"),
        ])}
        result = _compress_schema(schema)
        assert "public.users" in result
        ddl = result["public.users"]["ddl"]
        assert "CREATE TABLE" in ddl
        assert "id integer" in ddl
        assert "name text" in ddl
        assert "PRIMARY KEY (id)" in ddl

    def test_view_keyword(self):
        schema = {"public.v": _make_table("v", [_col("x", "int")], type="view")}
        result = _compress_schema(schema)
        assert "CREATE VIEW" in result["public.v"]["ddl"]

    def test_not_null(self):
        schema = {"public.t": _make_table("t", [_col("id", "int", nullable=False)])}
        result = _compress_schema(schema)
        assert "NOT NULL" in result["public.t"]["ddl"]

    def test_row_count_preserved(self):
        schema = {"public.t": _make_table("t", [_col("id", "int")], row_count=42)}
        result = _compress_schema(schema)
        assert result["public.t"]["row_count"] == 42


class TestCardinalityHints:
    def test_unique_column(self):
        schema = {"public.t": _make_table("t", [
            _col("email", "text", stats={"distinct_fraction": -1.0}),
        ])}
        result = _compress_schema(schema)
        assert "UNIQUE" in result["public.t"]["ddl"]

    def test_low_cardinality_enum(self):
        schema = {"public.t": _make_table("t", [
            _col("status", "text", low_cardinality=True),
        ])}
        result = _compress_schema(schema)
        assert "ENUM" in result["public.t"]["ddl"]

    def test_low_distinct_count_enum(self):
        schema = {"public.t": _make_table("t", [
            _col("status", "varchar", stats={"distinct_count": 5}),
        ])}
        result = _compress_schema(schema)
        assert "ENUM" in result["public.t"]["ddl"]

    def test_timestamps_not_marked_enum(self):
        """Timestamp columns with low distinct counts should NOT be marked ENUM."""
        schema = {"public.t": _make_table("t", [
            _col("created_at", "timestamp", stats={"distinct_count": 3}),
        ])}
        result = _compress_schema(schema)
        assert "ENUM" not in result["public.t"]["ddl"]


class TestForeignKeyCompression:
    def test_fk_refs(self):
        schema = {"public.orders": _make_table("orders", [_col("id", "int")], foreign_keys=[
            {"column": "user_id", "references_schema": "public", "references_table": "users", "references_column": "id"},
        ])}
        result = _compress_schema(schema)
        assert result["public.orders"]["foreign_keys"] == ["user_id -> public.users.id"]

    def test_no_fk(self):
        schema = {"public.t": _make_table("t", [_col("id", "int")])}
        result = _compress_schema(schema)
        assert "foreign_keys" not in result["public.t"]


class TestComments:
    def test_column_comment_in_ddl(self):
        schema = {"public.t": _make_table("t", [
            _col("status", "text", comment="order status: pending, shipped, delivered"),
        ])}
        result = _compress_schema(schema)
        assert "-- order status" in result["public.t"]["ddl"]

    def test_table_description(self):
        schema = {"public.t": _make_table("t", [_col("id", "int")], description="Main table")}
        result = _compress_schema(schema)
        assert result["public.t"]["description"] == "Main table"


class TestSampleValueInlining:
    """Test that cached sample values are inlined for ENUM-like columns."""

    def test_enum_with_samples(self):
        schema = {"public.orders": _make_table("orders", [
            _col("status", "varchar", stats={"distinct_count": 3}),
        ])}
        sample_values = {"public.orders": {"status": ["pending", "shipped", "delivered"]}}
        result = _compress_schema(schema, sample_values)
        ddl = result["public.orders"]["ddl"]
        assert "values:" in ddl
        assert "'pending'" in ddl
        assert "'shipped'" in ddl
        assert "'delivered'" in ddl

    def test_non_enum_no_samples(self):
        """Non-ENUM columns should NOT get sample values even if available."""
        schema = {"public.t": _make_table("t", [
            _col("name", "text"),  # No low cardinality stats
        ])}
        sample_values = {"public.t": {"name": ["Alice", "Bob"]}}
        result = _compress_schema(schema, sample_values)
        assert "values:" not in result["public.t"]["ddl"]

    def test_samples_limited_to_5(self):
        schema = {"public.t": _make_table("t", [
            _col("code", "varchar", stats={"distinct_count": 8}),
        ])}
        sample_values = {"public.t": {"code": ["A", "B", "C", "D", "E", "F", "G", "H"]}}
        result = _compress_schema(schema, sample_values)
        ddl = result["public.t"]["ddl"]
        # Should include at most 5 values
        assert "'F'" not in ddl
        assert "'A'" in ddl
        assert "'E'" in ddl

    def test_no_sample_values_dict(self):
        """When sample_values is None, should still work."""
        schema = {"public.t": _make_table("t", [
            _col("status", "text", stats={"distinct_count": 3}),
        ])}
        result = _compress_schema(schema, None)
        assert "ENUM" in result["public.t"]["ddl"]
        assert "values:" not in result["public.t"]["ddl"]

    def test_sample_with_existing_comment(self):
        """Sample values should append to existing column comments."""
        schema = {"public.t": _make_table("t", [
            _col("status", "varchar", stats={"distinct_count": 2}, comment="order status"),
        ])}
        sample_values = {"public.t": {"status": ["active", "inactive"]}}
        result = _compress_schema(schema, sample_values)
        ddl = result["public.t"]["ddl"]
        assert "values:" in ddl
        assert "order status" in ddl


class TestDBSpecificMetadata:
    def test_clickhouse_engine(self):
        schema = {"default.events": _make_table("events", [_col("id", "UInt64")], engine="MergeTree")}
        result = _compress_schema(schema)
        assert result["default.events"]["engine"] == "MergeTree"

    def test_clickhouse_sorting_key(self):
        schema = {"default.events": _make_table("events", [_col("id", "UInt64")], sorting_key="id")}
        result = _compress_schema(schema)
        assert result["default.events"]["sorting_key"] == "id"

    def test_redshift_diststyle(self):
        schema = {"public.t": _make_table("t", [_col("id", "int")], diststyle="KEY")}
        result = _compress_schema(schema)
        assert result["public.t"]["diststyle"] == "KEY"

    def test_snowflake_clustering_key(self):
        schema = {"public.t": _make_table("t", [_col("id", "int")], clustering_key="id")}
        result = _compress_schema(schema)
        assert result["public.t"]["clustering_key"] == "id"

    def test_size_mb(self):
        schema = {"public.t": _make_table("t", [_col("id", "int")], size_mb=42.5)}
        result = _compress_schema(schema)
        assert result["public.t"]["size_mb"] == 42.5
