"""Tests for KernelSessionManager."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_manager import KernelSessionManager


@pytest.mark.asyncio
async def test_create_and_execute():
    mgr = KernelSessionManager()
    session = await mgr.create_session()
    assert session.status == "idle"

    r = await session.execute("x = 10")
    assert r.success

    r2 = await session.execute("x * 2")
    assert r2.success
    assert r2.output.strip() == "20"

    await mgr.cleanup()


@pytest.mark.asyncio
async def test_list_and_delete():
    mgr = KernelSessionManager()
    s1 = await mgr.create_session()
    s2 = await mgr.create_session()

    sessions = mgr.list_sessions()
    assert len(sessions) == 2

    deleted = await mgr.delete_session(s1.id)
    assert deleted

    sessions = mgr.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].id == s2.id

    await mgr.cleanup()


@pytest.mark.asyncio
async def test_restart_session():
    mgr = KernelSessionManager()
    s = await mgr.create_session(session_id="restart-test")

    await s.execute("y = 99")
    r = await s.execute("y")
    assert "99" in r.output

    s2 = await mgr.restart_session("restart-test")
    assert s2.id == "restart-test"
    assert s2.cell_count == 0

    # Old variable should be gone
    r2 = await s2.execute("y")
    assert not r2.success

    await mgr.cleanup()


@pytest.mark.asyncio
async def test_get_session():
    mgr = KernelSessionManager()
    s = await mgr.create_session(session_id="lookup-test")

    found = mgr.get_session("lookup-test")
    assert found is not None
    assert found.id == "lookup-test"

    assert mgr.get_session("nonexistent") is None

    await mgr.cleanup()
