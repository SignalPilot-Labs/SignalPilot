"""Blocking pymssql operations retain exclusive ownership without blocking asyncio."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from gateway.connectors.drivers import mssql


class FakeConnection:
    def __init__(self, entered=None, release=None):
        self.entered = entered
        self.release = release
        self.closed = False
        self.description = ("ok",)

    def cursor(self, **kwargs):
        return self

    def execute(self, *args):
        if self.entered:
            self.entered.set()
            assert self.release.wait(2)

    def fetchall(self):
        return [{"ok": 1}]

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_connect_runs_blocking_auth_login_and_setup_off_loop(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    conn = FakeConnection()
    loop_thread = threading.get_ident()
    def connect(**kwargs):
        assert threading.get_ident() != loop_thread
        assert kwargs["login_timeout"] > 0 and kwargs["timeout"] > 0
        entered.set()
        assert release.wait(2)
        return conn
    monkeypatch.setattr(mssql, "HAS_PYMSSQL", True)
    monkeypatch.setattr(mssql, "pymssql", SimpleNamespace(connect=connect, OperationalError=OSError), raising=False)
    driver = mssql.MSSQLConnector()
    task = asyncio.create_task(driver.connect("mssql://reader:example@db.invalid/example"))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await asyncio.sleep(.01)
        assert not task.done()
    finally:
        release.set()
    await task
    assert driver._conn is conn


@pytest.mark.asyncio
async def test_health_ping_does_not_block_event_loop():
    entered, release = threading.Event(), threading.Event()
    driver = mssql.MSSQLConnector()
    driver._conn = FakeConnection(entered, release)
    task = asyncio.create_task(driver.health_check())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await asyncio.sleep(.01)
        assert not task.done()
    finally:
        release.set()
    assert await task is True


@pytest.mark.asyncio
async def test_cancelled_health_retains_lock_until_worker_finishes_and_discards():
    entered, release = threading.Event(), threading.Event()
    driver = mssql.MSSQLConnector()
    connection = FakeConnection(entered, release)
    driver._conn = connection
    task = asyncio.create_task(driver.health_check())
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(.01)
    task.cancel()  # Repeated cancellation must not escape the drain.
    competitor = asyncio.create_task(driver._conn_lock.acquire())
    await asyncio.sleep(.01)
    assert not task.done() and not competitor.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await competitor
    driver._conn_lock.release()
    assert driver._conn is None and connection.closed


@pytest.mark.asyncio
async def test_close_waits_for_worker_ownership():
    entered, release = threading.Event(), threading.Event()
    driver = mssql.MSSQLConnector()
    driver._conn = FakeConnection(entered, release)
    health = asyncio.create_task(driver.health_check())
    assert await asyncio.to_thread(entered.wait, 1)
    close = asyncio.create_task(driver.close())
    await asyncio.sleep(.01)
    assert not close.done()
    release.set()
    assert await health
    await close
    assert driver._conn is None


@pytest.mark.asyncio
async def test_cancelled_query_drains_before_handle_can_be_reused(monkeypatch):
    monkeypatch.setattr(mssql, "pymssql", SimpleNamespace(Error=OSError), raising=False)
    entered, release = threading.Event(), threading.Event()
    driver = mssql.MSSQLConnector()
    driver._conn = FakeConnection(entered, release)
    query = asyncio.create_task(driver._execute_impl("SELECT 1", timeout=1))
    assert await asyncio.to_thread(entered.wait, 1)
    query.cancel()
    await asyncio.sleep(.01)
    assert not query.done() and driver._conn_lock.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await query
    assert driver._conn is None


@pytest.mark.asyncio
async def test_connect_setup_failure_closes_partial_connection(monkeypatch):
    class BrokenConnection(FakeConnection):
        def execute(self, *args):
            raise ValueError("setup failed")
    connection = BrokenConnection()
    monkeypatch.setattr(mssql, "HAS_PYMSSQL", True)
    monkeypatch.setattr(mssql, "pymssql", SimpleNamespace(connect=lambda **kw: connection, OperationalError=OSError), raising=False)
    driver = mssql.MSSQLConnector()
    with pytest.raises(ValueError):
        await driver.connect("mssql://reader:example@db.invalid/example")
    assert connection.closed and driver._conn is None


@pytest.mark.asyncio
async def test_worker_timeout_does_not_abandon_thread():
    entered, release = threading.Event(), threading.Event()
    driver = mssql.MSSQLConnector()
    connection = FakeConnection()
    driver._conn = connection
    def blocking():
        entered.set()
        assert release.wait(2)
    # The helper adds a five-second grace; use a short effective test deadline.
    task = asyncio.create_task(driver._run_in_thread(blocking, timeout=-4.98))
    assert await asyncio.to_thread(entered.wait, 1)
    await asyncio.sleep(.04)
    assert not task.done() and not connection.closed
    release.set()
    with pytest.raises(RuntimeError, match="timed out"):
        await task
    assert driver._conn is None and connection.closed
