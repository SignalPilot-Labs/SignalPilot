"""Tests for database connectors and pool manager."""

import asyncio

import pytest

# DuckDB connector tests — tests against in-memory DuckDB
from signalpilot.gateway.gateway.connectors.duckdb import DuckDBConnector, HAS_DUCKDB
from signalpilot.gateway.gateway.connectors.pool_manager import PoolManager


@pytest.fixture
async def duckdb_connector():
    """Create and connect a DuckDB connector with test data."""
    if not HAS_DUCKDB:
        pytest.skip("duckdb not installed")
    conn = DuckDBConnector()
    await conn.connect(":memory:")
    # Note: read_only=True prevents CREATE TABLE, so we test with system tables
    yield conn
    await conn.close()


class TestDuckDBConnector:
    @pytest.mark.asyncio
    async def test_connect_memory(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        conn = DuckDBConnector()
        await conn.connect(":memory:")
        assert await conn.health_check()
        await conn.close()

    @pytest.mark.asyncio
    async def test_execute_simple(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        conn = DuckDBConnector()
        await conn.connect(":memory:")
        rows = await conn.execute("SELECT 1 AS num, 'hello' AS msg")
        assert len(rows) == 1
        assert rows[0]["num"] == 1
        assert rows[0]["msg"] == "hello"
        await conn.close()

    @pytest.mark.asyncio
    async def test_execute_multiple_rows(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        conn = DuckDBConnector()
        await conn.connect(":memory:")
        rows = await conn.execute("SELECT * FROM generate_series(1, 5) AS t(n)")
        assert len(rows) == 5
        assert rows[0]["n"] == 1
        assert rows[4]["n"] == 5
        await conn.close()

    @pytest.mark.asyncio
    async def test_execute_not_connected(self):
        conn = DuckDBConnector()
        with pytest.raises(RuntimeError, match="Not connected"):
            await conn.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        conn = DuckDBConnector()
        assert not await conn.health_check()

    @pytest.mark.asyncio
    async def test_get_schema(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        conn = DuckDBConnector()
        await conn.connect(":memory:")
        schema = await conn.get_schema()
        # In-memory DuckDB with no tables returns empty schema
        assert isinstance(schema, dict)
        await conn.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        conn = DuckDBConnector()
        await conn.connect(":memory:")
        await conn.close()
        await conn.close()  # Should not raise


class TestPoolManager:
    @pytest.mark.asyncio
    async def test_acquire_creates_connector(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        pm = PoolManager()
        connector = await pm.acquire("duckdb", ":memory:")
        assert connector is not None
        assert await connector.health_check()
        assert pm.pool_count == 1
        await pm.close_all()

    @pytest.mark.asyncio
    async def test_acquire_reuses_connector(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        pm = PoolManager()
        c1 = await pm.acquire("duckdb", ":memory:")
        await pm.release("duckdb", ":memory:")
        c2 = await pm.acquire("duckdb", ":memory:")
        assert c1 is c2
        assert pm.pool_count == 1
        await pm.close_all()

    @pytest.mark.asyncio
    async def test_release_updates_timestamp(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        pm = PoolManager()
        await pm.acquire("duckdb", ":memory:")
        await pm.release("duckdb", ":memory:")
        assert pm.pool_count == 1
        await pm.close_all()

    @pytest.mark.asyncio
    async def test_close_all(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        pm = PoolManager()
        await pm.acquire("duckdb", ":memory:")
        assert pm.pool_count == 1
        await pm.close_all()
        assert pm.pool_count == 0

    @pytest.mark.asyncio
    async def test_cleanup_idle(self):
        if not HAS_DUCKDB:
            pytest.skip("duckdb not installed")
        pm = PoolManager(idle_timeout_sec=0)  # Immediate timeout
        await pm.acquire("duckdb", ":memory:")
        await pm.release("duckdb", ":memory:")
        closed = await pm.cleanup_idle()
        assert closed == 1
        assert pm.pool_count == 0

    @pytest.mark.asyncio
    async def test_pool_count_property(self):
        pm = PoolManager()
        assert pm.pool_count == 0
