"""Tests for implicit join inference algorithm used for Spider2.0 join path discovery."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))

from gateway.main import _infer_implicit_joins


def _make_table(schema, name, columns, fks=None):
    """Helper to build a table dict for testing."""
    return {
        "schema": schema,
        "name": name,
        "columns": [
            {"name": c[0], "type": c[1], "primary_key": c[2] if len(c) > 2 else False}
            for c in columns
        ],
        "foreign_keys": fks or [],
    }


class TestImplicitJoinInference:
    """Test the _infer_implicit_joins function for Spider2.0 join discovery."""

    def test_basic_id_suffix_match(self):
        """customer_id → customers.id"""
        schema = {
            "public.orders": _make_table("public", "orders", [
                ("id", "int", True), ("customer_id", "int"), ("total", "decimal"),
            ]),
            "public.customers": _make_table("public", "customers", [
                ("id", "int", True), ("name", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert len(joins) >= 1
        j = joins[0]
        assert j["from_table"] == "orders"
        assert j["from_column"] == "customer_id"
        assert j["to_table"] == "customers"
        assert j["to_column"] == "id"
        assert j["inferred"] is True

    def test_singular_table_match(self):
        """user_id → user.id (singular table name)"""
        schema = {
            "public.posts": _make_table("public", "posts", [
                ("id", "int", True), ("user_id", "int"), ("title", "varchar"),
            ]),
            "public.user": _make_table("public", "user", [
                ("id", "int", True), ("email", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert any(j["from_column"] == "user_id" and j["to_table"] == "user" for j in joins)

    def test_no_duplicate_with_explicit_fks(self):
        """Don't infer a join that already exists as an explicit FK."""
        schema = {
            "public.orders": _make_table("public", "orders", [
                ("id", "int", True), ("customer_id", "int"),
            ], fks=[{
                "column": "customer_id",
                "references_schema": "public",
                "references_table": "customers",
                "references_column": "id",
            }]),
            "public.customers": _make_table("public", "customers", [
                ("id", "int", True), ("name", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        # Should not add any inferred joins since the FK already exists
        assert len(joins) == 0

    def test_no_self_reference(self):
        """Don't infer a self-join (e.g., orders.order_id → orders.id)."""
        schema = {
            "public.orders": _make_table("public", "orders", [
                ("id", "int", True), ("order_id", "int"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        # order_id → order table doesn't exist, so no join
        assert len(joins) == 0

    def test_camelcase_id_suffix(self):
        """customerId → customers.id (camelCase pattern)."""
        schema = {
            "public.orders": _make_table("public", "orders", [
                ("id", "int", True), ("customerId", "int"),
            ]),
            "public.customer": _make_table("public", "customer", [
                ("id", "int", True), ("name", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert any(j["from_column"] == "customerId" and j["to_table"] == "customer" for j in joins)

    def test_shared_column_pk_join(self):
        """Both tables have product_id, and one has it as PK → joinable."""
        schema = {
            "public.order_items": _make_table("public", "order_items", [
                ("id", "int", True), ("product_id", "int"), ("quantity", "int"),
            ]),
            "public.products": _make_table("public", "products", [
                ("product_id", "int", True), ("name", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert any(
            j["from_column"] == "product_id" and j["to_table"] == "products"
            for j in joins
        )

    def test_multiple_fk_columns(self):
        """Table with multiple FK-like columns should generate multiple joins."""
        schema = {
            "public.orders": _make_table("public", "orders", [
                ("id", "int", True), ("customer_id", "int"), ("product_id", "int"),
            ]),
            "public.customers": _make_table("public", "customers", [
                ("id", "int", True), ("name", "varchar"),
            ]),
            "public.products": _make_table("public", "products", [
                ("id", "int", True), ("name", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        from_cols = {j["from_column"] for j in joins if j["from_table"] == "orders"}
        assert "customer_id" in from_cols
        assert "product_id" in from_cols

    def test_category_ies_plural(self):
        """category_id → categories.id (irregular plural)."""
        schema = {
            "public.products": _make_table("public", "products", [
                ("id", "int", True), ("category_id", "int"),
            ]),
            "public.categories": _make_table("public", "categories", [
                ("id", "int", True), ("name", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert any(j["from_column"] == "category_id" and j["to_table"] == "categories" for j in joins)

    def test_empty_schema(self):
        """Empty schema should return empty list."""
        assert _infer_implicit_joins({}) == []

    def test_no_matches(self):
        """Tables with no matching patterns should return empty list."""
        schema = {
            "public.foo": _make_table("public", "foo", [
                ("id", "int", True), ("bar_baz", "varchar"),
            ]),
            "public.qux": _make_table("public", "qux", [
                ("id", "int", True), ("name", "varchar"),
            ]),
        }
        joins = _infer_implicit_joins(schema)
        assert len(joins) == 0
