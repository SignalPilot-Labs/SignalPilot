"""dbt-aware governance for proxy-forwarded SQL traffic.

This module provides validate_dbt_statement(), which governs the DDL/DML set
that dbt-postgres actually emits. It is distinct from validate_sql() (which is
read-only and used for direct interactive queries).

Connector-level isolation: schema-ownership is NOT enforced here. The connector's
DB credentials already scope write access to the tenant's schemas. The proxy
adds an allow/deny list on top. TODO(R7): add schema-allowlist enforcement once
connectors carry an allowed_schemas field.

The deny-list takes precedence over the allow-list. Every multi-statement string
is parsed into individual statements; if any single one is denied the whole
string is blocked.

Cap: 1 MiB total SQL string length (dbt compiled models can be large).

Security note: sqlglot is a HARD dependency of this module. If it is absent the
module raises ImportError at import time (fail closed — do not skip validation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import sqlglot
import sqlglot.expressions as exp

if TYPE_CHECKING:
    from ..dbt_proxy.tokens import RunTokenClaims

_SQL_MAX_BYTES = 1_048_576  # 1 MiB

# ─── Statement kind classification ───────────────────────────────────────────

_READ_TYPES: frozenset[str] = frozenset({
    "Select", "With", "Union", "Intersect", "Except", "Values", "Subquery",
})

_WRITE_TYPES: frozenset[str] = frozenset({
    "Insert", "Update", "Delete", "Merge", "Truncate",
})

_DDL_TYPES: frozenset[str] = frozenset({
    "Create", "Drop", "Alter", "Rename", "Comment",
})

_TX_TYPES: frozenset[str] = frozenset({
    "Transaction",  # BEGIN
    "Commit",
    "Rollback",
    "Savepoint",
    "ReleaseSavepoint",
    "Command",  # SET, SET LOCAL, SET SESSION AUTHORIZATION handled below
})

# ─── Denied statement node types (names that always block) ───────────────────

_DENIED_NODE_TYPES: frozenset[str] = frozenset({
    "Grant",
    "Revoke",
})

# ─── CREATE object-kind deny-list ────────────────────────────────────────────
# dbt-postgres emits CREATE TABLE / CREATE VIEW / CREATE SCHEMA / CREATE INDEX.
# Function/procedure/trigger/aggregate/operator/cast/extension/language/event
# trigger DDL is never emitted by standard dbt models and allows RCE or
# privilege escalation.

_DENIED_CREATE_KINDS: frozenset[str] = frozenset({
    "FUNCTION",
    "PROCEDURE",
    "TRIGGER",
    "AGGREGATE",
    "OPERATOR",
    "CAST",
    "EVENT TRIGGER",
    "LANGUAGE",
    "EXTENSION",
})

# ─── SQL keyword deny-list (checked via case-insensitive prefix on raw SQL) ──
# These are a fast pre-filter. The AST walk below is authoritative; these
# prefixes add defence-in-depth for statements sqlglot may mis-classify.

_DENIED_PREFIXES: tuple[str, ...] = (
    "copy ",
    "copy\t",
    "copy\n",
    "listen ",
    "notify ",
    "unlisten ",
    "do ",
    "do\t",
    "do\n",
    "do$$",
    "do $",
    "load ",
    "load\t",
    "create role",
    "drop role",
    "alter role",
    "create user",
    "drop user",
    "alter user",
    "create database",
    "drop database",
    "alter database",
    "create tablespace",
    "drop tablespace",
    "create extension",
    "drop extension",
    "create language",
    "drop language",
    "create function",
    "create procedure",
    "create trigger",
    "create aggregate",
    "create operator",
    "lock table",
    "lock\ttable",
    "reset role",
    "reset session",
    "security definer",
)

# SET commands that are always denied (privilege escalation)
_DENIED_SET_PATTERNS: tuple[str, ...] = (
    "set session authorization",
    "set role",
    "reset role",
    "reset session authorization",
)

# ─── Dangerous function deny-list (AST walk) ─────────────────────────────────
# These Postgres built-ins expose warehouse host filesystem, config, or network
# egress. Block any SELECT/expression that calls them regardless of context.

_DENIED_FUNCTION_NAMES: frozenset[str] = frozenset({
    "pg_read_server_files",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "dblink_connect",
    "dblink_disconnect",
    "dblink_open",
    "dblink_fetch",
    "dblink_close",
    "dblink_send_query",
    "dblink_get_result",
    "dblink_get_notify",
    "dblink_get_pkey",
    "dblink_build_sql_insert",
    "dblink_build_sql_delete",
    "dblink_build_sql_update",
    "current_setting",
    "set_config",
})


@dataclass
class ValidatedStatement:
    """Result of validate_dbt_statement().

    sql:          The original SQL string (never rewritten).
    kind:         Classification for audit logging.
    blocked:      True if the statement was denied.
    block_reason: Human-readable denial reason (None when not blocked).
    """

    sql: str
    kind: Literal["read", "write", "ddl", "tx", "admin"]
    blocked: bool
    block_reason: str | None


def validate_dbt_statement(sql: str, *, claims: RunTokenClaims) -> ValidatedStatement:
    """Governance for proxy-forwarded dbt traffic.

    Allows the DDL/DML set dbt-postgres actually emits; deny-lists destructive
    and cross-tenant operations.

    Connector-level isolation is provided by the connector's DB credentials.
    Schema-ownership enforcement is deferred to R7 (TODO R7: add schema allowlist).

    Args:
        sql:    The raw SQL string from the client.
        claims: The RunTokenClaims of the authenticated session (used for
                future schema-allowlist enforcement in R7).

    Returns:
        ValidatedStatement with blocked=True and a block_reason if the SQL
        is not permitted, or blocked=False when execution should proceed.
    """
    if len(sql.encode("utf-8")) > _SQL_MAX_BYTES:
        return ValidatedStatement(
            sql=sql,
            kind="admin",
            blocked=True,
            block_reason="sql_too_long",
        )

    # Deny-list: quick case-insensitive prefix check on the normalised SQL.
    # This is defence-in-depth; the AST walk below is authoritative.
    sql_lower = sql.strip().lower()
    for prefix in _DENIED_PREFIXES:
        if sql_lower.startswith(prefix) or f" {prefix}" in sql_lower or f"\n{prefix}" in sql_lower:
            return ValidatedStatement(
                sql=sql,
                kind="admin",
                blocked=True,
                block_reason=_deny_reason_for_prefix(sql_lower),
            )

    # Deny-list: SET … privilege-escalation patterns
    for pattern in _DENIED_SET_PATTERNS:
        if pattern in sql_lower:
            return ValidatedStatement(
                sql=sql,
                kind="admin",
                blocked=True,
                block_reason="privilege_escalation_blocked",
            )

    try:
        stmts = sqlglot.parse(sql, dialect="postgres")
    except Exception as exc:
        return ValidatedStatement(
            sql=sql,
            kind="admin",
            blocked=True,
            block_reason=f"parse_error: {str(exc)[:100]}",
        )

    if not stmts:
        return ValidatedStatement(
            sql=sql,
            kind="admin",
            blocked=True,
            block_reason="empty_statement",
        )

    overall_kind: Literal["read", "write", "ddl", "tx", "admin"] = "read"
    for stmt in stmts:
        if stmt is None:
            continue
        result = _validate_single(stmt, sql)
        if result.blocked:
            return result
        overall_kind = _merge_kind(overall_kind, result.kind)

    return ValidatedStatement(sql=sql, kind=overall_kind, blocked=False, block_reason=None)


def _validate_single(stmt: exp.Expr, original_sql: str) -> ValidatedStatement:
    """Classify and validate a single parsed statement node."""
    stmt_type = type(stmt).__name__
    kind = _classify_kind(stmt_type)

    # Denied node types (GRANT, REVOKE)
    if stmt_type in _DENIED_NODE_TYPES:
        return ValidatedStatement(
            sql=original_sql,
            kind="admin",
            blocked=True,
            block_reason=f"{stmt_type.lower()}_blocked",
        )

    # Command node — could be COPY, LISTEN, NOTIFY, LOCK TABLE, DO, LOAD, etc.
    if stmt_type == "Command":
        return _check_command_node(stmt, original_sql)

    # CREATE … FUNCTION/PROCEDURE/TRIGGER/AGGREGATE/EXTENSION/LANGUAGE — RCE risk
    if stmt_type == "Create":
        create_result = _check_create_node(stmt, original_sql)
        if create_result is not None:
            return create_result

    # Walk the AST for dangerous function calls (pg_read_file, dblink, etc.)
    func_result = _check_dangerous_functions(stmt, original_sql)
    if func_result is not None:
        return func_result

    return ValidatedStatement(sql=original_sql, kind=kind, blocked=False, block_reason=None)


def _check_command_node(stmt: exp.Expr, original_sql: str) -> ValidatedStatement:
    """Check a sqlglot Command node for denied operations."""
    # sqlglot represents unknown commands as Command with .this = keyword text
    raw = getattr(stmt, "this", "") or ""
    raw_upper = raw.strip().upper()

    denied_keywords = {"COPY", "LISTEN", "NOTIFY", "UNLISTEN", "LOCK", "DO", "LOAD"}
    for kw in denied_keywords:
        if raw_upper.startswith(kw):
            return ValidatedStatement(
                sql=original_sql,
                kind="admin",
                blocked=True,
                block_reason=f"{kw.lower()}_blocked",
            )

    # SET commands for privilege escalation
    if raw_upper.startswith("SET"):
        raw_lower = raw.lower()
        for pattern in _DENIED_SET_PATTERNS:
            if pattern in raw_lower:
                return ValidatedStatement(
                    sql=original_sql,
                    kind="admin",
                    blocked=True,
                    block_reason="privilege_escalation_blocked",
                )
        # All other SET (session-local settings) allowed
        return ValidatedStatement(sql=original_sql, kind="tx", blocked=False, block_reason=None)

    return ValidatedStatement(sql=original_sql, kind="admin", blocked=False, block_reason=None)


def _check_create_node(stmt: exp.Expr, original_sql: str) -> ValidatedStatement | None:
    """Block CREATE FUNCTION, PROCEDURE, TRIGGER, AGGREGATE, LANGUAGE, EXTENSION, etc.

    Returns a blocked ValidatedStatement if the CREATE kind is denied, else None.
    dbt-postgres only emits CREATE TABLE, VIEW, SCHEMA, INDEX — everything else
    is blocked unconditionally for R3.
    """
    # sqlglot Create node exposes .kind (the object type string)
    create_kind = getattr(stmt, "kind", None)
    if create_kind is None:
        # Attempt to read from args dict
        create_kind = stmt.args.get("kind", "")
    kind_upper = str(create_kind).upper() if create_kind else ""

    for denied in _DENIED_CREATE_KINDS:
        if denied in kind_upper:
            return ValidatedStatement(
                sql=original_sql,
                kind="admin",
                blocked=True,
                block_reason=f"create_{denied.lower().replace(' ', '_')}_blocked",
            )

    # Also block SECURITY DEFINER anywhere in the CREATE text
    if "security definer" in original_sql.lower():
        return ValidatedStatement(
            sql=original_sql,
            kind="admin",
            blocked=True,
            block_reason="security_definer_blocked",
        )

    return None


def _check_dangerous_functions(stmt: exp.Expr, original_sql: str) -> ValidatedStatement | None:
    """Walk the AST for calls to dangerous built-in functions.

    Checks both exp.Anonymous (unknown functions) and exp.Func subclasses.
    Returns a blocked ValidatedStatement if a denied function is found, else None.
    """
    # Walk all Anonymous nodes (covers functions sqlglot doesn't know about)
    for node in stmt.find_all(exp.Anonymous):
        func_name = (node.name or "").lower()
        if func_name in _DENIED_FUNCTION_NAMES:
            return ValidatedStatement(
                sql=original_sql,
                kind="admin",
                blocked=True,
                block_reason=f"denied_function_{func_name}",
            )

    # Walk all Func subclasses (covers functions sqlglot has typed representations for)
    for node in stmt.find_all(exp.Func):
        func_name = type(node).__name__.lower()
        # sql_name() is a method on Expression — call it without a lambda to
        # avoid the loop-variable closure capture issue (ruff B023).
        sql_name_raw = node.sql_name() if callable(getattr(node, "sql_name", None)) else func_name
        sql_name = sql_name_raw.lower() if isinstance(sql_name_raw, str) else func_name
        if func_name in _DENIED_FUNCTION_NAMES or sql_name in _DENIED_FUNCTION_NAMES:
            return ValidatedStatement(
                sql=original_sql,
                kind="admin",
                blocked=True,
                block_reason=f"denied_function_{sql_name}",
            )

    return None


def _classify_kind(stmt_type: str) -> Literal["read", "write", "ddl", "tx", "admin"]:
    if stmt_type in _READ_TYPES:
        return "read"
    if stmt_type in _WRITE_TYPES:
        return "write"
    if stmt_type in _DDL_TYPES:
        return "ddl"
    if stmt_type in _TX_TYPES:
        return "tx"
    return "admin"


def _merge_kind(
    a: Literal["read", "write", "ddl", "tx", "admin"],
    b: Literal["read", "write", "ddl", "tx", "admin"],
) -> Literal["read", "write", "ddl", "tx", "admin"]:
    """Promote kind to the 'most significant' type in a multi-statement string."""
    order = {"read": 0, "tx": 1, "write": 2, "ddl": 3, "admin": 4}
    return a if order[a] >= order[b] else b


def _deny_reason_for_prefix(sql_lower: str) -> str:
    if sql_lower.startswith("copy"):
        return "copy_blocked"
    if sql_lower.startswith("do"):
        return "do_block_blocked"
    if sql_lower.startswith("load"):
        return "load_blocked"
    if "listen" in sql_lower[:20]:
        return "listen_blocked"
    if "notify" in sql_lower[:20]:
        return "notify_blocked"
    if "unlisten" in sql_lower[:20]:
        return "unlisten_blocked"
    if "lock" in sql_lower[:20]:
        return "lock_blocked"
    if "security definer" in sql_lower:
        return "security_definer_blocked"
    if "create role" in sql_lower or "drop role" in sql_lower or "alter role" in sql_lower:
        return "role_management_blocked"
    if "create user" in sql_lower or "drop user" in sql_lower or "alter user" in sql_lower:
        return "user_management_blocked"
    if "database" in sql_lower[:30]:
        return "database_management_blocked"
    if "tablespace" in sql_lower[:30]:
        return "tablespace_blocked"
    if "extension" in sql_lower[:30]:
        return "extension_blocked"
    if "language" in sql_lower[:30]:
        return "language_blocked"
    if "function" in sql_lower[:30]:
        return "create_function_blocked"
    if "procedure" in sql_lower[:30]:
        return "create_procedure_blocked"
    if "trigger" in sql_lower[:30]:
        return "create_trigger_blocked"
    return "denied_statement"


__all__ = ["ValidatedStatement", "validate_dbt_statement"]
