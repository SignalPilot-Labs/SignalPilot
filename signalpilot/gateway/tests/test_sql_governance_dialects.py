"""Per-dialect dangerous-function governance: the fail-open denylist regression suite.

Covers the SP-SEC-011 fix in ``gateway/engine/denylists.py``:

* ``_DANGEROUS_FUNCTIONS`` previously returned an EMPTY set for any dialect
  without an explicit policy, so every dialect except the handful that were
  enumerated failed OPEN. It now falls back to the union of every reviewed
  dialect denylist.
* A real ``tsql`` policy was added (OPENROWSET / OPENDATASOURCE / OPENQUERY /
  OPENXML / xp_cmdshell / sp_executesql / sp_oacreate / sp_oamethod /
  sp_addlinkedserver / xp_dirtree / xp_fileexist / xp_regread / xp_regwrite)
  and ``mssql`` normalizes onto it.
* ``databricks`` (read_files / cloud_files / read_kafka / reflect / java_method
  / secret) and ``trino`` (query / raw_query / native_query) policies were added.
* ``redshift`` inherits the postgres policy (dblink family, pg_read_file, ...).
* ``_is_pathlike_table_name`` rejects DuckDB path/URL-as-table identifiers.

Every case here is a UNIT test over ``validate_sql`` /
``_check_dangerous_functions``. End-to-end proof that a rejected query never
reaches a server lives in ``tests/test_sql_governance_live.py``.
"""

from __future__ import annotations

import pytest

# Symbols introduced by the SP-SEC-011 fix. Resolved lazily through the module so
# that running this suite against the pre-fix sources produces ATTRIBUTE-ERROR
# TEST FAILURES rather than a collection error that hides the rest of the file.
from gateway.engine import denylists as _denylists
from gateway.engine import validate_sql
from gateway.engine._sqlglot import sqlglot
from gateway.engine.denylists import _DANGEROUS_FUNCTIONS, _check_dangerous_functions


def _all_dialect_functions() -> frozenset[str]:
    return _denylists._ALL_DIALECT_FUNCTIONS


def _is_pathlike_table_name(name: str) -> bool:
    return _denylists._is_pathlike_table_name(name)


def _blocked(sql: str, dialect: str) -> str:
    """Assert validate_sql rejects ``sql`` and return the reason."""
    result = validate_sql(sql, dialect=dialect)
    assert result.ok is False, f"[{dialect}] EXPECTED BLOCK but validate_sql allowed: {sql}"
    assert result.blocked_reason
    return result.blocked_reason


# ───────────────────────────────────────────────────────────────────────────────
# Probe rows from security/automated-results.md ("SQL governance probes")
#
# The audit recorded these three inputs as "Allowed by validate_sql". They must
# now all be blocked. (The two LIMIT probe rows from the same table live in
# tests/test_limit_enforcement.py.)
# ───────────────────────────────────────────────────────────────────────────────


class TestAutomatedResultsProbeRows:
    def test_probe_duckdb_path_as_table_url(self) -> None:
        reason = _blocked("SELECT * FROM 'https://example.com/x.parquet'", "duckdb")
        assert "file or URL table reference" in reason

    def test_probe_tsql_openrowset(self) -> None:
        reason = _blocked("SELECT a.* FROM OPENROWSET('SQLNCLI', 'Server=x;', 'SELECT 1') AS a", "tsql")
        assert "OPENROWSET" in reason.upper()

    def test_probe_redshift_dblink(self) -> None:
        reason = _blocked("SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(a int)", "redshift")
        assert "dblink" in reason


# ───────────────────────────────────────────────────────────────────────────────
# DuckDB path-as-table
# ───────────────────────────────────────────────────────────────────────────────


