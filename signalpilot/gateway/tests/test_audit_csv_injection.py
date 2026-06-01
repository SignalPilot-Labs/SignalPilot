"""Tests for M-5: CSV formula-injection neutralization in /api/audit/export?format=csv.

Verifies that user/agent-controlled fields starting with formula-trigger
characters are prefixed with a single apostrophe per OWASP guidance, and that
benign values pass through unchanged.
"""

from __future__ import annotations

import csv
import io
import json
from unittest.mock import AsyncMock

import pytest

from gateway.api.audit import export_audit

# ─── Shared helper ────────────────────────────────────────────────────────────


def _make_entry(**kwargs: object) -> dict:
    """Return a minimal audit entry dict, overriding any fields via kwargs."""
    base: dict = {
        "id": "abc-123",
        "timestamp": "2024-01-01T00:00:00Z",
        "event_type": "read_query",
        "connection_name": "prod_db",
        "sql": "SELECT 1",
        "tables": [],
        "rows_returned": 1,
        "duration_ms": 5,
        "blocked": False,
        "block_reason": "",
        "agent_id": "agent-1",
        "metadata": {},
    }
    base.update(kwargs)
    return base


async def _run_export(entries: list[dict]) -> list[list[str]]:
    """Invoke export_audit with a mocked store and return parsed CSV rows."""
    store = AsyncMock()
    store.read_audit = AsyncMock(return_value=entries)
    resp = await export_audit(
        store=store,
        limit=None,
        connection_name=None,
        event_type=None,
        format="csv",
    )
    chunks = [chunk async for chunk in resp.body_iterator]
    if chunks and isinstance(chunks[0], bytes):
        body = b"".join(chunks).decode()  # type: ignore[arg-type]
    else:
        body = "".join(chunks)  # type: ignore[arg-type]
    return list(csv.reader(io.StringIO(body)))


# ─── Test class ───────────────────────────────────────────────────────────────


class TestAuditCsvInjection:
    """Verify CSV formula-injection mitigation in the audit export endpoint."""

    @pytest.mark.asyncio
    async def test_formula_trigger_equals(self):
        """sql starting with '=' must be prefixed with apostrophe."""
        payload = '=WEBSERVICE("http://x")'
        rows = await _run_export([_make_entry(sql=payload)])
        # Row 0 is the header; row 1 is data. sql is column index 4.
        sql_cell = rows[1][4]
        assert sql_cell == "'" + payload

    @pytest.mark.asyncio
    async def test_formula_trigger_plus(self):
        """connection_name starting with '+' must be prefixed with apostrophe."""
        rows = await _run_export([_make_entry(connection_name="+attack")])
        conn_cell = rows[1][3]
        assert conn_cell.startswith("'+")

    @pytest.mark.asyncio
    async def test_formula_trigger_minus(self):
        """block_reason starting with '-' must be prefixed with apostrophe."""
        rows = await _run_export([_make_entry(block_reason="-1+1")])
        block_reason_cell = rows[1][9]
        assert block_reason_cell.startswith("'-")

    @pytest.mark.asyncio
    async def test_formula_trigger_at(self):
        """agent_id starting with '@' must be prefixed with apostrophe."""
        rows = await _run_export([_make_entry(agent_id="@SUM(A1)")])
        agent_cell = rows[1][10]
        assert agent_cell.startswith("'@")

    @pytest.mark.asyncio
    async def test_formula_trigger_tab(self):
        """sql starting with tab must be prefixed with apostrophe."""
        rows = await _run_export([_make_entry(sql="\t=cmd")])
        sql_cell = rows[1][4]
        assert sql_cell.startswith("'\t")

    @pytest.mark.asyncio
    async def test_formula_trigger_cr(self):
        """sql starting with carriage return must be prefixed with apostrophe."""
        rows = await _run_export([_make_entry(sql="\rinject")])
        sql_cell = rows[1][4]
        assert sql_cell.startswith("'\r")

    @pytest.mark.asyncio
    async def test_benign_values_unchanged(self):
        """Benign values must pass through without any leading apostrophe."""
        rows = await _run_export(
            [_make_entry(sql="SELECT 1", event_type="read_query", connection_name="prod_db")]
        )
        data_row = rows[1]
        # event_type col 2, connection_name col 3, sql col 4
        assert data_row[2] == "read_query"
        assert data_row[3] == "prod_db"
        assert data_row[4] == "SELECT 1"
        # None of the cells should start with apostrophe
        for cell in data_row:
            assert not cell.startswith("'"), f"Unexpected apostrophe in cell: {cell!r}"

    @pytest.mark.asyncio
    async def test_none_and_empty_stay_empty(self):
        """None and empty-string fields must produce empty CSV cells."""
        rows = await _run_export(
            [_make_entry(sql=None, block_reason=None, agent_id="")]
        )
        data_row = rows[1]
        sql_cell = data_row[4]
        block_reason_cell = data_row[9]
        agent_cell = data_row[10]
        assert sql_cell == ""
        assert block_reason_cell == ""
        assert agent_cell == ""

    @pytest.mark.asyncio
    async def test_metadata_json_with_trigger_neutralized(self):
        """metadata column contains json.dumps output; confirm it passes through _csv_safe.

        json.dumps of a dict always starts with '{', which is not a trigger char,
        so the cell must equal the literal json.dumps output with no apostrophe.
        """
        metadata = {"key": "value", "count": 42}
        rows = await _run_export([_make_entry(metadata=metadata)])
        metadata_cell = rows[1][11]
        expected = json.dumps(metadata)
        assert metadata_cell == expected
        assert not metadata_cell.startswith("'")
