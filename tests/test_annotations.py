"""Tests for schema annotations — Feature #16 (YAML sidecar governance)."""

import tempfile
import os
from pathlib import Path

import pytest

from signalpilot.gateway.gateway.governance.annotations import (
    SchemaAnnotations,
    TableAnnotation,
    ColumnAnnotation,
    load_annotations,
    generate_skeleton,
)


class TestSchemaAnnotations:
    """Tests for the SchemaAnnotations dataclass."""

    def test_empty_annotations(self):
        ann = SchemaAnnotations(connection_name="test")
        assert ann.blocked_tables == []
        assert ann.pii_columns == {}

    def test_blocked_tables_property(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={
                "users": TableAnnotation(blocked=False),
                "secrets": TableAnnotation(blocked=True),
                "credentials": TableAnnotation(blocked=True),
            },
        )
        blocked = ann.blocked_tables
        assert "secrets" in blocked
        assert "credentials" in blocked
        assert "users" not in blocked

    def test_pii_columns_property(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={
                "users": TableAnnotation(
                    columns={
                        "email": ColumnAnnotation(pii="mask"),
                        "ssn": ColumnAnnotation(pii="hash"),
                        "name": ColumnAnnotation(),
                    }
                )
            },
        )
        pii = ann.pii_columns
        assert pii["email"] == "mask"
        assert pii["ssn"] == "hash"
        assert "name" not in pii

    def test_get_table_case_insensitive(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={"Users": TableAnnotation(description="User table")},
        )
        result = ann.get_table("users")
        assert result is not None
        assert result.description == "User table"

    def test_get_table_missing(self):
        ann = SchemaAnnotations(connection_name="test")
        assert ann.get_table("nonexistent") is None

    def test_to_dict(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={
                "users": TableAnnotation(
                    description="Users table",
                    owner="team-auth",
                    blocked=True,
                    columns={
                        "email": ColumnAnnotation(pii="mask", description="Email"),
                    },
                )
            },
        )
        d = ann.to_dict()
        assert d["connection_name"] == "test"
        assert d["table_count"] == 1
        assert "users" in d["blocked_tables"]
        assert d["pii_columns"]["email"] == "mask"
        assert d["tables"]["users"]["owner"] == "team-auth"


class TestLoadAnnotations:
    """Tests for load_annotations() YAML loading."""

    def test_missing_file_returns_empty(self, tmp_path):
        os.environ["SP_DATA_DIR"] = str(tmp_path)
        try:
            ann = load_annotations("nonexistent")
            assert ann.connection_name == "nonexistent"
            assert len(ann.tables) == 0
        finally:
            os.environ.pop("SP_DATA_DIR", None)

    def test_load_from_connection_file(self, tmp_path):
        """Test loading from annotations/{connection_name}.yml"""
        pytest.importorskip("yaml")

        ann_dir = tmp_path / "annotations"
        ann_dir.mkdir()
        (ann_dir / "mydb.yml").write_text(
            """
tables:
  users:
    description: "User accounts"
    owner: "auth-team"
    blocked: false
    columns:
      email:
        description: "User email"
        pii: mask
  secrets:
    blocked: true
"""
        )

        os.environ["SP_DATA_DIR"] = str(tmp_path)
        try:
            ann = load_annotations("mydb")
            assert "users" in ann.tables
            assert "secrets" in ann.tables
            assert ann.tables["secrets"].blocked is True
            assert ann.tables["users"].columns["email"].pii == "mask"
            assert "secrets" in ann.blocked_tables
            assert "users" not in ann.blocked_tables
        finally:
            os.environ.pop("SP_DATA_DIR", None)

    def test_load_pii_annotations(self, tmp_path):
        """Test PII column detection from annotations."""
        pytest.importorskip("yaml")

        ann_dir = tmp_path / "annotations"
        ann_dir.mkdir()
        (ann_dir / "prod.yml").write_text(
            """
tables:
  customers:
    columns:
      ssn:
        pii: hash
      password:
        pii: drop
      phone:
        pii: mask
"""
        )

        os.environ["SP_DATA_DIR"] = str(tmp_path)
        try:
            ann = load_annotations("prod")
            pii = ann.pii_columns
            assert pii["ssn"] == "hash"
            assert pii["password"] == "drop"
            assert pii["phone"] == "mask"
        finally:
            os.environ.pop("SP_DATA_DIR", None)


class TestGenerateSkeleton:
    """Tests for generate_skeleton() — Feature #29."""

    def test_generates_yaml(self):
        schema = {
            "public.users": {
                "name": "users",
                "schema": "public",
                "columns": [
                    {"name": "id", "type": "integer", "nullable": False},
                    {"name": "email", "type": "varchar", "nullable": True},
                    {"name": "password_hash", "type": "varchar", "nullable": False},
                ],
            }
        }
        result = generate_skeleton(schema, "my_db")
        assert "# Schema annotations for my_db" in result
        assert "users:" in result
        assert "email:" in result
        assert "password_hash:" in result
        # Should suggest PII rules
        assert "pii:" in result

    def test_empty_schema(self):
        result = generate_skeleton({}, "empty")
        assert "tables:" in result

    def test_multiple_tables(self):
        schema = {
            "orders": {
                "name": "orders",
                "columns": [{"name": "id", "type": "int"}],
            },
            "products": {
                "name": "products",
                "columns": [{"name": "sku", "type": "varchar"}],
            },
        }
        result = generate_skeleton(schema, "shop")
        assert "orders:" in result
        assert "products:" in result