class TestDuckDBPathAsTable:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM 'https://example.com/x.parquet'",
            "SELECT * FROM 'http://evil.internal/leak.csv'",
            "SELECT * FROM 's3://bucket/key.parquet'",
            "SELECT * FROM '/etc/passwd'",
            "SELECT * FROM './relative/path.csv'",
            "SELECT * FROM 'C:/windows/win.ini'",
            "SELECT * FROM 'data.csv'",
            "SELECT * FROM 'export.parquet'",
            "SELECT * FROM 'dump.json'",
            "SELECT * FROM 'other.duckdb'",
            "SELECT * FROM 'creds.sqlite'",
        ],
    )
    def test_pathlike_table_blocked(self, sql: str) -> None:
        assert "not permitted" in _blocked(sql, "duckdb")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM read_csv_auto('/etc/passwd')",
            "SELECT * FROM read_parquet('s3://b/k.parquet')",
            "SELECT * FROM read_json_auto('/etc/shadow')",
            "SELECT read_text('/etc/passwd')",
            "SELECT read_blob('/etc/passwd')",
            "SELECT * FROM postgres_scan('host=x', 'public', 't')",
            "SELECT * FROM sqlite_scan('/tmp/x.db', 't')",
            "SELECT load_extension('httpfs')",
        ],
    )
    def test_file_reader_functions_blocked(self, sql: str) -> None:
        assert "not permitted" in _blocked(sql, "duckdb")

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("https://x/y.parquet", True),
            ("s3://b/k", True),
            ("/etc/passwd", True),
            ("dir\\file", True),
            ("data.csv", True),
            ("x.PARQUET", True),
            ("", False),
            ("orders", False),
            ("stg_orders", False),
            ("main", False),
            ("my_table_2024", False),
        ],
    )
    def test_is_pathlike_helper(self, name: str, expected: bool) -> None:
        assert _is_pathlike_table_name(name) is expected

    # REGRESSION: real DuckDB tables must keep working.
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM orders",
            "SELECT * FROM main.orders",
            "SELECT * FROM memory.main.orders",
            "SELECT o.id FROM main.stg_orders AS o JOIN main.customers AS c ON c.id = o.customer_id",
            "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
            "SELECT * FROM 'plain_table'",  # a quoted bare identifier is not path-like
        ],
    )
    def test_legitimate_duckdb_queries_still_pass(self, sql: str) -> None:
        assert validate_sql(sql, dialect="duckdb").ok is True


# ───────────────────────────────────────────────────────────────────────────────
# T-SQL / MSSQL
# ───────────────────────────────────────────────────────────────────────────────

_TSQL_PAYLOADS = [
    "SELECT a.* FROM OPENROWSET('SQLNCLI', 'Server=x;', 'SELECT 1') AS a",
    "SELECT * FROM OPENROWSET(BULK 'C:/secrets.txt', SINGLE_CLOB) AS d",
    "SELECT opendatasource('SQLOLEDB', 'Data Source=evil') AS x",
    "SELECT * FROM OPENDATASOURCE('SQLOLEDB', 'x').db.dbo.t",
    "SELECT * FROM OPENQUERY(linked_srv, 'SELECT 1')",
    "SELECT openxml(1, '/root')",
    "SELECT xp_cmdshell('dir C:/')",
    "SELECT sp_executesql('SELECT 1')",
    "SELECT sp_oacreate('WScript.Shell', 1)",
    "SELECT sp_oamethod(1, 'Run')",
    "SELECT sp_addlinkedserver('evil')",
    "SELECT xp_dirtree('C:/')",
    "SELECT xp_fileexist('C:/boot.ini')",
    "SELECT xp_regread('HKLM', 'a', 'b')",
    "SELECT xp_regwrite('HKLM', 'a', 'b', 'c', 'd')",
]


class TestTSQLDialect:
    @pytest.mark.parametrize("sql", _TSQL_PAYLOADS)
    def test_tsql_key_blocks_payload(self, sql: str) -> None:
        # OPENROWSET(BULK ...) is not parseable by sqlglot, so it is rejected at
        # the parse stage instead of the denylist stage — either way it is blocked.
        _blocked(sql, "tsql")

    @pytest.mark.parametrize("sql", _TSQL_PAYLOADS)
    def test_mssql_key_also_blocks_payload(self, sql: str) -> None:
        """The ``mssql`` dialect key must fail closed too.

        sqlglot has no dialect literally named ``mssql`` (SignalPilot maps
        db_type ``mssql`` -> sqlglot ``tsql`` via ``sqlglot_dialect``), so
        validate_sql rejects it at the parse stage. This test pins that
        fail-CLOSED behaviour: an unrecognised dialect name must never allow the
        payload through.
        """
        _blocked(sql, "mssql")

    @pytest.mark.parametrize(
        "func_sql",
        [
            "SELECT xp_cmdshell('dir')",
            "SELECT a.* FROM OPENROWSET('SQLNCLI', 'Server=x;', 'SELECT 1') AS a",
            "SELECT sp_executesql('x')",
        ],
    )
    def test_mssql_normalizes_onto_tsql_denylist(self, func_sql: str) -> None:
        """``_check_dangerous_functions`` maps the ``mssql`` alias onto ``tsql``.

        This is the reachable path for callers that hand a raw db_type string to
        the walker (e.g. ``_validate_where_predicate``), and it is the direct
        unit proof that the alias resolves to the real T-SQL policy rather than
        to an empty set.
        """
        parsed = sqlglot.parse_one(func_sql, dialect="tsql")
        assert _check_dangerous_functions(parsed, "mssql") is not None
        assert _check_dangerous_functions(parsed, "tsql") is not None

    def test_tsql_policy_covers_every_documented_function(self) -> None:
        expected = {
            "openrowset",
            "opendatasource",
            "openquery",
            "openxml",
            "xp_cmdshell",
            "sp_executesql",
            "sp_oacreate",
            "sp_oamethod",
            "sp_addlinkedserver",
            "xp_dirtree",
            "xp_fileexist",
            "xp_regread",
            "xp_regwrite",
        }
        assert expected <= _DANGEROUS_FUNCTIONS["tsql"]

    # REGRESSION: legitimate T-SQL still passes.
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM analytics.customers",
            "SELECT TOP 10 name FROM analytics.customers ORDER BY customer_id",
            "SELECT c.name, SUM(o.amount) AS total FROM analytics.customers c "
            "JOIN analytics.orders o ON o.customer_id = c.customer_id GROUP BY c.name",
            "SELECT DATEDIFF(day, '2024-01-01', created_at) AS age FROM analytics.customers",
        ],
    )
    def test_legitimate_tsql_still_passes(self, sql: str) -> None:
        assert validate_sql(sql, dialect="tsql").ok is True


