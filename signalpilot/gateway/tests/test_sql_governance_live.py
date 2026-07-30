"""Real-database integration tests for the SQL-governance security fixes.

Every group skips cleanly when its database is not reachable, matching the
conventions in ``tests/test_connectors_live.py`` and ``tests/test_mssql_e2e.py``.

Databases exercised:

* **SQL Server** — container ``sp-mssql-test`` on 127.0.0.1:1434, seeded by
  ``tests/fixtures/seed_mssql.py``. Proves T-SQL OPENROWSET / xp_cmdshell
  payloads are rejected by governance BEFORE any bytes reach the server, and
  that a legitimate governed query still returns rows.
* **PostgreSQL warehouses** — the trap-arena demo warehouses
  (akasa 5603 / parallax 5608 / keystone 5604 / nala 5602). Proves the
  dblink / pg_read_file family is rejected, that a legitimate query executes,
  and that the LIMIT cap actually truncates a real result set end to end.
* **DuckDB** — exercised in-process against a temporary file database. Proves
  ``FROM 'https://…/x.parquet'`` and ``FROM '/etc/passwd'`` are rejected while
  real and schema-qualified table reads keep working.

CREDENTIALS: no secret is hardcoded here. Postgres credentials come from
``SP_TEST_PG_URL`` if set, otherwise they are read at runtime from the local
(untracked) ``demo-generator/trap-arena/projects/<name>/project.env`` files. If
neither source is present the Postgres group skips.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from gateway.engine import inject_limit, validate_sql


class GovernanceBlocked(RuntimeError):
    """Raised by the governed-execute helper when validate_sql rejects a query."""


class _CountingConnector:
    """Wraps a connector and counts how many statements reach ``execute``.

    Used to prove that a blocked payload never leaves the process.
    """

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[str] = []

    async def execute(self, sql: str, params=None):
        self.calls.append(sql)
        if params is None:
            return await self._inner.execute(sql)
        return await self._inner.execute(sql, params=params)


async def governed_execute(connector, sql: str, *, dialect: str, max_rows: int = 100):
    """Run the production governance pipeline, then execute.

    Mirrors what the gateway does for every agent query: validate, inject the
    row cap, execute. A rejection raises before ``connector.execute`` is called.
    """
    result = validate_sql(sql, dialect=dialect)
    if not result.ok:
        raise GovernanceBlocked(result.blocked_reason or "blocked")
    return await connector.execute(inject_limit(sql, max_rows=max_rows, dialect=dialect))


# ═══════════════════════════════════════════════════════════════════════════════
# SQL Server (live container sp-mssql-test)
# ═══════════════════════════════════════════════════════════════════════════════

MSSQL_HOST = os.environ.get("SP_TEST_MSSQL_HOST", "127.0.0.1")
MSSQL_PORT = os.environ.get("SP_TEST_MSSQL_PORT", "1434")
# Same throwaway dev credentials the existing tests/test_mssql_e2e.py uses.
MSSQL_URL = f"mssql://sa:Str0ng%21Passw0rd@{MSSQL_HOST}:{MSSQL_PORT}/sp_test"
MSSQL_CUSTOMERS = "analytics.customers"


def _mssql_available() -> bool:
    try:
        import pymssql
    except ImportError:
        return False
    try:
        conn = pymssql.connect(
            server=MSSQL_HOST,
            port=MSSQL_PORT,
            user="sa",
            password="Str0ng!Passw0rd",
            database="sp_test",
            login_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


_MSSQL_UP = _mssql_available()

TSQL_PAYLOADS = [
    "SELECT a.* FROM OPENROWSET('SQLNCLI', 'Server=evil;Trusted_Connection=yes;', 'SELECT 1') AS a",
    "SELECT * FROM OPENROWSET(BULK 'C:/Windows/win.ini', SINGLE_CLOB) AS d",
    "SELECT * FROM OPENDATASOURCE('SQLOLEDB', 'Data Source=evil').sp_test.analytics.customers",
    "SELECT * FROM OPENQUERY(evil_link, 'SELECT 1')",
    "SELECT xp_cmdshell('whoami')",
    "SELECT xp_dirtree('C:/')",
    "SELECT sp_executesql('SELECT 1')",
]


@pytest.mark.skipif(not _MSSQL_UP, reason="SQL Server test container (sp-mssql-test) not reachable")
class TestMSSQLLiveGovernance:
    DIALECT = "tsql"

    @pytest.fixture
    async def connector(self):
        from gateway.connectors.drivers.mssql import MSSQLConnector

        c = MSSQLConnector()
        await c.connect(MSSQL_URL)
        yield c
        await c.close()

    @pytest.mark.parametrize("payload", TSQL_PAYLOADS, ids=[p[:44] for p in TSQL_PAYLOADS])
    async def test_payload_blocked_before_reaching_the_server(self, connector, payload: str) -> None:
        spy = _CountingConnector(connector)
        with pytest.raises(GovernanceBlocked):
            await governed_execute(spy, payload, dialect=self.DIALECT)
        assert spy.calls == [], f"payload reached the SQL Server socket: {payload!r}"

    async def test_legitimate_query_executes_and_returns_rows(self, connector) -> None:
        rows = await governed_execute(
            connector,
            f"SELECT name, region FROM {MSSQL_CUSTOMERS} ORDER BY customer_id",
            dialect=self.DIALECT,
        )
        assert len(rows) == 5
        assert rows[0]["name"] == "Acme Corp"

    async def test_legitimate_join_still_executes(self, connector) -> None:
        rows = await governed_execute(
            connector,
            "SELECT c.name, SUM(o.amount) AS total FROM analytics.customers c "
            "JOIN analytics.orders o ON o.customer_id = c.customer_id GROUP BY c.name",
            dialect=self.DIALECT,
        )
        assert len(rows) >= 1

    async def test_limit_cap_enforced_end_to_end_via_top(self, connector) -> None:
        governed = inject_limit(f"SELECT * FROM {MSSQL_CUSTOMERS}", max_rows=2, dialect=self.DIALECT)
        assert "TOP 2" in governed
        rows = await connector.execute(governed)
        assert len(rows) == 2

    async def test_small_top_is_not_inflated(self, connector) -> None:
        """A TOP below the cap keeps its original value against the real server."""
        governed = inject_limit(f"SELECT * FROM {MSSQL_CUSTOMERS} ORDER BY customer_id", max_rows=100, dialect="tsql")
        assert "TOP 100" in governed
        rows = await connector.execute(
            inject_limit(f"SELECT TOP 3 * FROM {MSSQL_CUSTOMERS} ORDER BY customer_id", max_rows=100, dialect="tsql")
        )
        assert len(rows) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# PostgreSQL warehouses (live containers)
# ═══════════════════════════════════════════════════════════════════════════════

_PROJECT_ENV_DIR = Path(__file__).resolve().parents[3] / "demo-generator" / "trap-arena" / "projects"
_PG_PROJECT_ORDER = ("akasa", "parallax", "keystone", "nala")


def _read_project_env_url(project: str) -> str | None:
    """Build a Postgres URL from a local trap-arena project.env, or None.

    Reads the read-only role. Nothing is printed; the value is only handed to the
    connector.
    """
    path = _PROJECT_ENV_DIR / project / "project.env"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    def field(key: str) -> str | None:
        m = re.search(rf"^{key}\s*=\s*([^;\s#]+)", text, re.MULTILINE)
        return m.group(1) if m else None

    port, database = field("PG_PORT"), field("PG_DB")
    user = field("PG_USER_RO")
    pw_match = re.search(r"PG_PASS_RO\s*=\s*([^;\s#]+)", text)
    if not (port and database and user and pw_match):
        return None
    from urllib.parse import quote

    return f"postgresql://{quote(user)}:{quote(pw_match.group(1), safe='')}@127.0.0.1:{port}/{database}"


def _resolve_pg_url() -> str | None:
    if url := os.environ.get("SP_TEST_PG_URL"):
        return url
    for project in _PG_PROJECT_ORDER:
        if url := _read_project_env_url(project):
            return url
    return None


def _pg_reachable(url: str) -> bool:
    import asyncio

    async def _probe() -> bool:
        from gateway.connectors.drivers.postgres import PostgresConnector

        c = PostgresConnector()
        try:
            await c.connect(url)
            ok = await c.health_check()
            await c.close()
            return bool(ok)
        except Exception:
            return False

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


PG_URL = _resolve_pg_url()
_PG_UP = bool(PG_URL) and _pg_reachable(PG_URL)

POSTGRES_PAYLOADS = [
    "SELECT * FROM dblink('host=evil port=5432 dbname=x', 'SELECT 1') AS t(a int)",
    "SELECT dblink_exec('host=evil', 'DROP TABLE x')",
    "SELECT dblink_connect('host=evil')",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_read_server_files('/etc/passwd')",
    "SELECT pg_read_binary_file('/etc/passwd')",
    "SELECT pg_ls_dir('/')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT pg_execute_server_program('id')",
    "SELECT pg_terminate_backend(1)",
    "SELECT set_config('log_statement', 'none', false)",
]


@pytest.mark.skipif(
    not _PG_UP,
    reason="No reachable Postgres warehouse (set SP_TEST_PG_URL or start a trap-arena warehouse container)",
)
class TestPostgresLiveGovernance:
    DIALECT = "postgres"

    @pytest.fixture
    async def connector(self):
        from gateway.connectors.drivers.postgres import PostgresConnector

        c = PostgresConnector()
        await c.connect(PG_URL)
        yield c
        await c.close()

    @pytest.mark.parametrize("payload", POSTGRES_PAYLOADS, ids=[p[:44] for p in POSTGRES_PAYLOADS])
    async def test_payload_blocked_before_reaching_the_server(self, connector, payload: str) -> None:
        spy = _CountingConnector(connector)
        with pytest.raises(GovernanceBlocked):
            await governed_execute(spy, payload, dialect=self.DIALECT)
        assert spy.calls == [], f"payload reached the Postgres socket: {payload!r}"

    @pytest.mark.parametrize("payload", POSTGRES_PAYLOADS[:4], ids=[p[:44] for p in POSTGRES_PAYLOADS[:4]])
    async def test_same_payloads_blocked_on_the_redshift_dialect(self, connector, payload: str) -> None:
        """Redshift inherits the postgres policy; run it against a real PG server."""
        spy = _CountingConnector(connector)
        with pytest.raises(GovernanceBlocked):
            await governed_execute(spy, payload, dialect="redshift")
        assert spy.calls == []

    async def test_legitimate_query_executes(self, connector) -> None:
        rows = await governed_execute(connector, "SELECT 1 AS ok", dialect=self.DIALECT)
        assert rows[0]["ok"] == 1

    async def test_legitimate_catalog_query_executes(self, connector) -> None:
        rows = await governed_execute(
            connector,
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2",
            dialect=self.DIALECT,
            max_rows=25,
        )
        assert len(rows) >= 1
        assert "table_name" in rows[0]

    # ── END-TO-END LIMIT CAP ────────────────────────────────────────────────

    CAP = 7
    BIG_TABLE = "information_schema.columns"

    async def test_source_table_has_more_rows_than_the_cap(self, connector) -> None:
        rows = await connector.execute(f"SELECT COUNT(*) AS n FROM {self.BIG_TABLE}")
        assert int(rows[0]["n"]) > self.CAP

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT column_name FROM information_schema.columns",
            "SELECT column_name FROM information_schema.columns LIMIT ALL",
            "SELECT column_name FROM information_schema.columns FETCH FIRST 5000 ROWS ONLY",
            "SELECT column_name FROM information_schema.columns LIMIT 99999",
            "SELECT column_name FROM information_schema.columns OFFSET 2",
        ],
        ids=["no-limit", "limit-all", "fetch-first-5000", "limit-99999", "offset-only"],
    )
    async def test_row_count_returned_equals_the_cap(self, connector, sql: str) -> None:
        """The real proof: the server actually returns exactly ``CAP`` rows."""
        rows = await governed_execute(connector, sql, dialect=self.DIALECT, max_rows=self.CAP)
        assert len(rows) == self.CAP, f"cap not enforced end to end for {sql!r}: got {len(rows)} rows"

    async def test_limit_below_cap_is_honoured_not_inflated(self, connector) -> None:
        rows = await governed_execute(
            connector,
            "SELECT column_name FROM information_schema.columns LIMIT 3",
            dialect=self.DIALECT,
            max_rows=self.CAP,
        )
        assert len(rows) == 3

    async def test_fetch_first_below_cap_is_honoured(self, connector) -> None:
        rows = await governed_execute(
            connector,
            "SELECT column_name FROM information_schema.columns FETCH FIRST 3 ROWS ONLY",
            dialect=self.DIALECT,
            max_rows=self.CAP,
        )
        assert len(rows) == 3

    async def test_offset_is_still_applied_after_clamping(self, connector) -> None:
        base = await governed_execute(
            connector,
            "SELECT column_name FROM information_schema.columns ORDER BY column_name",
            dialect=self.DIALECT,
            max_rows=self.CAP,
        )
        shifted = await governed_execute(
            connector,
            "SELECT column_name FROM information_schema.columns ORDER BY column_name OFFSET 3",
            dialect=self.DIALECT,
            max_rows=self.CAP,
        )
        assert len(base) == self.CAP
        assert len(shifted) == self.CAP
        assert [r["column_name"] for r in base][3:] == [r["column_name"] for r in shifted][: self.CAP - 3]


# ═══════════════════════════════════════════════════════════════════════════════
# DuckDB (in-process)
# ═══════════════════════════════════════════════════════════════════════════════

try:
    import duckdb as _duckdb

    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False


DUCKDB_PATH_PAYLOADS = [
    "SELECT * FROM 'https://example.com/x.parquet'",
    "SELECT * FROM 'http://169.254.169.254/latest/meta-data'",
    "SELECT * FROM 's3://bucket/key.parquet'",
    "SELECT * FROM '/etc/passwd'",
    "SELECT * FROM 'data.csv'",
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_parquet('https://example.com/x.parquet')",
    "SELECT read_text('/etc/passwd')",
    "SELECT load_extension('httpfs')",
]


@pytest.mark.skipif(not _HAS_DUCKDB, reason="duckdb not installed")
class TestDuckDBLiveGovernance:
    DIALECT = "duckdb"

    @pytest.fixture
    async def connector(self, tmp_path):
        import duckdb

        db_file = tmp_path / "gov_test.duckdb"
        seed = duckdb.connect(str(db_file))
        seed.execute("CREATE SCHEMA IF NOT EXISTS analytics")
        seed.execute("CREATE TABLE analytics.orders AS SELECT range AS id, range % 5 AS bucket FROM range(0, 50)")
        seed.execute("CREATE TABLE main_orders AS SELECT range AS id FROM range(0, 50)")
        seed.close()

        from gateway.connectors.drivers.duckdb import DuckDBConnector

        c = DuckDBConnector()
        await c.connect(str(db_file))
        yield c
        await c.close()

    @pytest.mark.parametrize("payload", DUCKDB_PATH_PAYLOADS, ids=[p[:44] for p in DUCKDB_PATH_PAYLOADS])
    async def test_path_and_url_payloads_blocked_before_execution(self, connector, payload: str) -> None:
        spy = _CountingConnector(connector)
        with pytest.raises(GovernanceBlocked):
            await governed_execute(spy, payload, dialect=self.DIALECT)
        assert spy.calls == [], f"payload reached the DuckDB engine: {payload!r}"

    async def test_legitimate_table_read_works(self, connector) -> None:
        rows = await governed_execute(connector, "SELECT * FROM main_orders", dialect=self.DIALECT, max_rows=100)
        assert len(rows) == 50

    async def test_legitimate_schema_qualified_read_works(self, connector) -> None:
        rows = await governed_execute(
            connector, "SELECT id, bucket FROM analytics.orders ORDER BY id", dialect=self.DIALECT, max_rows=100
        )
        assert len(rows) == 50
        assert rows[0]["id"] == 0

    async def test_legitimate_join_and_aggregate_work(self, connector) -> None:
        rows = await governed_execute(
            connector,
            "SELECT o.bucket, COUNT(*) AS n FROM analytics.orders o "
            "JOIN main_orders m ON m.id = o.id GROUP BY o.bucket ORDER BY o.bucket",
            dialect=self.DIALECT,
            max_rows=100,
        )
        assert len(rows) == 5

    # ── END-TO-END LIMIT CAP ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM main_orders",
            "SELECT * FROM main_orders LIMIT ALL",
            "SELECT * FROM main_orders LIMIT 10000",
            "SELECT * FROM main_orders OFFSET 2",
        ],
        ids=["no-limit", "limit-all", "limit-10000", "offset-only"],
    )
    async def test_row_count_returned_equals_the_cap(self, connector, sql: str) -> None:
        rows = await governed_execute(connector, sql, dialect=self.DIALECT, max_rows=6)
        assert len(rows) == 6, f"cap not enforced end to end for {sql!r}: got {len(rows)} rows"

    async def test_limit_below_cap_is_honoured(self, connector) -> None:
        rows = await governed_execute(connector, "SELECT * FROM main_orders LIMIT 2", dialect=self.DIALECT, max_rows=6)
        assert len(rows) == 2

    # ── Defense in depth: DuckDB-level external access ──────────────────────

    async def test_raw_engine_still_reads_files_governance_is_the_only_barrier(self, connector) -> None:
        """Documents the CURRENT defense-in-depth posture, honestly.

        The DuckDB connector does not set ``enable_external_access=false``, so if
        governance were bypassed the engine itself would happily read a local
        file. This test asserts the state of the world so the gap is visible in
        the suite rather than implied away. It is paired with
        ``test_external_access_should_be_disabled_at_the_engine`` below.
        """
        import duckdb

        raw = duckdb.connect(":memory:")
        settings = {
            r[0]: r[1]
            for r in raw.execute(
                "SELECT name, value FROM duckdb_settings() WHERE name = 'enable_external_access'"
            ).fetchall()
        }
        raw.close()
        assert settings.get("enable_external_access") == "true"

    @pytest.mark.xfail(
        reason=(
            "NOT IMPLEMENTED: the DuckDB connector does not pass "
            "enable_external_access=false. Governance (validate_sql) is currently "
            "the only barrier against file/URL reads. Remove this xfail when the "
            "connector hardens the engine config."
        ),
        strict=False,
    )
    async def test_external_access_should_be_disabled_at_the_engine(self, connector) -> None:
        conn = connector._conn or connector._open_transient()
        value = conn.execute("SELECT value FROM duckdb_settings() WHERE name = 'enable_external_access'").fetchone()
        assert value is not None
        assert value[0] == "false"
