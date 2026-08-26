"""Verify the capture limits in gateway/evals/capture.py.

The capture path limits sample rows and streams PostgreSQL rows in batches.
The path replaces an oversized file with a truncation record. The tests use
an asyncpg connection test double.
"""

from __future__ import annotations

from typing import Any

import pytest

from gateway.evals import capture


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Cursor:
    """Async-iterable over pre-baked rows, honouring the SQL LIMIT."""

    def __init__(self, rows: list[tuple]):
        self._rows = list(rows)

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeConn:
    """The five methods capture.py actually uses on an asyncpg connection."""

    def __init__(self, columns: list[str], rows: list[tuple], est_bytes: int = 0):
        self.columns = columns
        self.rows = rows
        self.est_bytes = est_bytes
        self.cursor_sqls: list[str] = []
        self.closed = False

    async def fetch(self, sql: str, *args: Any):
        if "information_schema.columns" in sql:
            if "data_type" in sql:
                return [{"column_name": c, "data_type": "text"} for c in self.columns]
            return [{"column_name": c} for c in self.columns]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchval(self, sql: str, *args: Any):
        if "pg_total_relation_size" in sql:
            return self.est_bytes
        if "count(*)" in sql.lower():
            return len(self.rows)
        return None

    def transaction(self):
        return _Txn()

    def cursor(self, sql: str):
        self.cursor_sqls.append(sql)
        limit = None
        if " LIMIT " in sql:
            limit = int(sql.rsplit(" LIMIT ", 1)[1])
        return _Cursor(self.rows if limit is None else self.rows[:limit])

    async def close(self):
        self.closed = True


@pytest.fixture
def conn(monkeypatch: pytest.MonkeyPatch) -> FakeConn:
    fake = FakeConn(["id", "name"], [(1, "a"), (2, "b"), (3, None)])

    async def _fake_connect(dsn: str):
        return fake

    monkeypatch.setattr(capture, "_connect", _fake_connect)
    return fake


async def _run(spec: dict, *, byte_budget: int = 10_000_000, full_max_bytes: int = 10_000_000):
    return await capture.capture_tables(
        "postgres://ignored", spec, grain=[], byte_budget=byte_budget, full_max_bytes=full_max_bytes
    )


class TestSampleClamp:
    async def test_sample_rows_above_cap_is_clamped(self, conn: FakeConn) -> None:
        spec = {"mode": "fingerprint+sample", "sample_rows": 999_999, "tables": ["public.t"]}
        summary, files = await _run(spec)
        assert summary["sample_clamped"] is True
        assert len(files) == 1
        assert any(
            f"LIMIT {capture.MAX_SAMPLE_ROWS}" in s for s in conn.cursor_sqls
        ), conn.cursor_sqls
        assert not any("999999" in s for s in conn.cursor_sqls)
        assert conn.closed

    async def test_sample_rows_within_cap_is_untouched(self, conn: FakeConn) -> None:
        spec = {"mode": "fingerprint+sample", "sample_rows": 7, "tables": ["public.t"]}
        summary, files = await _run(spec)
        assert "sample_clamped" not in summary
        assert any("LIMIT 7" in s for s in conn.cursor_sqls)
        assert len(files) == 1


class TestOversizedFile:
    async def test_file_over_ceiling_becomes_truncated_note(self, conn: FakeConn) -> None:
        # An empty DuckDB file exceeds the 100-byte test limit.
        # The capture operation must discard the file.
        spec = {"mode": "fingerprint+sample", "sample_rows": 10, "tables": ["public.t"]}
        summary, files = await _run(spec, byte_budget=100)
        assert files == []
        entry = summary["tables"]["public.t"]
        assert "capture_truncated" in entry
        assert "fingerprint" in entry  # degraded, not failed
        assert summary["bytes"] == 0

    async def test_budget_exhaustion_second_table_degrades(self, conn: FakeConn) -> None:
        # Measure one file, then give a two-table capture just enough budget
        # for the first: the second must degrade to a truncated note.
        spec1 = {"mode": "fingerprint+sample", "sample_rows": 10, "tables": ["public.a"]}
        summary1, files1 = await _run(spec1)
        one_file = files1[0][1]

        spec2 = {
            "mode": "fingerprint+sample",
            "sample_rows": 10,
            "tables": ["public.a", "public.b"],
        }
        summary2, files2 = await _run(spec2, byte_budget=len(one_file) + 10)
        assert [f[0] for f in files2] == ["public_a.duckdb"]
        assert "file" in summary2["tables"]["public.a"]
        assert "capture_truncated" in summary2["tables"]["public.b"]
        assert summary2["bytes"] == len(files2[0][1])

    async def test_full_mode_precheck_still_refuses(self, conn: FakeConn) -> None:
        conn.est_bytes = 10**12
        spec = {"mode": "full", "tables": ["public.t"]}
        summary, files = await _run(spec, full_max_bytes=1_000_000)
        assert files == []
        assert "capture_refused" in summary["tables"]["public.t"]

    async def test_full_mode_applies_on_disk_ceiling(self, conn: FakeConn) -> None:
        conn.est_bytes = 50  # passes the pre-check, but the real file is >10KB
        spec = {"mode": "full", "tables": ["public.t"]}
        summary, files = await _run(spec, byte_budget=200, full_max_bytes=1_000_000)
        assert files == []
        assert "capture_truncated" in summary["tables"]["public.t"]


class TestStreaming:
    async def test_dump_streams_in_batches(self, conn: FakeConn, monkeypatch) -> None:
        batches: list[int] = []
        real = capture._stream_rows

        def spy(c, sql, batch_size=capture._INSERT_BATCH_ROWS):
            async def gen():
                async for b in real(c, sql, batch_size=2):
                    batches.append(len(b))
                    yield b

            return gen()

        monkeypatch.setattr(capture, "_stream_rows", spy)
        spec = {"mode": "fingerprint+sample", "sample_rows": 10, "tables": ["public.t"]}
        _, files = await _run(spec)
        assert len(files) == 1
        assert batches == [2, 1]  # 3 rows in 2-row batches, never one big fetch

    async def test_constants(self) -> None:
        assert capture.MAX_SAMPLE_ROWS == 50_000
        assert capture.MAX_CAPTURE_FILE_BYTES == 128 * 1024 * 1024
