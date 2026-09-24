"""Tableau tools of the standalone chat agent: gating, files, and errors."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
)

from signalpilot._server.ai.standalone_chat_tool_schemas import (
    standalone_chat_tools,
)
from signalpilot._server.ai.standalone_chat_tools import (
    build_standalone_chat_mcp_server,
)
from signalpilot._server.ai.tableau_summary import (
    SUMMARY_MAX_CHARS,
    summarize_twb,
)
from signalpilot._server.ai.tableau_tools import (
    NOT_ENABLED_MESSAGE,
    TABLEAU_TOOL_NAMES,
    build_tableau_handlers,
    resolve_scratch_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

GATEWAY = "http://gateway:3300"
TOKEN = "run-scoped-token"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource name='Parameters' hasconnection='false' inline='true'>
      <column caption='Top N' datatype='integer' name='[Parameter 1]'
        param-domain-type='range' role='measure' type='quantitative'
        value='10' />
    </datasource>
    <datasource caption='Orders (published)' name='sqlproxy.0abc'>
      <repository-location id='OrdersPublished' path='/datasources'
        revision='1.0' site='daniel' />
      <connection class='sqlproxy' dbname='OrdersPublished'
        server='10ay.online.tableau.com' />
    </datasource>
    <datasource caption='Warehouse' name='federated.1xyz'>
      <connection class='federated'>
        <named-connections>
          <named-connection name='sqlserver.1'>
            <connection class='sqlserver' server='db.example.com,1433' />
          </named-connection>
        </named-connections>
      </connection>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Revenue by Month'>
      <table><view><datasources>
        <datasource caption='Nested' name='sqlproxy.0abc' />
      </datasources></view></table>
    </worksheet>
    <worksheet name='Top Customers' />
  </worksheets>
  <dashboards>
    <dashboard name='Executive Overview' />
  </dashboards>
</workbook>
"""


def _handlers(
    tmp_path: Path, respond: Callable[[httpx.Request], httpx.Response]
) -> dict[str, Any]:
    return build_tableau_handlers(
        scratch_directory=tmp_path,
        gateway_url=GATEWAY,
        gateway_token=TOKEN,
        transport=httpx.MockTransport(respond),
    )


def _json(result: list[Any]) -> dict[str, Any]:
    return json.loads(result[0].text)


async def _list_names(**kwargs: Any) -> set[str]:
    server = build_standalone_chat_mcp_server(**kwargs)["instance"]
    listed = await server.request_handlers[ListToolsRequest](
        ListToolsRequest()
    )
    return {tool.name for tool in listed.root.tools}


@pytest.mark.asyncio
async def test_tableau_tools_are_absent_unless_enabled() -> None:
    names = await _list_names()
    assert not any(name.startswith("tableau_") for name in names)

    enabled = await _list_names(tableau_enabled=True)
    assert set(TABLEAU_TOOL_NAMES) <= enabled
    assert enabled - set(TABLEAU_TOOL_NAMES) == names

    schema_names = {
        tool.name
        for tool in standalone_chat_tools(
            notebook_enabled=True, tableau_enabled=True
        )
    }
    assert set(TABLEAU_TOOL_NAMES) <= schema_names
    assert not any(
        tool.name.startswith("tableau_")
        for tool in standalone_chat_tools(notebook_enabled=True)
    )


@pytest.mark.asyncio
async def test_tableau_handlers_are_unregistered_when_disabled() -> None:
    server = build_standalone_chat_mcp_server()["instance"]
    response = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="tableau_search", arguments={"query": "sales"}
            )
        )
    )
    assert response.root.isError is True
    assert "Unknown tool" in response.root.content[0].text


