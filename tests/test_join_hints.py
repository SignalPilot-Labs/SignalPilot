"""Tests for schema linking join hints — Spider2.0 optimization.

Verifies that the schema linker correctly identifies FK-based and
inferred join paths between linked tables and returns them as hints.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))
from gateway.schema_utils import _infer_implicit_joins


def _table(name: str, schema: str = "public", columns=None, fks=None, row_count=100):
    """Helper to build a minimal table dict."""
    return {
        "schema": schema,
        "name": name,
        "columns": columns or [{"name": "id", "type": "int", "primary_key": True}],
        "foreign_keys": fks or [],
        "row_count": row_count,
    }


class TestImplicitJoinInference:
    """Test _infer_implicit_joins for tables without declared FKs."""

    def test_customer_id_to_customers(self):
        """orders.customer_id → customers.id pattern."""
        schema = {
            "public.customers": _table("customers", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "text"},
            ]),
            "public.orders": _table("orders", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "customer_id", "type": "int"},
                {"name": "total", "type": "numeric"},
            ]),
        }
        inferred = _infer_implicit_joins(schema)
        assert len(inferred) >= 1
        # Should find orders.customer_id → customers.id
        match = [ij for ij in inferred
                 if ij["from_table"] == "orders" and ij["from_column"] == "customer_id"
                 and ij["to_table"] == "customers" and ij["to_column"] == "id"]
        assert len(match) == 1

    def test_no_false_positives_for_non_id_columns(self):
        """Don't infer joins for columns that don't match _id patterns."""
        schema = {
            "public.users": _table("users", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "email", "type": "text"},
            ]),
            "public.logs": _table("logs", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "message", "type": "text"},
            ]),
        }
        inferred = _infer_implicit_joins(schema)
        assert len(inferred) == 0

    def test_explicit_fks_not_duplicated(self):
        """Tables with explicit FKs should not get duplicate inferred joins."""
        schema = {
            "public.customers": _table("customers", columns=[
                {"name": "id", "type": "int", "primary_key": True},
            ]),
            "public.orders": _table("orders", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "customer_id", "type": "int"},
            ], fks=[{
                "column": "customer_id",
                "references_schema": "public",
                "references_table": "customers",
                "references_column": "id",
            }]),
        }
        inferred = _infer_implicit_joins(schema)
        # customer_id already has an explicit FK — should not be inferred again
        customer_joins = [ij for ij in inferred if ij["from_column"] == "customer_id"]
        assert len(customer_joins) == 0

    def test_product_id_plural_matching(self):
        """product_id should match 'products' table (singular → plural)."""
        schema = {
            "public.products": _table("products", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "text"},
            ]),
            "public.order_items": _table("order_items", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "product_id", "type": "int"},
                {"name": "quantity", "type": "int"},
            ]),
        }
        inferred = _infer_implicit_joins(schema)
        match = [ij for ij in inferred
                 if ij["from_column"] == "product_id" and ij["to_table"] == "products"]
        assert len(match) == 1

    def test_multiple_inferred_joins(self):
        """Multiple _id columns should each produce an inferred join."""
        schema = {
            "public.users": _table("users", columns=[
                {"name": "id", "type": "int", "primary_key": True},
            ]),
            "public.products": _table("products", columns=[
                {"name": "id", "type": "int", "primary_key": True},
            ]),
            "public.reviews": _table("reviews", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "user_id", "type": "int"},
                {"name": "product_id", "type": "int"},
            ]),
        }
        inferred = _infer_implicit_joins(schema)
        user_join = [ij for ij in inferred if ij["from_column"] == "user_id" and ij["to_table"] == "users"]
        product_join = [ij for ij in inferred if ij["from_column"] == "product_id" and ij["to_table"] == "products"]
        assert len(user_join) == 1
        assert len(product_join) == 1


class TestJoinHintConstruction:
    """Test that join hints are built correctly from FKs between linked tables.

    The actual join hint construction happens inside schema_link() — we test
    the FK matching logic pattern here.
    """

    def test_fk_between_linked_tables_produces_hint(self):
        """Simulate the join hint extraction from FK data."""
        linked_tables = {
            "public.orders": _table("orders", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "customer_id", "type": "int"},
            ], fks=[{
                "column": "customer_id",
                "references_schema": "public",
                "references_table": "customers",
                "references_column": "id",
            }]),
            "public.customers": _table("customers", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "text"},
            ]),
        }
        # Replicate the join hint logic from main.py
        hints = []
        seen = set()
        for key, t in linked_tables.items():
            for fk in t.get("foreign_keys", []):
                ref_table = fk.get("references_table", "")
                ref_col = fk.get("references_column", "")
                fk_col = fk.get("column", "")
                for ref_key, ref_data in linked_tables.items():
                    if ref_data.get("name", "") == ref_table:
                        pair = tuple(sorted([key, ref_key]))
                        if pair not in seen:
                            seen.add(pair)
                            hints.append(f"{t['name']}.{fk_col} = {ref_table}.{ref_col}")
                        break

        assert len(hints) == 1
        assert hints[0] == "orders.customer_id = customers.id"

    def test_self_referencing_fk(self):
        """employees.manager_id → employees.id should produce a hint."""
        linked_tables = {
            "public.employees": _table("employees", columns=[
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "manager_id", "type": "int"},
            ], fks=[{
                "column": "manager_id",
                "references_schema": "public",
                "references_table": "employees",
                "references_column": "id",
            }]),
        }
        hints = []
        seen = set()
        for key, t in linked_tables.items():
            for fk in t.get("foreign_keys", []):
                ref_table = fk.get("references_table", "")
                ref_col = fk.get("references_column", "")
                fk_col = fk.get("column", "")
                for ref_key, ref_data in linked_tables.items():
                    if ref_data.get("name", "") == ref_table:
                        pair = tuple(sorted([key, ref_key]))
                        if pair not in seen:
                            seen.add(pair)
                            hints.append(f"{t['name']}.{fk_col} = {ref_table}.{ref_col}")
                        break
        assert len(hints) == 1
        assert "manager_id" in hints[0]

    def test_no_hints_when_tables_unrelated(self):
        """Tables without FK connections produce no hints."""
        linked_tables = {
            "public.users": _table("users"),
            "public.products": _table("products"),
        }
        hints = []
        for key, t in linked_tables.items():
            for fk in t.get("foreign_keys", []):
                ref_table = fk.get("references_table", "")
                for ref_key, ref_data in linked_tables.items():
                    if ref_data.get("name", "") == ref_table:
                        hints.append("found")
                        break
        assert len(hints) == 0
