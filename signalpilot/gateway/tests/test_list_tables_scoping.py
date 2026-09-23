"""list_tables scoping and byte budget (chat failure plan section F), plus the
generic result budget in the audited-tool wrapper."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gateway.connectors.schema_cache import schema_cache
from gateway.mcp import audit
from gateway.mcp.tools.schema import catalog
from gateway.standalone_chat.tool_projection import project_tool_result

_TOOL = "mcp__signalpilot__list_tables"


def _schema(count: int, *, columns: int = 3, schemas: tuple[str, ...] = ("dbo", "sales")) -> dict:
    schema = {}
    for i in range(count):
        schema_name = schemas[i % len(schemas)]
        name = f"orders_{i:03d}" if i % 3 else f"customers_{i:03d}"
        schema[f"{schema_name}.{name}"] = {
            "schema": schema_name,
            "name": name,
            "row_count": i * 1000,
            "columns": [{"name": f"col_{c}", "primary_key": c == 0} for c in range(columns)],
            "foreign_keys": [],
        }
    return schema


@pytest.fixture
def listing(monkeypatch: pytest.MonkeyPatch):
    state = {"schema": _schema(300)}

    class FakeStore:
        async def get_connection(self, _name: str):
            return SimpleNamespace(db_type="mssql")

        async def get_connection_string(self, _name: str) -> str:
            return "mssql://x"

        async def get_credential_extras(self, _name: str) -> dict:
            return {}

    @asynccontextmanager
    async def fake_store_session():
        yield FakeStore()

    monkeypatch.setattr(catalog, "_store_session", fake_store_session)
    monkeypatch.setattr(schema_cache, "get", lambda _name: state["schema"])

    async def call(**kwargs) -> str:
        return await catalog.list_tables.__wrapped__(connection_name="warehouse", **kwargs)

    return call, state


@pytest.mark.asyncio
async def test_default_listing_caps_at_200_tables_with_a_narrowing_hint(listing) -> None:
    call, _state = listing
    text = await call()

    lines = text.splitlines()
    assert lines[0] == "Database: warehouse (mssql)" and lines[1] == "Tables: 300"
    assert lines[-1] == "100 more tables not shown; narrow with schema= or name_contains="
    assert len(lines) == 3 + 200 + 1
    assert lines[3].startswith("dbo.customers_000: col_0*, col_1, col_2")

    projected = project_tool_result(_TOOL, text)
    assert projected.result["total"] == 300 and len(projected.result["entries"]) == 200


@pytest.mark.asyncio
async def test_schema_and_name_filters_narrow_the_listing(listing) -> None:
    call, _state = listing

    by_schema = await call(schema="SALES")
    assert by_schema.splitlines()[1] == "Tables: 150"
    assert all(line.startswith("sales.") for line in by_schema.splitlines()[3:])

    by_name = await call(name_contains="CUSTOMERS_0")
    names = [line.split(" ")[0].split(":")[0] for line in by_name.splitlines()[3:]]
    assert names and all("customers_0" in name for name in names)
    assert "more tables not shown" not in by_name

    both = await call(schema="dbo", name_contains="orders", max_tables=5)
    assert both.splitlines()[-1].endswith("more tables not shown; narrow with schema= or name_contains=")
    assert len(both.splitlines()) == 3 + 5 + 1


@pytest.mark.asyncio
async def test_columns_false_and_budget_overflow_use_the_compact_form(listing) -> None:
    call, state = listing

    compact = await call(columns=False, max_tables=3)
    assert compact.splitlines()[3] == "dbo.customers_000 (3 cols)"
    assert compact.splitlines()[4] == "dbo.customers_006 (6K rows, 3 cols)"
    projected = project_tool_result(_TOOL, compact)
    entry = projected.result["entries"][1]
    assert entry["name"] == "dbo.customers_006" and entry["row_count"] == 6000 and entry["column_count"] == 3
    assert entry["columns"] == []

    state["schema"] = _schema(200, columns=120)
    degraded = await call()
    assert len(degraded) <= catalog.LIST_TABLES_CHAR_BUDGET
    body = degraded.splitlines()[3:]
    assert all(": col_" not in line for line in body)
    assert body[0].endswith("(120 cols)")
    assert "more tables not shown" not in degraded

    state["schema"] = _schema(3000, columns=1)
    cut = await call(max_tables=3000)
    assert len(cut) <= catalog.LIST_TABLES_CHAR_BUDGET
    assert cut.splitlines()[-1].endswith("more tables not shown; narrow with schema= or name_contains=")


@pytest.mark.asyncio
async def test_list_tables_docstring_names_the_new_parameters() -> None:
    doc = catalog.list_tables.__wrapped__.__doc__ or ""
    for name in ("schema", "name_contains", "max_tables", "columns"):
        assert f"{name}:" in doc


def test_generic_result_budget_truncates_with_a_narrowing_tail() -> None:
    big = "x" * (audit.RESULT_BUDGET_CHARS + 5000)
    clipped = audit.apply_result_budget("schema_overview", big)
    assert isinstance(clipped, str)
    assert clipped.startswith("x" * audit.RESULT_BUDGET_CHARS)
    assert clipped.endswith(
        f"[truncated: result was {len(big)} chars; narrow the request with the tool's filter parameters]"
    )
    assert audit.apply_result_budget("schema_overview", "small") == "small"
    assert audit.apply_result_budget("sandbox_read_file", big) is big
    assert audit.apply_result_budget("read_notebook", {"kind": "json"}) == {"kind": "json"}


@pytest.mark.asyncio
async def test_audited_wrapper_applies_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from gateway.mcp.context import mcp_scopes_var

    async def schema_overview(connection_name: str) -> str:
        return "y" * (audit.RESULT_BUDGET_CHARS + 1)

    wrapped = audit._audited_tool(schema_overview)
    monkeypatch.setattr(audit, "_audit_tool_call", AsyncMock())
    token = mcp_scopes_var.set(frozenset({"query"}))
    try:
        result = await wrapped(connection_name="warehouse")
    finally:
        mcp_scopes_var.reset(token)
    assert "[truncated: result was" in result


@pytest.mark.asyncio
async def test_audited_wrapper_records_a_tool_error_as_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ToolError still reaches the audit log as blocked, with its reason."""
    from unittest.mock import AsyncMock

    from mcp.server.mcpserver.exceptions import ToolError

    from gateway.mcp.context import mcp_scopes_var

    async def query_database(sql: str, connection_name: str | None = None) -> str:
        raise ToolError("Query error: relation orders does not exist")

    wrapped = audit._audited_tool(query_database)
    recorded = AsyncMock()
    monkeypatch.setattr(audit, "_audit_tool_call", recorded)
    token = mcp_scopes_var.set(["query"])
    try:
        with pytest.raises(ToolError, match="^Query error:"):
            await wrapped(sql="select 1", connection_name="warehouse")
    finally:
        mcp_scopes_var.reset(token)
    import asyncio

    await asyncio.sleep(0)
    recorded.assert_awaited_once()
    kwargs = recorded.await_args.kwargs
    assert kwargs["error"] == "Query error: relation orders does not exist"
    assert kwargs["sql"] == "select 1" and kwargs["connection_name"] == "warehouse"