# ───────────────────────────────────────────────────────────────────────────────
# Redshift inherits postgres
# ───────────────────────────────────────────────────────────────────────────────


class TestRedshiftInheritsPostgres:
    def test_redshift_policy_is_the_postgres_policy(self) -> None:
        assert _DANGEROUS_FUNCTIONS["redshift"] == _DANGEROUS_FUNCTIONS["postgres"]

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(a int)",
            "SELECT dblink_exec('h', 'DROP TABLE x')",
            "SELECT dblink_connect('h')",
            "SELECT dblink_send_query('h', 'SELECT 1')",
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT pg_read_server_files('/etc/passwd')",
            "SELECT pg_ls_dir('/')",
            "SELECT lo_import('/etc/passwd')",
            "SELECT lo_export(1, '/tmp/out')",
            "SELECT pg_execute_server_program('id')",
            "SELECT set_config('x', 'y', false)",
            "SELECT pg_terminate_backend(1)",
        ],
    )
    def test_redshift_blocks_postgres_payloads(self, sql: str) -> None:
        assert "not permitted" in _blocked(sql, "redshift")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(a int)",
            "SELECT pg_read_file('/etc/passwd')",
        ],
    )
    def test_postgres_blocks_same_payloads(self, sql: str) -> None:
        assert "not permitted" in _blocked(sql, "postgres")

    # REGRESSION
    @pytest.mark.parametrize("dialect", ["postgres", "redshift"])
    def test_legitimate_queries_still_pass(self, dialect: str) -> None:
        assert validate_sql("SELECT id, name FROM public.customers WHERE id > 5", dialect=dialect).ok is True


# ───────────────────────────────────────────────────────────────────────────────
# Databricks / Trino (new policies)
# ───────────────────────────────────────────────────────────────────────────────


class TestDatabricksDialect:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM read_files('s3://bucket/prefix')",
            "SELECT * FROM cloud_files('s3://bucket/prefix', 'json')",
            "SELECT * FROM read_kafka('topic')",
            "SELECT reflect('java.lang.Runtime', 'getRuntime')",
            "SELECT java_method('java.lang.System', 'getenv', 'PATH')",
            "SELECT secret('scope', 'key')",
        ],
    )
    def test_databricks_payloads_blocked(self, sql: str) -> None:
        assert "not permitted" in _blocked(sql, "databricks")

    def test_legitimate_databricks_query_passes(self) -> None:
        assert validate_sql("SELECT id FROM main.analytics.orders LIMIT 10", dialect="databricks").ok is True


class TestTrinoDialect:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM TABLE(system.query(query => 'SELECT 1'))",
            "SELECT * FROM TABLE(pg_catalog.system.query(query => 'DROP TABLE x'))",
            "SELECT * FROM TABLE(system.raw_query(query => 'SELECT 1'))",
            "SELECT * FROM TABLE(system.native_query(query => 'SELECT 1'))",
        ],
    )
    def test_trino_polymorphic_table_functions_blocked(self, sql: str) -> None:
        assert "not permitted" in _blocked(sql, "trino")

    def test_legitimate_trino_query_passes(self) -> None:
        assert validate_sql("SELECT id FROM hive.analytics.orders", dialect="trino").ok is True

    def test_known_gap_bare_system_query_identifier_is_allowed(self) -> None:
        """Documented, accepted gap: ``FROM catalog.system.query`` (no argument
        list) parses as a plain three-part table name, not a function call, and
        is allowed.

        Trino's polymorphic table functions can only be invoked through the
        ``TABLE(...)`` form, which IS blocked above, so this identifier form
        cannot smuggle a raw query. If a future Trino release permits a bare
        invocation, this test will still pass and the assertion below must be
        revisited — it is a deliberate marker, not coverage.
        """
        assert validate_sql("SELECT * FROM postgresql.system.query", dialect="trino").ok is True


