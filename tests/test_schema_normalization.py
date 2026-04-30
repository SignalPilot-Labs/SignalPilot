"""Tests for schema normalization across all connector types.

Verifies that _normalize_schema fills missing baseline fields so
downstream consumers get consistent structure regardless of DB type.
"""

import pytest
from signalpilot.gateway.gateway.connectors.schema_cache import _normalize_schema


class TestNormalization:
    """Test that schema normalization fills missing defaults."""

    def test_fills_missing_table_fields(self):
        schema = {
            "public.t": {
                "columns": [{"name": "id", "type": "int"}],
            }
        }
        _normalize_schema(schema)
        t = schema["public.t"]
        assert t["schema"] == ""
        assert t["name"] == "t"
        assert t["type"] == "table"
        assert t["foreign_keys"] == []
        assert t["row_count"] == 0
        assert t["description"] == ""

    def test_fills_missing_column_fields(self):
        schema = {
            "public.t": {
                "columns": [{"name": "x", "type": "bigint"}],
                "foreign_keys": [],
            }
        }
        _normalize_schema(schema)
        col = schema["public.t"]["columns"][0]
        assert col["nullable"] is True
        assert col["primary_key"] is False
        assert col["comment"] == ""

    def test_preserves_existing_values(self):
        schema = {
            "public.t": {
                "schema": "public",
                "name": "t",
                "type": "view",
                "columns": [
                    {"name": "id", "type": "bigint", "nullable": False, "primary_key": True, "comment": "PK"},
                ],
                "foreign_keys": [{"column": "fk", "references_table": "other", "references_column": "id"}],
                "row_count": 42,
                "description": "My table",
            }
        }
        _normalize_schema(schema)
        t = schema["public.t"]
        assert t["type"] == "view"
        assert t["row_count"] == 42
        assert t["description"] == "My table"
        col = t["columns"][0]
        assert col["nullable"] is False
        assert col["primary_key"] is True
        assert col["comment"] == "PK"

    def test_size_bytes_to_size_mb_conversion(self):
        schema = {
            "public.t": {
                "columns": [],
                "size_bytes": 10485760,  # 10 MB
            }
        }
        _normalize_schema(schema)
        assert schema["public.t"]["size_mb"] == 10.0

    def test_size_mb_not_overwritten(self):
        schema = {
            "public.t": {
                "columns": [],
                "size_bytes": 10485760,
                "size_mb": 99,  # Already set — should not be overwritten
            }
        }
        _normalize_schema(schema)
        assert schema["public.t"]["size_mb"] == 99

    def test_name_extracted_from_key(self):
        schema = {
            "catalog.schema.my_table": {
                "columns": [],
            }
        }
        _normalize_schema(schema)
        assert schema["catalog.schema.my_table"]["name"] == "my_table"

    def test_empty_schema_no_error(self):
        schema = {}
        _normalize_schema(schema)
        assert schema == {}

    def test_column_missing_type_gets_unknown(self):
        schema = {
            "t": {
                "columns": [{"name": "x"}],
            }
        }
        _normalize_schema(schema)
        assert schema["t"]["columns"][0]["type"] == "unknown"

    def test_bigquery_style_schema(self):
        """BigQuery returns size_bytes and mode but not size_mb or nullable."""
        schema = {
            "project.dataset.events": {
                "schema": "project.dataset",
                "name": "events",
                "type": "table",
                "columns": [
                    {"name": "event_id", "type": "STRING", "primary_key": False, "mode": "REQUIRED"},
                    {"name": "payload", "type": "JSON", "mode": "NULLABLE"},
                ],
                "row_count": 1000000,
                "size_bytes": 536870912,  # 512 MB
            }
        }
        _normalize_schema(schema)
        t = schema["project.dataset.events"]
        assert t["foreign_keys"] == []
        assert t["description"] == ""
        assert t["size_mb"] == 512.0
        # Columns should have baseline fields
        for col in t["columns"]:
            assert "nullable" in col
            assert "comment" in col

    def test_clickhouse_style_schema(self):
        """ClickHouse returns engine/sorting_key but might miss foreign_keys."""
        schema = {
            "default.hits": {
                "schema": "default",
                "name": "hits",
                "type": "table",
                "columns": [
                    {"name": "id", "type": "UInt64", "primary_key": True, "nullable": False},
                    {"name": "url", "type": "String", "nullable": False, "low_cardinality": True},
                ],
                "engine": "MergeTree",
                "sorting_key": "id",
                "row_count": 50000,
            }
        }
        _normalize_schema(schema)
        t = schema["default.hits"]
        assert t["foreign_keys"] == []
        assert t["description"] == ""
        # DB-specific fields preserved
        assert t["engine"] == "MergeTree"
        assert t["sorting_key"] == "id"
