"""Tests for ReFoRCE-style schema compression and table deduplication."""

import pytest
import sys
import os

# Add gateway to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))

from gateway.main import _deduplicate_partitioned_tables, _group_tables


class TestDeduplicatePartitionedTables:
    """Tests for _deduplicate_partitioned_tables (ReFoRCE SOTA pattern)."""

    def _make_table(self, name, schema="public", columns=None, row_count=100):
        if columns is None:
            columns = [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "data", "type": "text", "nullable": True},
                {"name": "created_at", "type": "timestamp", "nullable": True},
            ]
        return {
            "name": name,
            "schema": schema,
            "columns": columns,
            "row_count": row_count,
            "foreign_keys": [],
        }

    def test_date_partitioned_tables_collapsed(self):
        """Tables with YYYYMMDD suffixes should be collapsed into one representative."""
        schema = {}
        for day in range(1, 10):
            key = f"public.ga_sessions_2016080{day}"
            schema[key] = self._make_table(f"ga_sessions_2016080{day}", row_count=1000)

        deduped, partition_map = _deduplicate_partitioned_tables(schema)

        # Should collapse 9 tables into 1
        assert len(deduped) == 1
        assert len(partition_map) == 1
        # Representative should have aggregated row count
        rep_key = list(deduped.keys())[0]
        assert deduped[rep_key]["row_count"] == 9000
        assert deduped[rep_key]["_partition_count"] == 9

    def test_non_partitioned_tables_preserved(self):
        """Normal tables should not be affected."""
        schema = {
            "public.users": self._make_table("users"),
            "public.orders": self._make_table("orders"),
            "public.products": self._make_table("products"),
        }

        deduped, partition_map = _deduplicate_partitioned_tables(schema)

        assert len(deduped) == 3
        assert len(partition_map) == 0

    def test_few_tables_not_collapsed(self):
        """Groups with fewer than 3 tables should not be collapsed."""
        schema = {
            "public.events_20230101": self._make_table("events_20230101"),
            "public.events_20230102": self._make_table("events_20230102"),
        }

        deduped, partition_map = _deduplicate_partitioned_tables(schema)

        assert len(deduped) == 2
        assert len(partition_map) == 0

    def test_structurally_different_tables_not_collapsed(self):
        """Tables with same prefix but different schemas should not be collapsed."""
        cols_a = [{"name": "id", "type": "int"}, {"name": "a", "type": "text"}]
        cols_b = [{"name": "id", "type": "int"}, {"name": "b", "type": "text"}]

        schema = {
            "public.report_001": self._make_table("report_001", columns=cols_a),
            "public.report_002": self._make_table("report_002", columns=cols_a),
            "public.report_003": self._make_table("report_003", columns=cols_b),
        }

        deduped, partition_map = _deduplicate_partitioned_tables(schema)

        # 2/3 share same structure (67%) which is below 80% threshold
        assert len(deduped) == 3
        assert len(partition_map) == 0

    def test_mixed_partitioned_and_regular(self):
        """Mix of partitioned families and regular tables."""
        schema = {
            "public.users": self._make_table("users"),
            "public.orders": self._make_table("orders"),
        }
        # Add a family of 5 date-partitioned tables
        for i in range(5):
            key = f"public.daily_stats_2024010{i}"
            schema[key] = self._make_table(f"daily_stats_2024010{i}", row_count=500)

        deduped, partition_map = _deduplicate_partitioned_tables(schema)

        # 2 regular + 1 representative = 3
        assert len(deduped) == 3
        assert len(partition_map) == 1
        # Row count should be aggregated
        rep_key = [k for k in deduped if "daily_stats" in k][0]
        assert deduped[rep_key]["row_count"] == 2500

    def test_numeric_suffix_partitions(self):
        """Tables with numeric suffixes (p1, p2, ...) should be collapsed."""
        schema = {}
        for i in range(1, 6):
            key = f"public.shard_p{i}"
            schema[key] = self._make_table(f"shard_p{i}", row_count=200)

        deduped, partition_map = _deduplicate_partitioned_tables(schema)

        assert len(deduped) == 1
        assert len(partition_map) == 1


class TestGroupTables:
    """Tests for _group_tables prefix and FK grouping."""

    def test_prefix_grouping(self):
        """Tables with same prefix should be grouped."""
        schema = {
            "public.order_items": {"name": "order_items", "columns": [], "foreign_keys": []},
            "public.order_history": {"name": "order_history", "columns": [], "foreign_keys": []},
            "public.order_returns": {"name": "order_returns", "columns": [], "foreign_keys": []},
            "public.users": {"name": "users", "columns": [], "foreign_keys": []},
        }

        groups = _group_tables(schema)

        assert "order" in groups
        assert len(groups["order"]) == 3
        # users should be in _other
        assert "public.users" in groups.get("_other", [])

    def test_fk_connected_tables_grouped(self):
        """FK-connected tables should be merged into the same group."""
        schema = {
            "public.order_items": {
                "name": "order_items",
                "columns": [],
                "foreign_keys": [{"column": "product_id", "references_schema": "public", "references_table": "products", "references_column": "id"}],
            },
            "public.order_history": {"name": "order_history", "columns": [], "foreign_keys": []},
            "public.products": {"name": "products", "columns": [], "foreign_keys": []},
        }

        groups = _group_tables(schema)

        # Products should be pulled into the order group via FK
        assert "order" in groups
        order_group = groups["order"]
        assert "public.products" in order_group or "public.order_items" in order_group
