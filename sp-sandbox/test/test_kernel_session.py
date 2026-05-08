"""Tests for KernelSession — async subprocess wrapper."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel_session import KernelSession


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.mark.asyncio
async def test_session_lifecycle(workdir):
    session = KernelSession("test-1", workdir)
    await session.start()
    assert session.status == "idle"
    assert session.is_alive

    r1 = await session.execute("x = 42", cell_id="c1")
    assert r1.success
    assert r1.cell_id == "c1"

    r2 = await session.execute("print(x)", cell_id="c2")
    assert r2.success
    assert r2.output.strip() == "42"

    assert session.cell_count == 2

    await session.kill()
    assert session.status == "dead"


@pytest.mark.asyncio
async def test_expression_display(workdir):
    session = KernelSession("test-2", workdir)
    await session.start()

    r = await session.execute("1 + 1")
    assert r.success
    assert r.output.strip() == "2"

    await session.kill()


@pytest.mark.asyncio
async def test_error_handling(workdir):
    session = KernelSession("test-3", workdir)
    await session.start()

    r = await session.execute("1 / 0")
    assert not r.success
    assert "ZeroDivisionError" in r.error

    # Session should still be alive after a cell error
    r2 = await session.execute("'ok'")
    assert r2.success

    await session.kill()


@pytest.mark.asyncio
async def test_bootstrap_injection(workdir):
    session = KernelSession("test-4", workdir)
    await session.start()

    await session.inject_bootstrap("_secret = 'injected'")
    assert session.cell_count == 0  # bootstrap not in history

    r = await session.execute("_secret")
    assert r.success
    assert "injected" in r.output

    await session.kill()


@pytest.mark.asyncio
async def test_history(workdir):
    session = KernelSession("test-5", workdir)
    await session.start()

    await session.execute("a = 1")
    await session.execute("b = 2")
    await session.execute("a + b")

    assert session.cell_count == 3
    assert session.history[2].output.strip() == "3"

    await session.kill()