# ───────────────────────────────────────────────────────────────────────────────
# Fail-closed fallback for dialects with no reviewed policy
# ───────────────────────────────────────────────────────────────────────────────


class TestUnknownDialectFailsClosed:
    """The core SP-SEC-011 regression.

    Before the fix ``_DANGEROUS_FUNCTIONS.get(dialect_key, frozenset())``
    returned an empty set for any dialect that had no explicit entry, so a
    dangerous function was allowed straight through. Now every unlisted dialect
    gets the union of all reviewed denylists.
    """

    # sqlglot-parseable dialects for which SignalPilot has NO explicit policy.
    # These are the real fail-open surface: the SQL parses, so the denylist walk
    # runs, and before the fix it walked with an empty denylist.
    POLICYLESS_DIALECTS = [
        "oracle",
        "spark",
        "hive",
        "presto",
        "athena",
        "teradata",
        "starrocks",
        "doris",
        "drill",
        "materialize",
    ]

    PAYLOADS = [
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT xp_cmdshell('dir')",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT load_file('/etc/passwd')",
        "SELECT sys_exec('id')",
        "SELECT reflect('java.lang.Runtime', 'getRuntime')",
        "SELECT readfile('/etc/passwd')",
    ]

    @pytest.mark.parametrize("dialect", POLICYLESS_DIALECTS)
    @pytest.mark.parametrize("sql", PAYLOADS)
    def test_policyless_dialect_blocks_every_known_payload(self, dialect: str, sql: str) -> None:
        assert "not permitted" in _blocked(sql, dialect)

    @pytest.mark.parametrize(
        "made_up",
        ["totally_made_up_dialect", "sqlserver", "wibble", "postgres9", ""],
    )
    def test_walker_uses_union_for_made_up_dialect_names(self, made_up: str) -> None:
        """Direct unit proof against the AST walker for names sqlglot cannot parse."""
        for sql, parse_dialect in [
            ("SELECT xp_cmdshell('dir')", "tsql"),
            ("SELECT pg_read_file('/etc/passwd')", "postgres"),
            ("SELECT * FROM read_csv_auto('/etc/passwd')", "duckdb"),
        ]:
            parsed = sqlglot.parse_one(sql, parse_dialect)
            assert _check_dangerous_functions(parsed, made_up) is not None, (
                f"FAIL OPEN: dialect {made_up!r} allowed {sql!r}"
            )

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT xp_cmdshell('dir')",
        ],
    )
    def test_unparseable_dialect_name_is_rejected_by_validate_sql(self, sql: str) -> None:
        """``validate_sql`` with a name sqlglot does not know must not allow the query."""
        assert validate_sql(sql, dialect="totally_made_up_dialect").ok is False

    def test_union_set_contains_every_dialect_policy(self) -> None:
        union = _all_dialect_functions()
        for dialect, funcs in _DANGEROUS_FUNCTIONS.items():
            assert funcs <= union, f"{dialect} policy is not covered by the union fallback"
        assert "xp_cmdshell" in union
        assert "pg_read_file" in union
        assert "read_files" in union
        assert "raw_query" in union


# ───────────────────────────────────────────────────────────────────────────────
# Cross-dialect regression: a plain SELECT is never blocked
# ───────────────────────────────────────────────────────────────────────────────


