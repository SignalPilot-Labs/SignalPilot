"""Tests for the connection pool manager (MED-06 fix)."""

import asyncio
import time

import pytest

from signalpilot.gateway.gateway.connectors.base import BaseConnector
from signalpilot.gateway.gateway.connectors.pool_manager import PoolManager


class MockConnector(BaseConnector):
    """Mock connector for testing pool manager."""

    def __init__(self):
        self.connected = False
        self.closed = False
        self.connect_count = 0
        self.close_count = 0
        self.healthy = True

    async def connect(self, connection_string: str) -> None:
        self.connected = True
        self.connect_count += 1

    async def execute(self, sql, params=None, timeout=None):
        return [{"result": 1}]

    async def get_schema(self):
        return {}

    async def health_check(self) -> bool:
        return self.healthy

    async def close(self) -> None:
        self.closed = True
        self.connected = False
        self.close_count += 1


# Patch the registry so pool_manager can create MockConnectors
@pytest.fixture(autouse=True)
def patch_registry(monkeypatch):
    """Make get_connector return MockConnectors."""
    from signalpilot.gateway.gateway.connectors import pool_manager as pm_module

    def mock_get_connector(db_type: str) -> MockConnector:
        return MockConnector()

    monkeypatch.setattr(pm_module, "get_connector", mock_get_connector)


class TestPoolManager:
    """Tests for PoolManager."""

    @pytest.mark.asyncio
    async def test_acquire_creates_new_connector(self):
        pool = PoolManager()
        connector = await pool.acquire("postgres", "postgresql://test")
        assert isinstance(connector, MockConnector)
        assert connector.connected is True
        assert pool.pool_count == 1

    @pytest.mark.asyncio
    async def test_acquire_reuses_connector(self):
        pool = PoolManager()
        c1 = await pool.acquire("postgres", "postgresql://test")
        c2 = await pool.acquire("postgres", "postgresql://test")
        assert c1 is c2  # Same instance
        assert pool.pool_count == 1

    @pytest.mark.asyncio
    async def test_different_connections_get_different_pools(self):
        pool = PoolManager()
        c1 = await pool.acquire("postgres", "postgresql://db1")
        c2 = await pool.acquire("postgres", "postgresql://db2")
        assert c1 is not c2
        assert pool.pool_count == 2

    @pytest.mark.asyncio
    async def test_different_db_types_get_different_pools(self):
        pool = PoolManager()
        c1 = await pool.acquire("postgres", "conn_str")
        c2 = await pool.acquire("duckdb", "conn_str")
        assert c1 is not c2
        assert pool.pool_count == 2

    @pytest.mark.asyncio
    async def test_release_updates_last_used(self):
        pool = PoolManager()
        await pool.acquire("postgres", "test_conn")
        # Release should not raise
        await pool.release("postgres", "test_conn")
        assert pool.pool_count == 1

    @pytest.mark.asyncio
    async def test_release_nonexistent_is_noop(self):
        pool = PoolManager()
        await pool.release("postgres", "nonexistent")
        assert pool.pool_count == 0

    @pytest.mark.asyncio
    async def test_cleanup_idle_removes_stale(self):
        pool = PoolManager(idle_timeout_sec=0)  # Expire immediately
        connector = await pool.acquire("postgres", "test")
        # Wait a tiny bit to ensure monotonic time advances
        await asyncio.sleep(0.01)
        closed = await pool.cleanup_idle()
        assert closed == 1
        assert pool.pool_count == 0
        assert connector.closed is True

    @pytest.mark.asyncio
    async def test_cleanup_idle_keeps_active(self):
        pool = PoolManager(idle_timeout_sec=300)
        await pool.acquire("postgres", "test")
        closed = await pool.cleanup_idle()
        assert closed == 0
        assert pool.pool_count == 1

    @pytest.mark.asyncio
    async def test_close_all(self):
        pool = PoolManager()
        c1 = await pool.acquire("postgres", "conn1")
        c2 = await pool.acquire("postgres", "conn2")
        await pool.close_all()
        assert pool.pool_count == 0
        assert c1.closed is True
        assert c2.closed is True

    @pytest.mark.asyncio
    async def test_unhealthy_connector_recreated(self):
        pool = PoolManager()
        c1 = await pool.acquire("postgres", "test")
        # Mark as unhealthy
        c1.healthy = False
        # Should create a new connector
        c2 = await pool.acquire("postgres", "test")
        assert c2 is not c1
        assert c1.closed is True  # Old one was closed
        assert pool.pool_count == 1

    @pytest.mark.asyncio
    async def test_pool_count_property(self):
        pool = PoolManager()
        assert pool.pool_count == 0
        await pool.acquire("postgres", "c1")
        assert pool.pool_count == 1
        await pool.acquire("postgres", "c2")
        assert pool.pool_count == 2
        await pool.close_all()
        assert pool.pool_count == 0