def test_tableau_tool_schemas_describe_the_skill_and_close_inputs() -> None:
    tools = {
        tool.name: tool
        for tool in standalone_chat_tools(
            notebook_enabled=False, tableau_enabled=True
        )
        if tool.name.startswith("tableau_")
    }
    assert set(tools) == set(TABLEAU_TOOL_NAMES)
    for tool in tools.values():
        assert "signalpilot-dbt:tableau skill first" in tool.description
        assert "—" not in tool.description  # no em dashes
        assert tool.inputSchema["additionalProperties"] is False
    assert tools["tableau_publish_workbook"].inputSchema["required"] == [
        "path",
        "name",
    ]
    assert tools["tableau_query_datasource"].inputSchema["required"] == [
        "datasource",
        "fields",
    ]


@pytest.mark.asyncio
async def test_download_writes_the_twb_and_returns_a_summary(
    tmp_path: Path,
) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            content=TWB,
            headers={
                "Content-Type": "application/xml",
                "X-Tableau-Workbook-Id": "wb-1",
                "X-Tableau-Workbook-Name": "Sales%20Overview%20Q3",
            },
        )

    result = await _handlers(tmp_path, respond)["tableau_download_workbook"](
        {"workbook": "Sales Overview Q3"}
    )
    payload = _json(result)

    request = seen[0]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.url.raw_path == (
        b"/api/tableau/runtime/workbooks/Sales%20Overview%20Q3/content"
    )
    assert payload["path"] == "tableau/sales-overview-q3.twb"
    assert payload["workbook_id"] == "wb-1"
    assert payload["name"] == "Sales Overview Q3"
    assert payload["bytes"] == len(TWB)
    assert (tmp_path / payload["path"]).read_bytes() == TWB

    summary = payload["summary"]
    assert summary["dashboards"] == ["Executive Overview"]
    assert summary["worksheets"] == ["Revenue by Month", "Top Customers"]
    assert summary["parameters"] == ["Top N"]
    assert summary["datasource_count"] == 2  # nested view copies not counted
    published, warehouse = summary["datasources"]
    assert published == {
        "caption": "Orders (published)",
        "class": "sqlproxy",
        "content_url": "OrdersPublished",
    }
    assert warehouse["class"] == "federated"
    assert warehouse["inner_classes"] == ["sqlserver"]


def test_summary_stays_compact_for_a_large_workbook(tmp_path: Path) -> None:
    sheets = "".join(
        f"<worksheet name='Sheet number {index} with a long name' />"
        for index in range(400)
    )
    path = tmp_path / "big.twb"
    path.write_text(
        f"<workbook><worksheets>{sheets}</worksheets></workbook>",
        encoding="utf-8",
    )
    summary = summarize_twb(path)
    assert summary["worksheet_count"] == 400
    assert summary["lists_truncated"] is True
    assert len(json.dumps(summary)) <= SUMMARY_MAX_CHARS

    broken = tmp_path / "broken.twb"
    broken.write_text("<workbook><worksheets>", encoding="utf-8")
    assert "parse_error" in summarize_twb(broken)


@pytest.mark.parametrize(
    "bad_path", ["../escape.twb", "tableau/../../escape.twb"]
)
@pytest.mark.asyncio
async def test_download_rejects_paths_outside_the_scratch(
    tmp_path: Path, bad_path: str
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    def respond(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request for a rejected path")

    handlers = _handlers(scratch, respond)
    with pytest.raises(ValueError, match="'..'"):
        await handlers["tableau_download_workbook"](
            {"workbook": "wb", "path": bad_path}
        )
    outside = tmp_path / "outside.twb"
    with pytest.raises(ValueError, match="inside the scratch"):
        await handlers["tableau_download_workbook"](
            {"workbook": "wb", "path": str(outside)}
        )
    inside = resolve_scratch_path(scratch, str(scratch / "tableau" / "a.twb"))
    assert inside == (scratch / "tableau" / "a.twb").resolve()


@pytest.mark.asyncio
async def test_publish_sends_the_file_as_multipart(tmp_path: Path) -> None:
    source = tmp_path / "tableau" / "edited.twb"
    source.parent.mkdir()
    source.write_bytes(TWB)
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "wb-9",
                "name": "Edited",
                "credentials_embedded": ["Warehouse"],
                "unbound_connections": [],
            },
        )

    result = await _handlers(tmp_path, respond)["tableau_publish_workbook"](
        {
            "path": "tableau/edited.twb",
            "name": "Edited",
            "connection": "production",
            "overwrite": False,
        }
    )

    assert _json(result)["id"] == "wb-9"
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/tableau/runtime/workbooks"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    body = request.read()
    assert TWB in body
    assert b'name="file"; filename="edited.twb"' in body
    assert b'name="connection"\r\n\r\nproduction' in body
    assert b'name="overwrite"\r\n\r\nfalse' in body
    assert b'name="show_tabs"\r\n\r\ntrue' in body


