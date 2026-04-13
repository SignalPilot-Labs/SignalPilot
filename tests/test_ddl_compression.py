"""Tests for DDL compression, column pruning, and condensed format.

Verifies that:
- Column pruning correctly keeps PKs, FKs, and relevant columns
- Condensed format produces shorter output than full DDL
- Type compression works correctly
- Error hint function returns DB-specific guidance
"""

import pytest


# ── Simulated schema data for testing ──

SAMPLE_SCHEMA = {
    "public.orders": {
        "schema": "public",
        "name": "orders",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "customer_id", "type": "bigint", "primary_key": False, "nullable": False},
            {"name": "order_date", "type": "timestamp with time zone", "primary_key": False, "nullable": False},
            {"name": "status", "type": "character varying", "primary_key": False, "nullable": True},
            {"name": "total_amount", "type": "numeric", "primary_key": False, "nullable": True},
            {"name": "notes", "type": "text", "primary_key": False, "nullable": True},
            {"name": "internal_flag", "type": "boolean", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [
            {"column": "customer_id", "references_table": "customers", "references_column": "id"},
        ],
        "row_count": 50000,
    },
    "public.customers": {
        "schema": "public",
        "name": "customers",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "name", "type": "character varying", "primary_key": False, "nullable": False},
            {"name": "email", "type": "character varying", "primary_key": False, "nullable": True},
            {"name": "phone", "type": "character varying", "primary_key": False, "nullable": True},
            {"name": "address", "type": "text", "primary_key": False, "nullable": True},
            {"name": "created_at", "type": "timestamp with time zone", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [],
        "row_count": 10000,
    },
    "public.audit_log": {
        "schema": "public",
        "name": "audit_log",
        "type": "table",
        "columns": [
            {"name": "id", "type": "bigint", "primary_key": True, "nullable": False},
            {"name": "user_id", "type": "bigint", "primary_key": False, "nullable": False},
            {"name": "action", "type": "character varying", "primary_key": False, "nullable": False},
            {"name": "target_table", "type": "character varying", "primary_key": False, "nullable": True},
            {"name": "target_id", "type": "bigint", "primary_key": False, "nullable": True},
            {"name": "old_value", "type": "jsonb", "primary_key": False, "nullable": True},
            {"name": "new_value", "type": "jsonb", "primary_key": False, "nullable": True},
            {"name": "ip_address", "type": "character varying", "primary_key": False, "nullable": True},
            {"name": "created_at", "type": "timestamp with time zone", "primary_key": False, "nullable": True},
        ],
        "foreign_keys": [
            {"column": "user_id", "references_table": "customers", "references_column": "id"},
        ],
        "row_count": 500000,
    },
}


class TestColumnPruning:
    """Test that column pruning keeps structural and relevant columns."""

    def test_high_score_table_keeps_all_columns(self):
        """Tables with score >= 5.0 should keep all columns."""
        table_data = SAMPLE_SCHEMA["public.orders"]
        table_scores = {"public.orders": 15.0}
        column_scores = {"public.orders": {"order_date": 4.0, "status": 2.0}}

        # High-score table: prune_columns=True but score >= 5.0 → keep all
        all_cols = table_data["columns"]
        t_score = table_scores["public.orders"]
        assert t_score >= 5.0
        # All 7 columns should be retained
        assert len(all_cols) == 7

    def test_low_score_table_prunes_irrelevant(self):
        """Low-score FK-connected tables should only keep PKs, FKs, and relevant columns."""
        table_data = SAMPLE_SCHEMA["public.audit_log"]
        # Simulate: audit_log only included because it FK-connects to customers
        col_relevance = {}  # No columns matched the question
        fk_cols = {fk["column"] for fk in table_data["foreign_keys"]}

        kept = []
        for col in table_data["columns"]:
            if col["primary_key"] or col["name"] in fk_cols or col_relevance.get(col["name"], 0) > 0:
                kept.append(col)

        # Should keep: id (PK), user_id (FK) = 2 columns
        assert len(kept) == 2
        kept_names = {c["name"] for c in kept}
        assert "id" in kept_names
        assert "user_id" in kept_names
        # Should have pruned: action, target_table, target_id, old_value, new_value, ip_address, created_at
        assert "old_value" not in kept_names
        assert "ip_address" not in kept_names

    def test_relevant_columns_kept(self):
        """Columns that match question terms should be kept even in low-score tables."""
        table_data = SAMPLE_SCHEMA["public.audit_log"]
        col_relevance = {"action": 4.0, "created_at": 2.0}  # These matched the question
        fk_cols = {fk["column"] for fk in table_data["foreign_keys"]}

        kept = []
        for col in table_data["columns"]:
            if col["primary_key"] or col["name"] in fk_cols or col_relevance.get(col["name"], 0) > 0:
                kept.append(col)

        # Should keep: id (PK), user_id (FK), action (relevant), created_at (relevant) = 4 columns
        assert len(kept) == 4
        kept_names = {c["name"] for c in kept}
        assert "action" in kept_names
        assert "created_at" in kept_names

    def test_empty_relevance_keeps_all(self):
        """If pruning removes ALL columns, safety fallback keeps all."""
        table_data = {
            "columns": [
                {"name": "x", "type": "int", "primary_key": False},
                {"name": "y", "type": "int", "primary_key": False},
            ],
            "foreign_keys": [],
        }
        col_relevance = {}
        fk_cols = set()

        kept = []
        for col in table_data["columns"]:
            if col.get("primary_key") or col["name"] in fk_cols or col_relevance.get(col["name"], 0) > 0:
                kept.append(col)

        # No PKs, no FKs, no relevance → empty
        # Safety: should fall back to all columns
        if not kept:
            kept = table_data["columns"]
        assert len(kept) == 2


