import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.connectors.pool_manager import PoolManager


@pytest.fixture
def factory(monkeypatch):
    created = []

    def create(_):
        conn = MagicMock()
        conn.connect = AsyncMock()
        conn.health_check = AsyncMock(return_value=True)
        conn.close = AsyncMock()
        created.append(conn)
        return conn

    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
    monkeypatch.setattr("gateway.connectors.pool_manager.get_connector", create)
    return created


@pytest.mark.asyncio
async def test_five_distinct_leases_queue_sixth_and_preserve_query_state(factory):
    pm = PoolManager(max_connections=5, acquire_timeout_sec=2)
    full, release = asyncio.Event(), asyncio.Event()
    acquired = []

    async def query(index):
        async with pm.connection("postgres", "dsn") as connector:
            connector.query_id = index
            acquired.append(connector)
            if len(acquired) == 5:
                full.set()
            await release.wait()
            assert connector.query_id == index

    tasks = [asyncio.create_task(query(n)) for n in range(5)]
    await asyncio.wait_for(full.wait(), 1)
    assert len({id(connector) for connector in acquired}) == 5
    sixth = asyncio.create_task(query(5))
    await asyncio.sleep(0.02)
    assert len(acquired) == 5
    release.set()
    await asyncio.gather(*tasks, sixth)
    assert len(factory) == 5
    acquired.clear()
    full.clear()
    release.clear()
    warm = [asyncio.create_task(query(n)) for n in range(5)]
    await asyncio.wait_for(full.wait(), 1)
    assert len({id(connector) for connector in acquired}) == 5
    release.set()
    await asyncio.gather(*warm)
    assert len(factory) == 5
    assert not pm._checkout_owners
    await pm.close_all()


@pytest.mark.asyncio
async def test_idle_cleanup_never_closes_active_lease(factory):
    pm = PoolManager(idle_timeout_sec=-1)
    async with pm.connection("postgres", "dsn") as conn:
        assert await pm.cleanup_idle() == 0
        conn.close.assert_not_awaited()
    assert await pm.cleanup_idle() == 1
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_cancelled_waiter_and_nonowner_release(factory):
    pm = PoolManager(max_connections=1, acquire_timeout_sec=0.05)
    held = await pm.acquire("postgres", "dsn")

    async def foreign_release():
        await pm.release("postgres", "dsn")

    await asyncio.create_task(foreign_release())
    assert pm._checkout_owners
    with pytest.raises(RuntimeError, match="pool acquisition timed out"):
        await asyncio.create_task(pm.acquire("postgres", "dsn"))
    waiter = asyncio.create_task(pm.acquire("postgres", "dsn"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await pm.release("postgres", "dsn")
    assert await pm.acquire("postgres", "dsn") is held
    await pm.release("postgres", "dsn")
    await pm.close_all()


@pytest.mark.asyncio
async def test_nested_leases_restore_audit_name_and_deferred_close(factory):
    pm = PoolManager()
    async with pm.connection("postgres", "dsn", connection_name="outer") as outer:
        async with pm.connection("postgres", "dsn", connection_name="inner") as inner:
            assert outer is inner and inner._audit_connection_name == "inner"
        assert outer._audit_connection_name == "outer"
        await pm.close_all()
        outer.close.assert_not_awaited()
    outer.close.assert_awaited_once()
    assert pm.pool_count == 0 and not pm._checkout_owners


@pytest.mark.asyncio
async def test_cold_connections_do_not_hold_global_lock(factory, monkeypatch):
    pm = PoolManager(max_connections=2)
    started, release = asyncio.Event(), asyncio.Event()

    async def connect(*args):
        started.set()
        await release.wait()

    original = __import__("gateway.connectors.pool_manager", fromlist=["get_connector"]).get_connector

    def create(db_type):
        conn = original(db_type)
        if len(factory) == 1:
            conn.connect.side_effect = connect
        return conn

    monkeypatch.setattr("gateway.connectors.pool_manager.get_connector", create)

    async def held():
        async with pm.connection("postgres", "first"):
            pass

    first = asyncio.create_task(held())
    await asyncio.wait_for(started.wait(), 1)
    other = await asyncio.wait_for(pm.acquire("postgres", "other"), 1)
    await pm.release("postgres", "other")
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    factory[0].close.assert_awaited()
    assert other is factory[1]
    assert not pm._checkout_owners
    await pm.close_all()


@pytest.mark.asyncio
async def test_file_engines_retain_single_slot(factory):
    pm = PoolManager(max_connections=20, acquire_timeout_sec=0.03)
    async with pm.connection("duckdb", "project.duckdb"):
        with pytest.raises(RuntimeError, match="pool acquisition timed out"):
            await asyncio.create_task(pm.acquire("duckdb", "project.duckdb"))
    assert len(factory) == 1
    await pm.close_all()


@pytest.mark.asyncio
async def test_slow_close_does_not_block_other_pool_and_cancelled_query_retires(factory):
    pm = PoolManager(max_connections=1)
    running, closing, finish_close = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def slow_close():
        closing.set()
        await finish_close.wait()

    async def query():
        async with pm.connection("postgres", "first") as conn:
            conn.close.side_effect = slow_close
            running.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(query())
    await asyncio.wait_for(running.wait(), 1)
    task.cancel()
    await asyncio.wait_for(closing.wait(), 1)
    other = await asyncio.wait_for(pm.acquire("postgres", "other"), 1)
    assert other is not factory[0]
    await pm.release("postgres", "other")
    finish_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not pm._checkout_owners
    replacement = await pm.acquire("postgres", "first")
    assert replacement is not factory[0]
    await pm.release("postgres", "first")
    await pm.close_all()
