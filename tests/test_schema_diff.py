"""Tests for schema fingerprinting, diff detection, and change history.

Verifies that:
- Schema fingerprinting detects structural changes but ignores volatile fields
- Diff tracking records change events on put()
- Change history is ordered newest-first and capped
"""

import time
import pytest
from signalpilot.gateway.gateway.connectors.schema_cache import (
    SchemaCache,
    _schema_fingerprint,
    _compute_schema_diff,
)


# ── Sample schemas for testing ──

SCHEMA_V1 = {
    "public.users": {
        "schema": "public",
        "name": "users",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "email", "type": "varchar", "primary_key": False, "nullable": False},
            {"name": "name", "type": "varchar", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [],
        "row_count": 1000,
    },
    "public.orders": {
        "schema": "public",
        "name": "orders",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "user_id", "type": "bigint", "primary_key": False, "nullable": False},
            {"name": "total", "type": "numeric", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [
            {"column": "user_id", "references_table": "users", "references_column": "id"},
        ],
        "row_count": 5000,
    },
}

# V2: added a column to users
SCHEMA_V2 = {
    "public.users": {
        "schema": "public",
        "name": "users",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "email", "type": "varchar", "primary_key": False, "nullable": False},
            {"name": "name", "type": "varchar", "primary_key": False, "nullable": True},
            {"name": "phone", "type": "varchar", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [],
        "row_count": 1200,
    },
    "public.orders": {
        "schema": "public",
        "name": "orders",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "user_id", "type": "bigint", "primary_key": False, "nullable": False},
            {"name": "total", "type": "numeric", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [
            {"column": "user_id", "references_table": "users", "references_column": "id"},
        ],
        "row_count": 6000,
    },
}

# V3: added a new table
SCHEMA_V3 = {
    **SCHEMA_V2,
    "public.products": {
        "schema": "public",
        "name": "products",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "name", "type": "varchar", "primary_key": False, "nullable": False},
            {"name": "price", "type": "numeric", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [],
        "row_count": 200,
    },
}


class TestSchemaFingerprint:
    """Test structural fingerprint computation."""

    def test_same_schema_same_fingerprint(self):
        fp1 = _schema_fingerprint(SCHEMA_V1)
        fp2 = _schema_fingerprint(SCHEMA_V1)
        assert fp1 == fp2

    def test_different_structure_different_fingerprint(self):
        fp1 = _schema_fingerprint(SCHEMA_V1)
        fp2 = _schema_fingerprint(SCHEMA_V2)
        assert fp1 != fp2

    def test_added_table_changes_fingerprint(self):
        fp2 = _schema_fingerprint(SCHEMA_V2)
        fp3 = _schema_fingerprint(SCHEMA_V3)
        assert fp2 != fp3

    def test_row_count_change_does_not_affect_fingerprint(self):
        """Volatile fields like row_count should not change the fingerprint."""
        schema_a = {
            "public.t": {
                "columns": [{"name": "id", "type": "int", "primary_key": True, "nullable": False}],
                "foreign_keys": [],
                "row_count": 100,
            }
        }
        schema_b = {
            "public.t": {
                "columns": [{"name": "id", "type": "int", "primary_key": True, "nullable": False}],
                "foreign_keys": [],
                "row_count": 99999,
            }
        }
        assert _schema_fingerprint(schema_a) == _schema_fingerprint(schema_b)

    def test_fingerprint_is_hex_string(self):
        fp = _schema_fingerprint(SCHEMA_V1)
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_empty_schema_fingerprint(self):
        fp = _schema_fingerprint({})
        assert len(fp) == 16


