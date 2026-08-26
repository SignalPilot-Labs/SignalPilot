"""Regression tests for whitespace/comment evasion bypass of _DENIED_PREFIX_RE.

These tests verify that tab, newline, and block-comment separators between
SQL tokens do not allow privileged-object statements to bypass the validator.
Both Layer A (normalization) and Layer B (AST kind-check / Command-node regex)
are exercised.
"""

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


class TestPrefixBypassBlocked:
    """Each payload must be blocked — bypasses proven on the pre-fix code."""

    def test_create_role_double_space(self) -> None:
        result = validate_dbt_statement("CREATE  ROLE evil", claims=_claims())
        assert result.blocked

    def test_create_role_tab(self) -> None:
        result = validate_dbt_statement("CREATE\tROLE evil", claims=_claims())
        assert result.blocked

    def test_create_role_newline(self) -> None:
        result = validate_dbt_statement("CREATE\nROLE evil", claims=_claims())
        assert result.blocked

    def test_create_role_block_comment(self) -> None:
        result = validate_dbt_statement("CREATE/*c*/ROLE evil", claims=_claims())
        assert result.blocked

    def test_create_role_empty_block_comment(self) -> None:
        result = validate_dbt_statement("CREATE/**/ROLE evil", claims=_claims())
        assert result.blocked

    def test_create_role_line_comment_newline(self) -> None:
        # Line comment stripped → "create  role evil" → normalized → "create role evil"
        result = validate_dbt_statement("create -- inline\nrole evil", claims=_claims())
        assert result.blocked

    def test_drop_user_double_space(self) -> None:
        result = validate_dbt_statement("DROP  USER bob", claims=_claims())
        assert result.blocked

    def test_alter_user_tab(self) -> None:
        result = validate_dbt_statement("ALTER\tUSER alice SUPERUSER", claims=_claims())
        assert result.blocked

    def test_create_extension_double_space(self) -> None:
        result = validate_dbt_statement("CREATE  EXTENSION pglogical", claims=_claims())
        assert result.blocked

    def test_create_database_block_comment(self) -> None:
        result = validate_dbt_statement("CREATE/*x*/DATABASE pwn", claims=_claims())
        assert result.blocked

    def test_drop_tablespace_double_space(self) -> None:
        result = validate_dbt_statement("DROP  TABLESPACE ts", claims=_claims())
        assert result.blocked

    def test_create_language_double_space_rce(self) -> None:
        result = validate_dbt_statement("CREATE  LANGUAGE plpython3u", claims=_claims())
        assert result.blocked

    def test_create_function_double_space_regression(self) -> None:
        # Already blocked pre-fix — must remain blocked.
        result = validate_dbt_statement(
            "CREATE  FUNCTION f() RETURNS void AS $$ $$ LANGUAGE sql",
            claims=_claims(),
        )
        assert result.blocked

    def test_create_role_after_semicolon(self) -> None:
        result = validate_dbt_statement("; CREATE  ROLE evil", claims=_claims())
        assert result.blocked

    def test_create_role_nested_block_comment_layer_b(self) -> None:
        # Postgres nested block comment: /* /* x */ */ — Layer A's non-recursive
        # regex leaves "CREATE*/ ROLE evil" which won't match the prefix.
        # Layer B (AST kind-check / Command-node regex) must catch this.
        result = validate_dbt_statement("CREATE/*/*x*/*/ROLE evil", claims=_claims())
        assert result.blocked


class TestPrefixBypassNegativeControls:
    """Statements that must NOT be blocked (regression / false-positive guard)."""

    def test_select_with_create_role_in_comment_not_blocked(self) -> None:
        # The comment is stripped; what remains is "SELECT 1  FROM x" — safe.
        result = validate_dbt_statement(
            "SELECT 1 -- create role in a comment\nFROM x",
            claims=_claims(),
        )
        assert not result.blocked

    def test_insert_with_create_role_in_string_literal_not_blocked(self) -> None:
        # The payload is inside a string literal — prefix boundary (?:^|[\s;])
        # won't match because the opening quote is not whitespace or semicolon.
        result = validate_dbt_statement(
            "INSERT INTO t (name) VALUES ('CREATE ROLE evil')",
            claims=_claims(),
        )
        assert not result.blocked

    def test_create_table_not_blocked(self) -> None:
        result = validate_dbt_statement("CREATE TABLE foo (id int)", claims=_claims())
        assert not result.blocked