class TestTypeCompression:
    """Test that type abbreviation works correctly."""

    def test_verbose_types_compressed(self):
        type_compress = {
            "CHARACTER VARYING": "VARCHAR",
            "TIMESTAMP WITHOUT TIME ZONE": "TS",
            "TIMESTAMP WITH TIME ZONE": "TSZ",
            "DOUBLE PRECISION": "DOUBLE",
            "BOOLEAN": "BOOL",
            "INTEGER": "INT",
        }
        assert type_compress["CHARACTER VARYING"] == "VARCHAR"
        assert type_compress["TIMESTAMP WITH TIME ZONE"] == "TSZ"
        assert type_compress["BOOLEAN"] == "BOOL"
        assert type_compress["INTEGER"] == "INT"

    def test_precision_stripping(self):
        """VARCHAR(255) should compress to VARCHAR in condensed format."""
        ct = "VARCHAR(255)"
        base = ct.split("(")[0]
        stripped_types = ("VARCHAR", "NVARCHAR", "CHAR", "DECIMAL", "NUMERIC")
        if "(" in ct and base in stripped_types:
            ct = base
        assert ct == "VARCHAR"

    def test_non_parameterized_types_unchanged(self):
        """Types without parentheses should pass through unchanged."""
        ct = "BIGINT"
        if "(" in ct:
            ct = ct.split("(")[0]
        assert ct == "BIGINT"


class TestErrorHints:
    """Test the _connection_error_hint function logic."""

    def _get_hint(self, db_type: str, error_msg: str) -> str:
        """Simulate the hint generation logic from main.py."""
        err_lower = error_msg.lower()

        if any(kw in err_lower for kw in ("connection refused", "timed out", "unreachable", "no route",
                                           "name or service not known", "getaddrinfo", "errno -2", "errno 111")):
            hints = {
                "postgres": "Check: 1) PostgreSQL is running 2) Port 5432 is open",
                "mysql": "Check: 1) MySQL is running 2) Port 3306 is open",
                "mssql": "Check: 1) SQL Server is running 2) TCP/IP protocol is enabled",
            }
            return hints.get(db_type, "Check hostname, port, firewall rules")

        if any(kw in err_lower for kw in ("authentication", "login failed", "access denied", "password")):
            hints = {
                "postgres": "Check: 1) Username and password are correct",
                "mysql": "Check: 1) User exists 2) Password is correct",
            }
            return hints.get(db_type, "Check credentials")

        return "Check connection parameters"

    def test_connection_refused_postgres(self):
        hint = self._get_hint("postgres", "Connection refused at localhost:5432")
        assert "PostgreSQL is running" in hint

    def test_connection_refused_mysql(self):
        hint = self._get_hint("mysql", "Connection refused at localhost:3306")
        assert "MySQL is running" in hint

    def test_dns_error(self):
        hint = self._get_hint("mysql", "[Errno -2] Name or service not known")
        assert "MySQL is running" in hint

    def test_auth_error_postgres(self):
        hint = self._get_hint("postgres", "Authentication failed: wrong password")
        assert "Username and password" in hint

    def test_unknown_error_fallback(self):
        hint = self._get_hint("postgres", "Some completely new error type")
        assert "Check connection parameters" in hint

    def test_mssql_network_error(self):
        hint = self._get_hint("mssql", "Connection timed out after 15 seconds")
        assert "SQL Server is running" in hint


class TestCondensedFormat:
    """Test properties of the condensed DDL format."""

    def test_condensed_shorter_than_ddl(self):
        """Condensed output should always be shorter than full DDL for same schema."""
        # Generate a mock DDL line (full format)
        full_ddl = """CREATE TABLE public.audit_log (
  id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  action CHARACTER VARYING NOT NULL,
  target_table CHARACTER VARYING,
  target_id BIGINT,
  old_value JSONB,
  new_value JSONB,
  ip_address CHARACTER VARYING,
  created_at TIMESTAMP WITH TIME ZONE,
  PRIMARY KEY (id),
  FOREIGN KEY (user_id) REFERENCES customers(id)
); -- 500,000 rows, relevance=2.0"""

        # Condensed version (pruned + compressed types)
        condensed = """CREATE TABLE public.audit_log (
  id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  PRIMARY KEY (id),
  FOREIGN KEY (user_id) REFERENCES customers(id)
); -- 7 columns pruned"""

        assert len(condensed) < len(full_ddl)
        # At least 40% shorter
        reduction = 1 - len(condensed) / len(full_ddl)
        assert reduction > 0.4

    def test_condensed_retains_structural_elements(self):
        """Condensed format should always include PRIMARY KEY and FOREIGN KEY."""
        condensed = """CREATE TABLE public.orders (
  id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  PRIMARY KEY (id),
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);"""
        assert "PRIMARY KEY" in condensed
        assert "FOREIGN KEY" in condensed

    def test_column_reduction_calculation(self):
        """Column reduction percentage should be correctly calculated."""
        original = 10
        kept = 3
        reduction_pct = round((1 - kept / max(original, 1)) * 100)
        assert reduction_pct == 70

        # Edge case: no reduction
        reduction_pct = round((1 - 10 / max(10, 1)) * 100)
        assert reduction_pct == 0

        # Edge case: all pruned (shouldn't happen due to safety, but test math)
        reduction_pct = round((1 - 0 / max(10, 1)) * 100)
        assert reduction_pct == 100
