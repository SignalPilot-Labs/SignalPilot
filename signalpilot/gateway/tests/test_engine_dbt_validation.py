"""Tests for validate_dbt_statement governance function."""

from __future__ import annotations

import uuid

import pytest

from gateway.dbt_proxy.tokens import RunTokenClaims
from gateway.engine.dbt_validation import ValidatedStatement, validate_dbt_statement


def _claims(connector: str = "my_db") -> RunTokenClaims:
    return RunTokenClaims(
        run_id=uuid.uuid4(),
        org_id="test-org",
        user_id="test-user",
        connector_name=connector,
        expires_at=9999999999.0,
    )


class TestDbtValidation:
    def test_select_allowed_kind_read(self) -> None:
        result = validate_dbt_statement("SELECT 1", claims=_claims())
        assert not result.blocked
        assert result.kind == "read"

    def test_create_table_as_select_allowed_kind_ddl(self) -> None:
        result = validate_dbt_statement("CREATE TABLE foo AS SELECT 1 AS id", claims=_claims())
        assert not result.blocked
        assert result.kind == "ddl"

    def test_insert_allowed_kind_write(self) -> None:
        result = validate_dbt_statement("INSERT INTO foo VALUES (1)", claims=_claims())
        assert not result.blocked
        assert result.kind == "write"

    def test_begin_commit_allowed_kind_tx(self) -> None:
        result = validate_dbt_statement("BEGIN", claims=_claims())
        assert not result.blocked
        result2 = validate_dbt_statement("COMMIT", claims=_claims())
        assert not result2.blocked

    def test_copy_blocked(self) -> None:
        result = validate_dbt_statement("COPY foo FROM '/etc/passwd'", claims=_claims())
        assert result.blocked
        assert result.block_reason == "copy_blocked"

    def test_grant_blocked(self) -> None:
        result = validate_dbt_statement("GRANT ALL ON foo TO bar", claims=_claims())
        assert result.blocked
        assert result.block_reason is not None

    def test_listen_blocked(self) -> None:
        result = validate_dbt_statement("LISTEN my_channel", claims=_claims())
        assert result.blocked

    def test_sql_too_long_blocked(self) -> None:
        # 1.5 MiB of SQL
        big_sql = "SELECT " + "a" * (1024 * 1024 + 600_000)
        result = validate_dbt_statement(big_sql, claims=_claims())
        assert result.blocked
        assert result.block_reason == "sql_too_long"

    def test_set_role_blocked(self) -> None:
        result = validate_dbt_statement("SET ROLE superuser", claims=_claims())
        assert result.blocked
        assert result.block_reason == "privilege_escalation_blocked"

    def test_create_extension_blocked(self) -> None:
        result = validate_dbt_statement("CREATE EXTENSION pg_stat_statements", claims=_claims())
        assert result.blocked
