"""Tests for ReFoRCE-style partitioned table deduplication.

Verifies that _deduplicate_partitioned_tables correctly identifies
date/number-partitioned table families, merges them into a single
representative, and preserves non-partitioned tables unchanged.

This is critical for Spider2.0 benchmark performance — ReFoRCE's
ablation shows this is the single most impactful compression step.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))
from gateway.main import _deduplicate_partitioned_tables


def _table(name: str, schema: str = "public", columns=None, row_count: int = 100):
    """Helper to build a minimal table dict."""
    return {
        "schema": schema,
        "name": name,
        "columns": columns or [
            {"name": "id", "type": "int"},
            {"name": "value", "type": "text"},
        ],
        "row_count": row_count,
    }


class TestDatePartitionDedup:
    """Test deduplication of YYYYMMDD-partitioned table families."""

    def test_yyyymmdd_family(self):
        """Tables like ga_sessions_20160801 through ga_sessions_20160803."""
        schema = {
            "public.ga_sessions_20160801": _table("ga_sessions_20160801", row_count=100),
            "public.ga_sessions_20160802": _table("ga_sessions_20160802", row_count=200),
            "public.ga_sessions_20160803": _table("ga_sessions_20160803", row_count=300),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        # Should collapse to 1 representative
        assert len(deduped) == 1
        rep_key = list(deduped.keys())[0]
        assert deduped[rep_key]["row_count"] == 600  # Sum of all partitions
        assert deduped[rep_key]["_partition_count"] == 3
        assert rep_key in pmap
        assert len(pmap[rep_key]) == 3

    def test_yyyy_mm_dd_family(self):
        """Tables like events_2024_01_01, events_2024_01_02, etc."""
        schema = {
            "public.events_2024_01_01": _table("events_2024_01_01"),
            "public.events_2024_01_02": _table("events_2024_01_02"),
            "public.events_2024_01_03": _table("events_2024_01_03"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        assert len(deduped) == 1
        assert len(pmap) == 1

    def test_yyyy_mm_family(self):
        """Tables like sales_2024_01, sales_2024_02, etc."""
        schema = {
            "public.sales_2024_01": _table("sales_2024_01"),
            "public.sales_2024_02": _table("sales_2024_02"),
            "public.sales_2024_03": _table("sales_2024_03"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        assert len(deduped) == 1


class TestNumericPartitionDedup:
    """Test deduplication of numeric partition suffixes."""

    def test_p_suffix_family(self):
        """Tables like data_p1, data_p2, data_p3."""
        schema = {
            "public.data_p1": _table("data_p1"),
            "public.data_p2": _table("data_p2"),
            "public.data_p3": _table("data_p3"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        assert len(deduped) == 1

    def test_numeric_suffix_family(self):
        """Tables like shard_001, shard_002, shard_003."""
        schema = {
            "public.shard_001": _table("shard_001"),
            "public.shard_002": _table("shard_002"),
            "public.shard_003": _table("shard_003"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        assert len(deduped) == 1


class TestNoFalsePositives:
    """Ensure tables that look similar but aren't partitions are preserved."""

    def test_too_few_tables(self):
        """2 tables is not enough to be considered a partition family."""
        schema = {
            "public.logs_20240101": _table("logs_20240101"),
            "public.logs_20240102": _table("logs_20240102"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        assert len(deduped) == 2  # Both preserved
        assert len(pmap) == 0

    def test_different_schemas(self):
        """Tables with different column structures should NOT be merged."""
        schema = {
            "public.data_001": _table("data_001", columns=[
                {"name": "id", "type": "int"},
                {"name": "value", "type": "text"},
            ]),
            "public.data_002": _table("data_002", columns=[
                {"name": "id", "type": "int"},
                {"name": "value", "type": "text"},
            ]),
            "public.data_003": _table("data_003", columns=[
                {"name": "id", "type": "int"},
                {"name": "different_col", "type": "float"},  # Different structure!
            ]),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        # 80% threshold: 2 out of 3 have same structure, so they CAN be deduped
        # (80% = 2/3 = 66.7% < 80% — actually won't pass)
        # Wait: 2/3 = 66.7% which is < 80%, so no dedup
        assert len(deduped) == 3

    def test_regular_tables_unchanged(self):
        """Tables without partition suffixes should pass through unchanged."""
        schema = {
            "public.users": _table("users"),
            "public.orders": _table("orders"),
            "public.products": _table("products"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        assert len(deduped) == 3
        assert len(pmap) == 0
        assert set(deduped.keys()) == {"public.users", "public.orders", "public.products"}


class TestPartitionMap:
    """Test partition_map output."""

    def test_partition_map_contains_all_members(self):
        schema = {
            "public.events_20240101": _table("events_20240101"),
            "public.events_20240102": _table("events_20240102"),
            "public.events_20240103": _table("events_20240103"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        assert len(pmap) == 1
        members = list(pmap.values())[0]
        assert len(members) == 3

    def test_row_count_aggregated(self):
        schema = {
            "public.logs_20240101": _table("logs_20240101", row_count=1000),
            "public.logs_20240102": _table("logs_20240102", row_count=2000),
            "public.logs_20240103": _table("logs_20240103", row_count=3000),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        rep = list(deduped.values())[0]
        assert rep["row_count"] == 6000

    def test_partition_base_name(self):
        schema = {
            "public.sessions_20240101": _table("sessions_20240101"),
            "public.sessions_20240102": _table("sessions_20240102"),
            "public.sessions_20240103": _table("sessions_20240103"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        rep = list(deduped.values())[0]
        assert rep["_partition_base"] == "sessions"


class TestMixedSchema:
    """Test schemas with both partitioned and non-partitioned tables."""

    def test_mixed(self):
        schema = {
            "public.users": _table("users"),
            "public.orders": _table("orders"),
            "public.ga_sessions_20240101": _table("ga_sessions_20240101"),
            "public.ga_sessions_20240102": _table("ga_sessions_20240102"),
            "public.ga_sessions_20240103": _table("ga_sessions_20240103"),
        }
        deduped, pmap = _deduplicate_partitioned_tables(schema)
        # 2 regular tables + 1 deduplicated partition family
        assert len(deduped) == 3
        assert "public.users" in deduped
        assert "public.orders" in deduped
        assert len(pmap) == 1