@pytest.mark.asyncio
async def test_publish_rejects_a_missing_or_wrong_file(tmp_path: Path) -> None:
    handlers = _handlers(tmp_path, lambda _request: httpx.Response(500))
    with pytest.raises(ValueError, match="No file"):
        await handlers["tableau_publish_workbook"](
            {"path": "tableau/missing.twb", "name": "X"}
        )
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.twb or \.twbx"):
        await handlers["tableau_publish_workbook"](
            {"path": "notes.md", "name": "X"}
        )


@pytest.mark.asyncio
async def test_view_image_saves_the_png_and_returns_only_the_path(
    tmp_path: Path,
) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, content=PNG, headers={"Content-Type": "image/png"}
        )

    result = await _handlers(tmp_path, respond)["tableau_view_image"](
        {"view": "Executive Overview", "width": 1600}
    )

    status = json.loads(result[0].text)
    assert status["path"] == "artifacts/tableau-executive-overview.png"
    assert (tmp_path / status["path"]).read_bytes() == PNG
    # Only text comes back: an inline image can exceed the SDK message limit.
    assert len(result) == 1
    assert "Read tool" in status["next"]
    assert seen[0].url.params["max_age"] == "1"
    assert seen[0].url.params["width"] == "1600"


@pytest.mark.asyncio
async def test_datasource_publish_requires_exactly_one_source(
    tmp_path: Path,
) -> None:
    seen: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "ds-1", "content_url": "c"})

    handlers = _handlers(tmp_path, respond)
    with pytest.raises(ValueError, match="exactly one"):
        await handlers["tableau_publish_datasource"](
            {"name": "d", "connection": "prod", "table": "t", "sql": "s"}
        )
    result = await handlers["tableau_publish_datasource"](
        {"name": "Orders", "connection": "prod", "table": "orders"}
    )
    assert _json(result)["id"] == "ds-1"
    assert seen == [
        {
            "name": "Orders",
            "connection": "prod",
            "table": "orders",
            "overwrite": True,
        }
    ]


@pytest.mark.asyncio
async def test_large_json_answers_are_truncated_with_a_note(
    tmp_path: Path,
) -> None:
    rows = [{"value": "x" * 100} for _ in range(1_000)]

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": rows, "row_count": 1_000})

    result = await _handlers(tmp_path, respond)["tableau_query_datasource"](
        {"datasource": "Orders", "fields": [{"fieldCaption": "Sales"}]}
    )
    text = result[0].text
    assert len(text) < 41_000
    assert "[truncated:" in text


@pytest.mark.asyncio
async def test_gateway_403_reports_the_integration_is_not_enabled(
    tmp_path: Path,
) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"detail": "Tableau integration is not active"}
        )

    with pytest.raises(ValueError, match=NOT_ENABLED_MESSAGE):
        await _handlers(tmp_path, respond)["tableau_search"]({"query": "x"})

    def denied(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Forbidden: project"})

    with pytest.raises(ValueError, match=r"Tableau denied access \(403\)"):
        await _handlers(tmp_path, denied)["tableau_get_workbook"](
            {"workbook": "Sales"}
        )


@pytest.mark.asyncio
async def test_gateway_errors_surface_as_mcp_errors() -> None:
    server = build_standalone_chat_mcp_server(tableau_enabled=True)["instance"]
    response = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="tableau_search", arguments={"query": "sales"}
            )
        )
    )
    assert response.root.isError is True
    assert "no gateway identity" in response.root.content[0].text
