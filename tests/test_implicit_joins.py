"""Tests for implicit join detection — column name pattern matching for FK inference."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))

from gateway.schema_utils import _infer_implicit_joins


class TestImplicitJoinDetection:
    def _make_schema(self, tables: dict) -> dict:
        """Helper to build a schema dict from simplified table definitions."""
        result = {}
        for key, (schema_name, table_name, columns, fks) in tables.items():
            cols = []
            for col_name, col_type, is_pk in columns:
                cols.append({
                    "name": col_name,
                    "type": col_type,
                    "nullable": True,
                    "primary_key": is_pk,
                })
            result[key] = {
                "schema": schema_name,
                "name": table_name,
                "columns": cols,
                "foreign_keys": fks or [],
            }
        return result

    def test_basic_id_pattern(self):
        """customer_id in orders should match customers.id."""
        schema = self._make_schema({
            "public.customers": ("public", "customers", [
                ("id", "int", True),
                ("name", "varchar", False),
            ], []),
            "public.orders": ("public", "orders", [
                ("id", "int", True),
                ("customer_id", "int", False),
                ("total", "decimal", False),
            ], []),
        })
        inferred = _infer_implicit_joins(schema)
        assert len(inferred) == 1
        assert inferred[0]["from_table"] == "orders"
        assert inferred[0]["from_column"] == "customer_id"
        assert inferred[0]["to_table"] == "customers"
        assert inferred[0]["to_column"] == "id"
        assert inferred[0]["inferred"] is True

    def test_plural_s_matching(self):
        """product_id should match products table."""
        schema = self._make_schema({
            "public.products": ("public", "products", [
                ("id", "int", True),
                ("name", "varchar", False),
            ], []),
            "public.order_items": ("public", "order_items", [
                ("id", "int", True),
                ("product_id", "int", False),
            ], []),
        })
        inferred = _infer_implicit_joins(schema)
        assert any(
            r["from_column"] == "product_id" and r["to_table"] == "products"
            for r in inferred
        )

    def test_skips_existing_fks(self):
        """Should not duplicate columns that already have explicit FK declarations."""
        schema = self._make_schema({
            "public.customers": ("public", "customers", [
                ("id", "int", True),
            ], []),
            "public.orders": ("public", "orders", [
                ("id", "int", True),
                ("customer_id", "int", False),
            ], [{
                "column": "customer_id",
                "references_schema": "public",
                "references_table": "customers",
                "references_column": "id",
            }]),
        })
        inferred = _infer_implicit_joins(schema)
        assert len(inferred) == 0

    def test_no_self_reference(self):
        """Should not infer a join from a table to itself."""
        schema = self._make_schema({
            "public.orders": ("public", "orders", [
                ("id", "int", True),
                ("order_id", "int", False),
            ], []),
        })
        inferred = _infer_implicit_joins(schema)
        assert len(inferred) == 0

    def test_multiple_inferred_joins(self):
        """Multiple _id columns should each be detected."""
        schema = self._make_schema({
            "public.customers": ("public", "customers", [
                ("id", "int", True),
            ], []),
            "public.products": ("public", "products", [
                ("id", "int", True),
            ], []),
            "public.orders": ("public", "orders", [
                ("id", "int", True),
                ("customer_id", "int", False),
                ("product_id", "int", False),
            ], []),
        })
        inferred = _infer_implicit_joins(schema)
        assert len(inferred) == 2
        cols = {r["from_column"] for r in inferred}
        assert "customer_id" in cols
        assert "product_id" in cols

    def test_confidence_field(self):
        """All inferred joins should have confidence='high'."""
        schema = self._make_schema({
            "public.users": ("public", "users", [
                ("id", "int", True),
            ], []),
            "public.posts": ("public", "posts", [
                ("id", "int", True),
                ("user_id", "int", False),
            ], []),
        })
        inferred = _infer_implicit_joins(schema)
        assert all(r["confidence"] == "high" for r in inferred)

    def test_no_match_without_target_table(self):
        """xyz_id should not match anything if there's no xyzs table."""
        schema = self._make_schema({
            "public.orders": ("public", "orders", [
                ("id", "int", True),
                ("widget_id", "int", False),
            ], []),
        })
        inferred = _infer_implicit_joins(schema)
        assert len(inferred) == 0

    def test_empty_schema(self):
        """Empty schema should return empty list."""
        assert _infer_implicit_joins({}) == []
