"""Tests for schema annotations — YAML loading, PII suggestion, skeleton generation."""

import pytest

from gateway.governance.annotations import (
    ColumnAnnotation,
    SchemaAnnotations,
    TableAnnotation,
    _parse_annotation_file,
    _suggest_pii_rule,
    generate_skeleton,
)


class TestPIISuggestion:
    """Test automatic PII rule suggestions from column names."""

    def test_email_suggests_hash(self):
        assert _suggest_pii_rule("email") == "hash"
        assert _suggest_pii_rule("user_email") == "hash"
        assert _suggest_pii_rule("EMAIL_ADDRESS") == "hash"

    def test_ssn_suggests_mask(self):
        assert _suggest_pii_rule("ssn") == "mask"
        assert _suggest_pii_rule("social_security_number") == "mask"

    def test_phone_suggests_mask(self):
        assert _suggest_pii_rule("phone") == "mask"
        assert _suggest_pii_rule("mobile_number") == "mask"

    def test_password_suggests_drop(self):
        assert _suggest_pii_rule("password") == "drop"
        assert _suggest_pii_rule("password_hash") == "drop"

    def test_credit_card_suggests_drop(self):
        assert _suggest_pii_rule("credit_card_number") == "drop"
        assert _suggest_pii_rule("card_number") == "drop"

    def test_name_suggests_mask(self):
        assert _suggest_pii_rule("first_name") == "mask"
        assert _suggest_pii_rule("last_name") == "mask"

    def test_generic_column_no_suggestion(self):
        assert _suggest_pii_rule("id") is None
        assert _suggest_pii_rule("created_at") is None
        assert _suggest_pii_rule("status") is None
        assert _suggest_pii_rule("amount") is None


class TestSchemaAnnotations:
    """Test SchemaAnnotations dataclass operations."""

    def test_blocked_tables(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={
                "users": TableAnnotation(blocked=False),
                "secrets": TableAnnotation(blocked=True),
                "passwords": TableAnnotation(blocked=True),
            },
        )
        assert set(ann.blocked_tables) == {"secrets", "passwords"}

    def test_pii_columns(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={
                "users": TableAnnotation(
                    columns={
                        "email": ColumnAnnotation(pii="hash"),
                        "ssn": ColumnAnnotation(pii="mask"),
                        "name": ColumnAnnotation(),  # No PII
                    }
                ),
            },
        )
        assert ann.pii_columns == {"email": "hash", "ssn": "mask"}

    def test_get_table_case_insensitive(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={"Users": TableAnnotation(description="User table")},
        )
        assert ann.get_table("users") is not None
        assert ann.get_table("USERS") is not None
        assert ann.get_table("nonexistent") is None

    def test_to_dict(self):
        ann = SchemaAnnotations(
            connection_name="test",
            tables={
                "users": TableAnnotation(
                    description="User accounts",
                    blocked=False,
                    columns={
                        "email": ColumnAnnotation(pii="hash", description="Primary email"),
                    },
                ),
            },
        )
        d = ann.to_dict()
        assert d["connection_name"] == "test"
        assert d["table_count"] == 1
        assert "users" in d["tables"]
        assert d["tables"]["users"]["description"] == "User accounts"


class TestSkeletonGeneration:
    """Test starter schema.yml generation."""

    def test_generate_from_schema(self):
        schema = {
            "public.users": {
                "name": "users",
                "schema": "public",
                "columns": [
                    {"name": "id", "type": "integer", "nullable": False},
                    {"name": "email", "type": "text", "nullable": False},
                    {"name": "phone", "type": "text", "nullable": True},
                    {"name": "created_at", "type": "timestamp", "nullable": True},
                ],
            },
        }
        result = generate_skeleton(schema, "prod-analytics")
        assert "prod-analytics" in result
        assert "users:" in result
        assert "email:" in result
        assert "pii: hash" in result  # email should get hash suggestion
        assert "pii: mask" in result  # phone should get mask suggestion

    def test_empty_schema(self):
        result = generate_skeleton({}, "empty-db")
        assert "empty-db" in result
        assert "tables:" in result
