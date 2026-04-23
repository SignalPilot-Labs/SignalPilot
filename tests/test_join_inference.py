"""Tests for implicit join inference algorithm.

Verifies that _infer_implicit_joins correctly detects FK-like
relationships from column naming patterns, critical for Spider2.0
performance on databases without explicit FK declarations (ClickHouse,
BigQuery, data lakes).
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))

from gateway.schema_utils import _infer_implicit_joins


def _make_table(name, schema="public", columns=None, foreign_keys=None):
    if columns is None:
        columns = [{"name": "id", "type": "integer", "primary_key": True}]
    return {
        "name": name,
        "schema": schema,
        "columns": columns,
        "foreign_keys": foreign_keys or [],
    }


class TestBasicPatterns:
    """Test fundamental join inference patterns."""

    def test_customer_id_to_customers(self):
        """customer_id column should join to customers.id."""
        schema = {
            "public.orders": _make_table("orders", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "customer_id", "type": "integer"},
                {"name": "total", "type": "numeric"},
            ]),
            "public.customers": _make_table("customers", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "name", "type": "varchar"},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert len(joins) >= 1
        customer_join = next((j for j in joins if j["from_column"] == "customer_id"), None)
        assert customer_join is not None
        assert customer_join["to_table"] == "customers"
        assert customer_join["to_column"] == "id"

    def test_product_id_to_products(self):
        """product_id should join to products.id."""
        schema = {
            "public.order_items": _make_table("order_items", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "product_id", "type": "integer"},
            ]),
            "public.products": _make_table("products", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "name", "type": "varchar"},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        product_join = next((j for j in joins if j["from_column"] == "product_id"), None)
        assert product_join is not None
        assert product_join["to_table"] == "products"

    def test_no_self_join(self):
        """A table should not infer a join to itself via its own _id column."""
        schema = {
            "public.orders": _make_table("orders", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "order_id", "type": "integer"},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        self_joins = [j for j in joins if j["from_table"] == j["to_table"] == "orders"]
        assert len(self_joins) == 0


class TestPluralForms:
    """Test plural form matching for table names."""

    def test_category_id_to_categories(self):
        """category_id should match categories (y -> ies)."""
        schema = {
            "public.products": _make_table("products", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "category_id", "type": "integer"},
            ]),
            "public.categories": _make_table("categories", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "name", "type": "varchar"},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        cat_join = next((j for j in joins if j["from_column"] == "category_id"), None)
        assert cat_join is not None
        assert cat_join["to_table"] == "categories"

    def test_address_id_to_addresses(self):
        """address_id should match addresses (s suffix)."""
        schema = {
            "public.users": _make_table("users", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "address_id", "type": "integer"},
            ]),
            "public.addresses": _make_table("addresses", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        addr_join = next((j for j in joins if j["from_column"] == "address_id"), None)
        assert addr_join is not None


class TestExistingFKsSkipped:
    """Test that existing explicit FKs are not duplicated."""

    def test_explicit_fk_not_duplicated(self):
        """Tables with explicit FK declarations should not get duplicate inferred FKs."""
        schema = {
            "public.orders": _make_table("orders", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "customer_id", "type": "integer"},
            ], foreign_keys=[
                {"column": "customer_id", "references_table": "customers", "references_column": "id"},
            ]),
            "public.customers": _make_table("customers", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        inferred_customer = [j for j in joins if j["from_column"] == "customer_id" and j["from_table"] == "orders"]
        assert len(inferred_customer) == 0


class TestSharedColumnJoins:
    """Test shared column name joins (bridge tables)."""

    def test_shared_column_detected(self):
        """Two tables sharing a _id column should get inferred joins to the target."""
        schema = {
            "public.orders": _make_table("orders", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "product_id", "type": "integer"},
            ]),
            "public.returns": _make_table("returns", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "product_id", "type": "integer"},
            ]),
            "public.products": _make_table("products", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        # Both orders and returns should have joins to products via product_id
        assert len(joins) >= 2


class TestEdgeCases:
    """Test edge cases and robustness."""

    def test_empty_schema(self):
        """Empty schema should return no joins."""
        assert _infer_implicit_joins({}) == []

    def test_single_table(self):
        """Single table should return no joins."""
        schema = {
            "public.users": _make_table("users", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert len(joins) == 0

    def test_no_id_columns(self):
        """Tables without id/PK columns should not crash."""
        schema = {
            "public.events": _make_table("events", columns=[
                {"name": "event_type", "type": "varchar"},
                {"name": "user_id", "type": "integer"},
            ]),
            "public.users": _make_table("users", columns=[
                {"name": "name", "type": "varchar"},
            ]),
        }
        # Should not crash
        _infer_implicit_joins(schema)

    def test_inferred_flag_set(self):
        """All inferred joins should have inferred=True."""
        schema = {
            "public.orders": _make_table("orders", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "customer_id", "type": "integer"},
            ]),
            "public.customers": _make_table("customers", columns=[
                {"name": "id", "type": "integer", "primary_key": True},
            ]),
        }
        joins = _infer_implicit_joins(schema)
        for j in joins:
            assert j["inferred"] is True