class TestGrantRevokeAndSetLocalBypasses:
    """Tests for V1–V4 security bypasses found in Round 2 security review.

    V1: GRANT <role> TO <role>  — role-membership grant (Command node, not exp.Grant)
    V2: REVOKE <role> FROM <role> — same root cause
    V3: SET LOCAL ROLE admin — LOCAL qualifier sits between SET and ROLE
    V4: SET LOCAL SESSION AUTHORIZATION admin — same qualifier issue
    """

    # ── V1: GRANT role membership ─────────────────────────────────────────────

    def test_grant_role_to_role_blocked(self) -> None:
        result = validate_dbt_statement("GRANT admin TO evil", claims=_claims())
        assert result.blocked
        assert result.block_reason is not None

    def test_grant_role_to_role_original_sql_preserved(self) -> None:
        original = "GRANT admin TO evil"
        result = validate_dbt_statement(original, claims=_claims())
        assert result.blocked
        assert result.sql == original

    # ── V2: REVOKE role membership ────────────────────────────────────────────

    def test_revoke_role_from_role_blocked(self) -> None:
        result = validate_dbt_statement("REVOKE admin FROM evil", claims=_claims())
        assert result.blocked
        assert result.block_reason is not None

    def test_revoke_role_from_role_original_sql_preserved(self) -> None:
        original = "REVOKE admin FROM evil"
        result = validate_dbt_statement(original, claims=_claims())
        assert result.blocked
        assert result.sql == original

    # ── V3: SET LOCAL ROLE ────────────────────────────────────────────────────

    def test_set_local_role_blocked(self) -> None:
        result = validate_dbt_statement("SET LOCAL ROLE admin", claims=_claims())
        assert result.blocked
        assert result.block_reason == "privilege_escalation_blocked"

    def test_set_role_still_blocked(self) -> None:
        # Regression: plain SET ROLE must still be blocked.
        result = validate_dbt_statement("SET ROLE admin", claims=_claims())
        assert result.blocked
        assert result.block_reason == "privilege_escalation_blocked"

    # ── V4: SET LOCAL SESSION AUTHORIZATION ───────────────────────────────────

    def test_set_local_session_authorization_blocked(self) -> None:
        result = validate_dbt_statement("SET LOCAL SESSION AUTHORIZATION admin", claims=_claims())
        assert result.blocked
        assert result.block_reason == "privilege_escalation_blocked"

    def test_set_session_authorization_still_blocked(self) -> None:
        # Regression: plain SET SESSION AUTHORIZATION must still be blocked.
        result = validate_dbt_statement("SET SESSION AUTHORIZATION admin", claims=_claims())
        assert result.blocked
        assert result.block_reason == "privilege_escalation_blocked"

    # ── V5: SET SESSION ROLE / SET SESSION SESSION AUTHORIZATION ──────────────
    # PG accepts SESSION as an alternative qualifier to LOCAL: `SET SESSION ROLE`
    # is identical to `SET ROLE`. Same for SESSION AUTHORIZATION.

    def test_set_session_role_blocked(self) -> None:
        result = validate_dbt_statement("SET SESSION ROLE admin", claims=_claims())
        assert result.blocked
        assert result.block_reason == "privilege_escalation_blocked"

    def test_set_session_session_authorization_blocked(self) -> None:
        result = validate_dbt_statement(
            "SET SESSION SESSION AUTHORIZATION admin", claims=_claims()
        )
        assert result.blocked
        assert result.block_reason == "privilege_escalation_blocked"


class TestGrantRevokeSetLocalNegativeControls:
    """False-positive guard — these must NOT be blocked."""

    def test_set_search_path_allowed(self) -> None:
        result = validate_dbt_statement("SET search_path = public", claims=_claims())
        assert not result.blocked

    def test_set_local_statement_timeout_allowed(self) -> None:
        result = validate_dbt_statement("SET LOCAL statement_timeout = 5000", claims=_claims())
        assert not result.blocked

    def test_set_work_mem_allowed(self) -> None:
        result = validate_dbt_statement("SET work_mem = '4MB'", claims=_claims())
        assert not result.blocked


class TestValidatedStatementSqlUnchanged:
    """ValidatedStatement.sql must always be byte-identical to the original input."""

    def test_sql_field_is_original_not_normalized_for_allowed(self) -> None:
        original = "SELECT\t1\n-- comment\nFROM x"
        result = validate_dbt_statement(original, claims=_claims())
        assert result.sql == original

    def test_sql_field_is_original_not_normalized_for_blocked(self) -> None:
        original = "CREATE\tROLE evil"
        result = validate_dbt_statement(original, claims=_claims())
        assert result.blocked
        assert result.sql == original

    def test_sql_field_is_original_for_block_comment_payload(self) -> None:
        original = "CREATE/*c*/ROLE evil"
        result = validate_dbt_statement(original, claims=_claims())
        assert result.blocked
        assert result.sql == original
