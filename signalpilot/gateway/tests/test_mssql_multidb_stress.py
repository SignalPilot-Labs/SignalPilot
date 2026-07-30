"""Multi-database stress tests for the SQL Server connector.

Exercises eight ~2 GB databases (~17 GB, ~11 M rows and 35 objects each) on a
single server, driven through the real PoolManager rather than bare connectors.

Load the fixture first:

    python tests/fixtures/load_mssql_stress.py --target-gb 2

The whole module skips when the fixture is absent, so CI stays green without it.
Set SP_STRESS_TARGET_MB to match a smaller --target-gb load.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

HOST = os.environ.get("SP_TEST_MSSQL_HOST", "127.0.0.1")
PORT = os.environ.get("SP_TEST_MSSQL_PORT", "1434")
PWD_URL = "Str0ng%21Passw0rd"

# Each database and the schema its objects live in.
DATABASES: dict[str, str] = {
    "sp_retail": "retail",
    "sp_finance": "finance",
    "sp_logistics": "logistics",
    "sp_marketing": "marketing",
    "sp_support": "support",
    "sp_iot": "telemetry",
    "sp_billing": "billing",
    "sp_hr": "people",
}

# Primary fact table per database — the largest object in each.
PRIMARY_FACT: dict[str, str] = {
    "sp_retail": "fact_orders",
    "sp_finance": "fact_ledger_entries",
    "sp_logistics": "fact_shipments",
    "sp_marketing": "fact_impressions",
    "sp_support": "fact_tickets",
    "sp_iot": "fact_sensor_readings",
    "sp_billing": "fact_charges",
    "sp_hr": "fact_timesheets",
}

# A loaded database is ~2 GB; allow generous slack for a smaller fixture load.
MIN_SIZE_MB = float(os.environ.get("SP_STRESS_TARGET_MB", "1500"))
EXPECTED_OBJECTS = 35


def url_for(db: str) -> str:
    return f"mssql://sa:{PWD_URL}@{HOST}:{PORT}/{db}"


def _fixture_loaded() -> bool:
    try:
        import pymssql
    except ImportError:
        return False
    try:
        conn = pymssql.connect(
            server=HOST, port=PORT, user="sa", password="Str0ng!Passw0rd",
            database="master", login_timeout=3, as_dict=True,
        )
        cur = conn.cursor(as_dict=True)
        placeholders = ",".join(["%s"] * len(DATABASES))
        cur.execute(
            f"SELECT COUNT(*) AS n FROM sys.databases WHERE name IN ({placeholders})",
            tuple(DATABASES),
        )
        n = cur.fetchone()["n"]
        conn.close()
        return n == len(DATABASES)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _fixture_loaded(),
    reason="multi-DB SQL Server fixture not loaded (see tests/fixtures/load_mssql_stress.py)",
)


@pytest.fixture
async def pool():
    from gateway.connectors.pool_manager import PoolManager

    pm = PoolManager()
    yield pm
    await pm.close_all()


# ── Fixture shape ───────────────────────────────────────────────────────────


class TestFixtureShape:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("db", list(DATABASES))
    async def test_each_database_is_loaded(self, pool, db):
        async with pool.connection("mssql", url_for(db)) as c:
            rows = await c.execute("""
                SELECT CAST(SUM(used_page_count) * 8.0 / 1024 AS FLOAT) AS mb,
                       SUM(CASE WHEN index_id IN (0,1) THEN row_count ELSE 0 END) AS rows_total
                FROM sys.dm_db_partition_stats""")
        assert rows[0]["mb"] >= MIN_SIZE_MB, f"{db} is only {rows[0]['mb']:.0f} MB"
        assert rows[0]["rows_total"] > 1_000_000

    @pytest.mark.asyncio
    @pytest.mark.parametrize("db", list(DATABASES))
    async def test_each_database_has_full_object_count(self, pool, db):
        async with pool.connection("mssql", url_for(db)) as c:
            rows = await c.execute("""
                SELECT COUNT(*) AS n FROM sys.objects
                WHERE type IN ('U','V') AND OBJECTPROPERTY(object_id,'IsMSShipped') = 0""")
        assert rows[0]["n"] == EXPECTED_OBJECTS

    @pytest.mark.asyncio
    async def test_databases_have_distinct_schemas(self, pool):
        """Each domain owns a differently-named schema — not eight identical copies."""
        found = set()
        for db, sch in DATABASES.items():
            async with pool.connection("mssql", url_for(db)) as c:
                rows = await c.execute(
                    "SELECT name FROM sys.schemas WHERE name = %s", params=[sch]
                )
            assert rows, f"{db} missing schema {sch}"
            found.add(sch)
        assert len(found) == len(DATABASES)


# ── Isolation between databases ─────────────────────────────────────────────


class TestDatabaseIsolation:
    @pytest.mark.asyncio
    async def test_each_connector_sees_only_its_own_database(self, pool):
        for db in DATABASES:
            async with pool.connection("mssql", url_for(db)) as c:
                rows = await c.execute("SELECT DB_NAME() AS current_db")
            assert rows[0]["current_db"] == db

    @pytest.mark.asyncio
    async def test_schema_introspection_excludes_other_databases(self, pool):
        async with pool.connection("mssql", url_for("sp_retail")) as c:
            schema = await c.get_schema()
        schemas = {v["schema"] for v in schema.values()}
        assert schemas == {"retail"}
        # A table unique to another domain must not leak in.
        assert not any("sensor" in k for k in schema)

    @pytest.mark.asyncio
    async def test_concurrent_connectors_do_not_cross_talk(self, pool):
        """Interleaved queries on 8 pooled connections must each stay in their own DB."""

        async def check(db: str) -> tuple[str, str]:
            async with pool.connection("mssql", url_for(db)) as c:
                for _ in range(3):
                    rows = await c.execute("SELECT DB_NAME() AS d")
                    await asyncio.sleep(0)
            return db, rows[0]["d"]

        results = await asyncio.gather(*(check(d) for d in DATABASES))
        assert all(expected == actual for expected, actual in results)


# ── Pool manager behaviour ──────────────────────────────────────────────────


class TestPoolManager:
    @pytest.mark.asyncio
    async def test_one_pool_per_database(self, pool):
        for db in DATABASES:
            async with pool.connection("mssql", url_for(db)) as c:
                await c.execute("SELECT 1 AS x")
        assert pool.pool_count == len(DATABASES)

    @pytest.mark.asyncio
    async def test_connection_is_reused_not_recreated(self, pool):
        first = await pool.acquire("mssql", url_for("sp_retail"))
        await pool.release("mssql", url_for("sp_retail"))
        second = await pool.acquire("mssql", url_for("sp_retail"))
        assert first is second
        assert pool.pool_count == 1

    @pytest.mark.asyncio
    async def test_stats_report_all_databases(self, pool):
        for db in DATABASES:
            await pool.acquire("mssql", url_for(db))
        stats = pool.stats()
        assert len(stats["pools"]) == len(DATABASES)
        assert all(p["db_type"] == "mssql" for p in stats["pools"])
        # Credentials must never appear in monitoring output.
        assert not any("Str0ng" in p["key"] for p in stats["pools"])

    @pytest.mark.asyncio
    async def test_close_all_releases_every_pool(self, pool):
        for db in DATABASES:
            await pool.acquire("mssql", url_for(db))
        assert pool.pool_count == len(DATABASES)
        await pool.close_all()
        assert pool.pool_count == 0


# ── Concurrent load across all eight databases ──────────────────────────────


class TestConcurrentLoad:
    @pytest.mark.asyncio
    async def test_parallel_connect_to_all_databases(self, pool):
        async def connect(db):
            async with pool.connection("mssql", url_for(db)) as c:
                return await c.health_check()

        results = await asyncio.gather(*(connect(d) for d in DATABASES))
        assert all(results)

    @pytest.mark.asyncio
    async def test_parallel_aggregations_over_large_facts(self, pool):
        """A GROUP BY across ~10 M rows, run on all 8 databases at once."""

        async def aggregate(db):
            sch, fact = DATABASES[db], PRIMARY_FACT[db]
            async with pool.connection("mssql", url_for(db)) as c:
                rows = await c.execute(f"""
                    SELECT status, COUNT_BIG(*) AS n
                    FROM {sch}.{fact}
                    GROUP BY status""")
            return db, rows

        t0 = time.monotonic()
        results = await asyncio.gather(*(aggregate(d) for d in DATABASES))
        elapsed = time.monotonic() - t0

        for db, rows in results:
            assert len(rows) >= 4, f"{db} returned too few status groups"
            assert sum(r["n"] for r in rows) > 1_000_000
        assert elapsed < 300, f"8-way parallel aggregation took {elapsed:.0f}s"

    @pytest.mark.asyncio
    async def test_parallel_schema_introspection(self, pool):
        """get_schema() fires 5 sys.* metadata queries; run all 8 concurrently."""

        async def introspect(db):
            async with pool.connection("mssql", url_for(db)) as c:
                return db, await c.get_schema()

        t0 = time.monotonic()
        results = await asyncio.gather(*(introspect(d) for d in DATABASES))
        elapsed = time.monotonic() - t0

        for db, schema in results:
            assert len(schema) == EXPECTED_OBJECTS, f"{db} introspected {len(schema)} objects"
            fact_key = f"{DATABASES[db]}.{PRIMARY_FACT[db]}"
            assert fact_key in schema
            assert schema[fact_key]["row_count"] > 1_000_000
            assert schema[fact_key]["columns"]
        assert elapsed < 300, f"8-way parallel introspection took {elapsed:.0f}s"

    @pytest.mark.asyncio
    async def test_parallel_unindexed_full_scans(self, pool):
        """8 concurrent scans of an unindexed varchar column — ~80 M rows of real IO.

        Nothing here can be answered from an index, so this exercises the driver
        while the server is genuinely saturated across all eight databases.
        """

        async def scan(db):
            sch, fact = DATABASES[db], PRIMARY_FACT[db]
            async with pool.connection("mssql", url_for(db)) as c:
                rows = await c.execute(
                    f"SELECT COUNT_BIG(*) AS n FROM {sch}.{fact} WHERE notes LIKE '%adjustment%'"
                )
            return db, rows[0]["n"]

        t0 = time.monotonic()
        results = await asyncio.gather(*(scan(d) for d in DATABASES))
        elapsed = time.monotonic() - t0

        for db, n in results:
            assert n > 0, f"{db} matched no rows — fixture may be malformed"
        assert elapsed < 600, f"8-way full scan took {elapsed:.0f}s"

    @pytest.mark.asyncio
    async def test_sustained_sequential_queries_on_one_connection(self, pool):
        """50 queries over a single pooled connection — catches cursor/state leaks."""
        async with pool.connection("mssql", url_for("sp_retail")) as c:
            for i in range(50):
                rows = await c.execute("SELECT %s AS i", params=[i])
                assert rows[0]["i"] == i
            assert await c.health_check() is True

    @pytest.mark.asyncio
    async def test_high_concurrency_on_single_database(self, pool):
        """32 concurrent queries share one pooled connector without corrupting results."""
        async with pool.connection("mssql", url_for("sp_retail")) as c:
            results = await asyncio.gather(
                *(c.execute("SELECT %s AS i", params=[i]) for i in range(32))
            )
        assert sorted(r[0]["i"] for r in results) == list(range(32))


# ── Governance under volume ─────────────────────────────────────────────────


class TestGovernanceAtScale:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("db", ["sp_retail", "sp_iot", "sp_finance"])
    async def test_injected_top_caps_unbounded_scan(self, pool, db):
        """SELECT * over a 10 M-row fact must come back bounded, not stream everything."""
        from gateway.engine import inject_limit, validate_sql

        sch, fact = DATABASES[db], PRIMARY_FACT[db]
        sql = f"SELECT * FROM {sch}.{fact}"
        assert validate_sql(sql, dialect="tsql").ok is True

        governed = inject_limit(sql, max_rows=1000, dialect="tsql")
        assert "TOP 1000" in governed

        async with pool.connection("mssql", url_for(db)) as c:
            t0 = time.monotonic()
            rows = await c.execute(governed)
            elapsed = time.monotonic() - t0

        assert len(rows) == 1000
        assert elapsed < 60, f"governed scan of {db} took {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_writes_blocked_on_every_database(self, pool):
        from gateway.engine import validate_sql

        for db in DATABASES:
            sch, fact = DATABASES[db], PRIMARY_FACT[db]
            for sql in (
                f"DELETE FROM {sch}.{fact}",
                f"UPDATE {sch}.{fact} SET status = 'x'",
                f"DROP TABLE {sch}.{fact}",
                f"TRUNCATE TABLE {sch}.{fact}",
            ):
                assert validate_sql(sql, dialect="tsql").ok is False, f"{db}: {sql} allowed"

    @pytest.mark.asyncio
    async def test_large_result_set_materializes(self, pool):
        """25k rows must come back intact as dicts — exercises the fetch loop."""
        sch, fact = DATABASES["sp_retail"], PRIMARY_FACT["sp_retail"]
        async with pool.connection("mssql", url_for("sp_retail")) as c:
            rows = await c.execute(
                f"SELECT TOP 25000 {fact}_key, status, amount FROM {sch}.{fact} ORDER BY {fact}_key"
            )
        assert len(rows) == 25_000
        assert rows[0][f"{fact}_key"] == 1
        assert all(isinstance(r, dict) for r in rows)


# ── Query shapes that matter on real warehouses ─────────────────────────────


class TestRealisticQueries:
    @pytest.mark.asyncio
    async def test_star_join_fact_to_dimension(self, pool):
        sch, fact = DATABASES["sp_retail"], PRIMARY_FACT["sp_retail"]
        async with pool.connection("mssql", url_for("sp_retail")) as c:
            rows = await c.execute(f"""
                SELECT TOP 20 d.region, COUNT_BIG(*) AS orders, SUM(f.amount) AS revenue
                FROM {sch}.{fact} f
                JOIN {sch}.dim_customer d ON d.customer_id = f.customer_id
                GROUP BY d.region
                ORDER BY revenue DESC""")
        assert rows
        assert {r["region"] for r in rows} <= {"NORTH", "SOUTH", "EAST", "WEST", "CENTRAL", "INTL"}
        assert all(r["orders"] > 0 for r in rows)

    @pytest.mark.asyncio
    async def test_window_function_over_large_table(self, pool):
        sch, fact = DATABASES["sp_billing"], PRIMARY_FACT["sp_billing"]
        async with pool.connection("mssql", url_for("sp_billing")) as c:
            rows = await c.execute(f"""
                SELECT TOP 100 status, event_date, amount,
                       ROW_NUMBER() OVER (PARTITION BY status ORDER BY amount DESC) AS rk
                FROM {sch}.{fact}
                WHERE event_date >= '2025-01-01'""")
        assert len(rows) == 100
        assert all(r["rk"] >= 1 for r in rows)

    @pytest.mark.asyncio
    async def test_view_query_across_databases(self, pool):
        for db in ("sp_retail", "sp_iot", "sp_hr"):
            sch, fact = DATABASES[db], PRIMARY_FACT[db]
            async with pool.connection("mssql", url_for(db)) as c:
                rows = await c.execute(
                    f"SELECT TOP 10 * FROM {sch}.v_{fact}_by_status"
                )
            assert rows, f"{db} view returned nothing"
            assert "row_count" in rows[0]

    @pytest.mark.asyncio
    async def test_sample_values_on_large_fact(self, pool):
        sch, fact = DATABASES["sp_logistics"], PRIMARY_FACT["sp_logistics"]
        async with pool.connection("mssql", url_for("sp_logistics")) as c:
            t0 = time.monotonic()
            result = await c.get_sample_values(f"{sch}.{fact}", ["status", "channel"], limit=5)
            elapsed = time.monotonic() - t0
        assert set(result) == {"status", "channel"}
        assert result["channel"]
        assert elapsed < 120, f"sampling a 10M-row table took {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_extended_property_comments_survive_at_scale(self, pool):
        """Regression guard: sql_variant comments must decode, not render as b'...'."""
        for db in DATABASES:
            async with pool.connection("mssql", url_for(db)) as c:
                schema = await c.get_schema()
            desc = schema[f"{DATABASES[db]}.{PRIMARY_FACT[db]}"]["description"]
            assert desc.startswith("Primary "), f"{db}: {desc!r}"
            assert not desc.startswith("b'")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