class TestPlainSelectRegression:
    ALL_DIALECTS = [
        "postgres",
        "redshift",
        "mysql",
        "snowflake",
        "bigquery",
        "clickhouse",
        "databricks",
        "tsql",
        "trino",
        "duckdb",
        "sqlite",
    ]

    @pytest.mark.parametrize("dialect", ALL_DIALECTS)
    def test_plain_select_passes(self, dialect: str) -> None:
        result = validate_sql("SELECT 1 AS ok", dialect=dialect)
        assert result.ok is True, f"[{dialect}] plain SELECT was blocked: {result.blocked_reason}"

    @pytest.mark.parametrize("dialect", ALL_DIALECTS)
    def test_table_select_with_filter_passes(self, dialect: str) -> None:
        result = validate_sql("SELECT id, name FROM customers WHERE id > 1 ORDER BY id", dialect=dialect)
        assert result.ok is True, f"[{dialect}] table SELECT was blocked: {result.blocked_reason}"

    @pytest.mark.parametrize("dialect", ALL_DIALECTS)
    def test_cte_and_aggregate_pass(self, dialect: str) -> None:
        sql = "WITH t AS (SELECT id, amount FROM orders) SELECT id, SUM(amount) AS total FROM t GROUP BY id"
        result = validate_sql(sql, dialect=dialect)
        assert result.ok is True, f"[{dialect}] CTE was blocked: {result.blocked_reason}"

    @pytest.mark.parametrize("dialect", ALL_DIALECTS)
    def test_ddl_is_still_blocked_everywhere(self, dialect: str) -> None:
        assert validate_sql("DROP TABLE customers", dialect=dialect).ok is False


# ───────────────────────────────────────────────────────────────────────────────
# FILE-READ / REMOTE-ACCESS PRIMITIVES — found while building this suite
#
# Every case here was a live bypass when the suite was written. All but one are
# now blocked and assert that positively. Anything still open stays a STRICT
# xfail so the suite names it out loud, and so fixing it turns the test XPASS —
# which a strict xfail reports as a failure, forcing the marker to be deleted in
# the same change as the fix. Do NOT relax a remaining xfail into a pass.
#
# Still open: the four-part T-SQL linked-server name below, and DuckDB's
# enable_external_access (see test_sql_governance_live.py).
# ───────────────────────────────────────────────────────────────────────────────


class TestFileAndRemoteAccessPrimitives:
    # DuckDB reader ALIASES that are absent from the duckdb denylist. Verified to
    # exist in the shipped duckdb build; parquet_scan demonstrably reads a file.
    DUCKDB_ALIAS_BYPASSES = [
        "SELECT * FROM parquet_scan('/etc/passwd')",
        "SELECT * FROM read_ndjson('/etc/passwd')",
        "SELECT * FROM read_ndjson_auto('/etc/passwd')",
        "SELECT * FROM read_json_objects('/etc/passwd')",
        "SELECT * FROM glob('/etc/*')",
    ]

    @pytest.mark.parametrize("sql", DUCKDB_ALIAS_BYPASSES, ids=[s[:40] for s in DUCKDB_ALIAS_BYPASSES])
    def test_duckdb_reader_aliases_should_be_blocked(self, sql: str) -> None:
        assert validate_sql(sql, dialect="duckdb").ok is False

    def test_clickhouse_file_table_function_should_be_blocked(self) -> None:
        assert validate_sql("SELECT * FROM file('/etc/passwd')", dialect="clickhouse").ok is False

    DATABRICKS_PATH_BYPASSES = [
        "SELECT * FROM parquet.`/etc/passwd`",
        "SELECT * FROM json.`s3://bucket/key`",
        "SELECT * FROM csv.`/etc/passwd`",
    ]

    @pytest.mark.parametrize("sql", DATABRICKS_PATH_BYPASSES, ids=[s[:40] for s in DATABRICKS_PATH_BYPASSES])
    def test_databricks_path_table_syntax_should_be_blocked(self, sql: str) -> None:
        assert validate_sql(sql, dialect="databricks").ok is False

    POSTGRES_BYPASSES = [
        # Executes an arbitrary SQL string server-side, entirely outside the AST governance.
        "SELECT query_to_xml('SELECT * FROM pg_authid', true, true, '')",
        # File metadata disclosure.
        "SELECT pg_stat_file('/etc/passwd')",
        # Trivial denial of service.
        "SELECT pg_sleep(600)",
        # Configuration / path disclosure.
        "SELECT current_setting('data_directory')",
    ]

    @pytest.mark.parametrize("sql", POSTGRES_BYPASSES, ids=[s[:40] for s in POSTGRES_BYPASSES])
    def test_postgres_residual_primitives_should_be_blocked(self, sql: str) -> None:
        assert validate_sql(sql, dialect="postgres").ok is False

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "OPEN BYPASS: a four-part T-SQL name reaches a linked server without "
            "OPENQUERY/OPENROWSET. Blocking needs a table-shape rule, not a function "
            "denylist entry."
        ),
    )
    def test_tsql_four_part_linked_server_name_should_be_blocked(self) -> None:
        assert validate_sql("SELECT * FROM evil_srv.db.dbo.tbl", dialect="tsql").ok is False
