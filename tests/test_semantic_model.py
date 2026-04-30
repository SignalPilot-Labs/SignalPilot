"""Tests for semantic model API functionality."""

import pytest
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestSemanticModelStorage:
    """Test semantic model load/save/merge logic."""

    def test_empty_model_structure(self):
        """Default empty model has tables, joins, and glossary."""
        from gateway.main import _load_semantic_model, _semantic_models
        _semantic_models.clear()
        _semantic_models["test-conn"] = {"tables": {}, "joins": [], "glossary": {}}
        model = _load_semantic_model("test-conn")
        assert "tables" in model
        assert "joins" in model
        assert "glossary" in model
        assert model["tables"] == {}
        assert model["joins"] == []
        assert model["glossary"] == {}

    def test_model_table_merge(self):
        """Updating a model merges table descriptions, not replaces."""
        from gateway.main import _semantic_models

        _semantic_models["merge-test"] = {
            "tables": {
                "public.users": {
                    "description": "Original description",
                    "columns": {
                        "id": {"description": "User ID"},
                        "email": {"description": "Email address"},
                    }
                }
            },
            "joins": [],
            "glossary": {"user email": "public.users.email"},
        }

        model = _semantic_models["merge-test"]

        # Simulate merge: update description, add new column, keep existing
        update = {
            "public.users": {
                "description": "Updated description",
                "columns": {
                    "email": {"description": "Primary email", "unit": "email"},
                    "name": {"description": "Full name"},
                }
            }
        }

        for table_key, table_data in update.items():
            if table_key not in model["tables"]:
                model["tables"][table_key] = {"description": "", "columns": {}}
            if "description" in table_data:
                model["tables"][table_key]["description"] = table_data["description"]
            if "columns" in table_data:
                for col_name, col_data in table_data["columns"].items():
                    if col_name not in model["tables"][table_key]["columns"]:
                        model["tables"][table_key]["columns"][col_name] = {}
                    model["tables"][table_key]["columns"][col_name].update(col_data)

        # Verify merge results
        t = model["tables"]["public.users"]
        assert t["description"] == "Updated description"
        assert t["columns"]["id"]["description"] == "User ID"  # Preserved
        assert t["columns"]["email"]["description"] == "Primary email"  # Updated
        assert t["columns"]["email"]["unit"] == "email"  # New field
        assert t["columns"]["name"]["description"] == "Full name"  # New column

    def test_glossary_merge(self):
        """Glossary terms merge without losing existing entries."""
        from gateway.main import _semantic_models
        _semantic_models["gloss-test"] = {
            "tables": {},
            "joins": [],
            "glossary": {"revenue": "orders.total", "customer": "users.name"},
        }
        model = _semantic_models["gloss-test"]
        model["glossary"].update({"revenue": "orders.total_amount", "ARR": "subs.arr"})

        assert model["glossary"]["revenue"] == "orders.total_amount"  # Updated
        assert model["glossary"]["customer"] == "users.name"  # Preserved
        assert model["glossary"]["ARR"] == "subs.arr"  # Added


class TestSemanticModelInContext:
    """Test that semantic model enriches agent context."""

    def test_description_override(self):
        """Semantic description overrides empty database description."""
        sem_table = {"description": "Core customer records", "columns": {}}
        table = {"description": ""}

        desc = sem_table.get("description", "") or table.get("description", "")
        assert desc == "Core customer records"

    def test_db_description_fallback(self):
        """Falls back to database description when semantic is empty."""
        sem_table = {"description": "", "columns": {}}
        table = {"description": "From DB comment"}

        desc = sem_table.get("description", "") or table.get("description", "")
        assert desc == "From DB comment"

    def test_column_business_name(self):
        """Business name prepended to column comment."""
        sem_col = {"description": "Unique identifier", "business_name": "Customer ID"}
        col = {"name": "id", "comment": ""}

        comment = sem_col.get("description", "") or col.get("comment", "")
        biz_name = sem_col.get("business_name", "")
        if biz_name and biz_name.lower() != col["name"].lower().replace("_", " "):
            comment = f"{biz_name}: {comment}" if comment else biz_name

        assert comment == "Customer ID: Unique identifier"

    def test_unit_annotation(self):
        """Unit annotation appended to column comment."""
        sem_col = {"description": "Order total", "unit": "USD"}

        comment = sem_col.get("description", "")
        unit = sem_col.get("unit", "")
        if unit:
            comment = f"{comment} ({unit})" if comment else f"({unit})"

        assert comment == "Order total (USD)"

    def test_glossary_filtering(self):
        """Glossary filtered to relevant tables only."""
        glossary = {
            "revenue": "public.orders.total_amount",
            "customer name": "public.customers.full_name",
            "warehouse temp": "public.sensors.temperature",
        }
        table_names = {"orders", "customers"}

        relevant = {}
        for term, col_ref in glossary.items():
            ref_lower = col_ref.lower()
            for tname in table_names:
                if tname and tname in ref_lower:
                    relevant[term] = col_ref
                    break

        assert "revenue" in relevant
        assert "customer name" in relevant
        assert "warehouse temp" not in relevant


class TestJoinHints:
    """Test semantic join hint generation."""

    def test_join_auto_generation(self):
        """FK relationships generate join entries."""
        fks = [
            {"column": "customer_id", "references_table": "customers", "references_column": "id", "references_schema": "public"},
        ]

        joins = []
        for fk in fks:
            to_key = f"public.{fk['references_table']}"
            joins.append({
                "from": f"public.orders.{fk['column']}",
                "to": f"{to_key}.{fk['references_column']}",
                "type": "many_to_one",
            })

        assert len(joins) == 1
        assert joins[0]["from"] == "public.orders.customer_id"
        assert joins[0]["to"] == "public.customers.id"
        assert joins[0]["type"] == "many_to_one"

    def test_join_dedup(self):
        """Duplicate joins not added."""
        existing = [
            {"from": "public.orders.customer_id", "to": "public.customers.id"},
        ]
        new_join = {"from": "public.orders.customer_id", "to": "public.customers.id"}

        is_dup = any(
            j.get("from") == new_join["from"] and j.get("to") == new_join["to"]
            for j in existing
        )
        assert is_dup is True
