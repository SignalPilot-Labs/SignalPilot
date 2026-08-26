"""Verify serialized access to synchronous connector drivers.

PoolManager stores one connector for each connection string. Concurrent callers
share that connector. Each synchronous driver uses an internal lock because its
database handle cannot process concurrent statements.

Each driver skips independently when its database is unreachable.
"""

from __future__ import annotations

import asyncio

import pytest

CONCURRENCY = 32

# Map each database type to its connection URL.
# The Redshift driver uses psycopg2 and the PostgreSQL wire protocol.
TARGETS: dict[str, str] = {
    "mssql": "mssql://sa:Str0ng%21Passw0rd@127.0.0.1:1434/sp_test",
    "mysql": "mysql://root:Test1234%21@127.0.0.1:3307/test_analytics",
    "clickhouse": "clickhouse://default:test123@127.0.0.1:8123/default",
    "redshift": "redshift://postgres:Test1234@127.0.0.1:5610/test_analytics",
}


async def _try_connect(db_type: str):
    """Return a connected connector, or None when the database is unavailable."""
    from gateway.connectors.registry import get_connector

    try:
        c = get_connector(db_type)
        await c.connect(TARGETS[db_type])
        return c
    except Exception:
        return None


@pytest.fixture(params=list(TARGETS))
async def connector(request):
    c = await _try_connect(request.param)
    if c is None:
        pytest.skip(f"{request.param} not reachable")
    c._db_type_label = request.param
    yield c
    await c.close()


def _select_int(db_type: str, i: int) -> tuple[str, list | None]:
    """A query returning exactly the integer i, in each dialect."""
    if db_type == "clickhouse":
        return f"SELECT {i} AS i", None
    return "SELECT %s AS i", [i]


class TestConcurrentExecute:
    @pytest.mark.asyncio
    async def test_concurrent_queries_return_their_own_rows(self, connector):
        """Verify that 32 concurrent queries return their own results."""
        db_type = connector._db_type_label

        async def one(i: int) -> int:
            sql, params = _select_int(db_type, i)
            rows = await connector.execute(sql, params=params)
            return int(next(iter(rows[0].values())))

        results = await asyncio.gather(*(one(i) for i in range(CONCURRENCY)))
        assert sorted(results) == list(range(CONCURRENCY))

    @pytest.mark.asyncio
    async def test_connection_survives_concurrent_burst(self, connector):
        db_type = connector._db_type_label
        sql, params = _select_int(db_type, 1)
        await asyncio.gather(*(connector.execute(sql, params=params) for _ in range(CONCURRENCY)))
        assert await connector.health_check() is True

    @pytest.mark.asyncio
    async def test_repeated_bursts_do_not_degrade(self, connector):
        """Verify the lock state with three consecutive query bursts."""
        db_type = connector._db_type_label

        async def one(i: int) -> int:
            sql, params = _select_int(db_type, i)
            rows = await connector.execute(sql, params=params)
            return int(next(iter(rows[0].values())))

        for _ in range(3):
            results = await asyncio.gather(*(one(i) for i in range(16)))
            assert sorted(results) == list(range(16))


class TestConcurrentMixedOperations:
    @pytest.mark.asyncio
    async def test_schema_introspection_concurrent_with_queries(self, connector):
        """Verify that get_schema and execute do not use the connection concurrently."""
        db_type = connector._db_type_label

        async def query(i: int) -> int:
            sql, params = _select_int(db_type, i)
            rows = await connector.execute(sql, params=params)
            return int(next(iter(rows[0].values())))

        async def introspect():
            return await connector.get_schema()

        results = await asyncio.gather(introspect(), *(query(i) for i in range(8)), introspect())
        schema_a, *values, schema_b = results
        assert sorted(values) == list(range(8))
        assert isinstance(schema_a, dict)
        assert isinstance(schema_b, dict)

    @pytest.mark.asyncio
    async def test_health_check_concurrent_with_queries(self, connector):
        """Verify that a health check does not overlap an active query.

        PoolManager uses the shared connection for each acquisition health check.
        """
        db_type = connector._db_type_label

        async def query(i: int) -> int:
            sql, params = _select_int(db_type, i)
            rows = await connector.execute(sql, params=params)
            return int(next(iter(rows[0].values())))

        results = await asyncio.gather(
            *(query(i) for i in range(12)),
            *(connector.health_check() for _ in range(12)),
        )
        # Split by position because bool is a subclass of int.
        values, healths = results[:12], results[12:]
        assert sorted(values) == list(range(12))
        assert all(healths)

    @pytest.mark.asyncio
    async def test_queries_still_work_after_concurrent_introspection(self, connector):
        db_type = connector._db_type_label
        await asyncio.gather(*(connector.get_schema() for _ in range(3)))
        sql, params = _select_int(db_type, 99)
        rows = await connector.execute(sql, params=params)
        assert int(next(iter(rows[0].values()))) == 99


class TestLockPresence:
    """Verify that each synchronous connector contains a serialization lock."""

    @pytest.mark.parametrize("module_name", ["mssql", "mysql", "clickhouse"])
    def test_driver_declares_connection_lock(self, module_name):
        import importlib

        mod = importlib.import_module(f"gateway.connectors.drivers.{module_name}")
        cls = next(
            v
            for k, v in vars(mod).items()
            if k.endswith("Connector") and isinstance(v, type) and v.__module__ == mod.__name__
        )
        instance = cls()
        assert isinstance(instance._conn_lock, asyncio.Lock), (
            f"{cls.__name__} must serialize access to its non-multiplexable connection"
        )

    @pytest.mark.parametrize("module_name", ["mssql", "mysql", "clickhouse"])
    def test_execute_and_schema_paths_acquire_the_lock(self, module_name):
        import importlib
        import inspect

        mod = importlib.import_module(f"gateway.connectors.drivers.{module_name}")
        cls = next(
            v
            for k, v in vars(mod).items()
            if k.endswith("Connector") and isinstance(v, type) and v.__module__ == mod.__name__
        )
        for method in ("_execute_impl", "_get_schema_impl", "_get_sample_values_impl"):
            source = inspect.getsource(getattr(cls, method))
            assert "_conn_lock" in source, f"{cls.__name__}.{method} does not take the lock"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