class TestSchemaDiff:
    """Test the _compute_schema_diff function."""

    def test_no_changes(self):
        diff = _compute_schema_diff(SCHEMA_V1, SCHEMA_V1)
        assert diff["has_changes"] is False
        assert diff["added_tables"] == []
        assert diff["removed_tables"] == []

    def test_added_column_detected(self):
        diff = _compute_schema_diff(SCHEMA_V1, SCHEMA_V2)
        assert diff["has_changes"] is True
        assert len(diff["modified_tables"]) == 1
        mod = diff["modified_tables"][0]
        assert mod["table"] == "public.users"
        assert "phone" in mod["added_columns"]

    def test_added_table_detected(self):
        diff = _compute_schema_diff(SCHEMA_V2, SCHEMA_V3)
        assert diff["has_changes"] is True
        assert "public.products" in diff["added_tables"]

    def test_removed_table_detected(self):
        diff = _compute_schema_diff(SCHEMA_V3, SCHEMA_V2)
        assert diff["has_changes"] is True
        assert "public.products" in diff["removed_tables"]

    def test_type_change_detected(self):
        old = {
            "t": {
                "columns": [{"name": "x", "type": "int"}],
                "foreign_keys": [],
            }
        }
        new = {
            "t": {
                "columns": [{"name": "x", "type": "bigint"}],
                "foreign_keys": [],
            }
        }
        diff = _compute_schema_diff(old, new)
        assert diff["has_changes"] is True
        assert diff["modified_tables"][0]["type_changes"][0]["old_type"] == "int"
        assert diff["modified_tables"][0]["type_changes"][0]["new_type"] == "bigint"


class TestSchemaCacheDiffTracking:
    """Test SchemaCache fingerprinting and diff history."""

    def test_put_computes_fingerprint(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("test-conn", SCHEMA_V1)
        fp = cache.get_fingerprint("test-conn")
        assert fp is not None
        assert len(fp) == 16

    def test_has_structural_change_detects_diff(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("test-conn", SCHEMA_V1)
        assert cache.has_structural_change("test-conn", SCHEMA_V1) is False
        assert cache.has_structural_change("test-conn", SCHEMA_V2) is True

    def test_has_structural_change_returns_true_when_no_cache(self):
        cache = SchemaCache(ttl_seconds=60)
        assert cache.has_structural_change("missing", SCHEMA_V1) is True

    def test_track_diff_records_event(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("test-conn", SCHEMA_V1)
        # Now put V2 with tracking
        diff_result = cache.put("test-conn", SCHEMA_V2, track_diff=True)
        assert diff_result is not None
        assert diff_result["has_changes"] is True

        # Check history
        history = cache.get_diff_history("test-conn")
        assert len(history) == 1
        assert history[0]["connection_name"] == "test-conn"
        assert history[0]["diff"]["has_changes"] is True

    def test_track_diff_no_change_returns_none(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("test-conn", SCHEMA_V1)
        # Put same schema again
        diff_result = cache.put("test-conn", SCHEMA_V1, track_diff=True)
        assert diff_result is None

    def test_diff_history_newest_first(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("test-conn", SCHEMA_V1)
        cache.put("test-conn", SCHEMA_V2, track_diff=True)
        cache.put("test-conn", SCHEMA_V3, track_diff=True)

        history = cache.get_diff_history("test-conn")
        assert len(history) == 2
        # Newest first
        assert history[0]["timestamp"] >= history[1]["timestamp"]

    def test_diff_history_all_connections(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("conn-a", SCHEMA_V1)
        cache.put("conn-b", SCHEMA_V1)
        cache.put("conn-a", SCHEMA_V2, track_diff=True)
        cache.put("conn-b", SCHEMA_V3, track_diff=True)

        history = cache.get_diff_history()
        assert len(history) == 2
        conn_names = {e["connection_name"] for e in history}
        assert conn_names == {"conn-a", "conn-b"}

    def test_stats_includes_fingerprints(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("test-conn", SCHEMA_V1)
        stats = cache.stats()
        assert "fingerprints" in stats
        assert "test-conn" in stats["fingerprints"]
        assert "diff_events_total" in stats

    def test_diff_history_capped(self):
        """History should not grow unbounded — max 20 per connection."""
        cache = SchemaCache(ttl_seconds=60)
        # Alternate between V1 and V2 to create many diff events
        for i in range(25):
            schema = SCHEMA_V1 if i % 2 == 0 else SCHEMA_V2
            cache.put("test-conn", schema, track_diff=True)

        history = cache.get_diff_history("test-conn")
        assert len(history) <= 20
