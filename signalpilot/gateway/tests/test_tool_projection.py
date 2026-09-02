"""Contracts for standalone_chat.tool_projection.

Sample strings are built the way the MCP tools build them (see the pointer
comments at each formatter). If a formatter changes, update the sample here.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from gateway.standalone_chat.tool_projection import finalize_payload, project_tool_result
from gateway.standalone_chat.tool_projection.limits import PAYLOAD_MAX, RESULT_TEXT_MAX
from gateway.standalone_chat.tool_projection.text import compact_json, legacy_repr_text, parse_count, parse_ms

_RESULT_ID = "1f0e3f4a-9c1b-4a0e-8d2e-7d0b0f7a1c11"
_TOOL = "mcp__signalpilot__"


def _query_output(rows: list[dict[str, Any]], *, row_count: int, ms: int = 312, pii: list[str] | None = None) -> str:
    """Mirror gateway/mcp/tools/query.py::query_database formatting."""
    meta = f"{row_count} rows, {ms}ms, result {_RESULT_ID}, completeness: complete"
    notice = ""
    if pii:
        notice = (
            f"\n\n[PII REDACTED] The following columns were redacted by policy: {', '.join(pii)}. "
            "Values shown as ***** (hide), sha256:... (hash), or partially masked. "
            "Do not attempt to reverse or infer the original values."
        )
    if not rows:
        return f"Query returned 0 rows ({meta})" + notice
    columns = list(rows[0].keys())
    lines = [" | ".join(columns)]
    lines.append("-" * len(lines[0]))
    shown = 0
    for row in rows:
        if shown >= 400:
            break
        lines.append(" | ".join(str(row.get(c, "")) for c in columns))
        shown += 1
    if row_count > shown:
        lines.append(
            f"[INCOMPLETE DISPLAY] {row_count} rows total; only the first {shown} are shown above. "
            f"The remaining {row_count - shown} rows exist but are not displayed. "
            f"Do not treat the list above as complete: re-run the query with a WHERE filter or OFFSET {shown} "
            "to see every remaining row before concluding anything about what the full result does or does not contain."
        )
    return "\n".join(lines) + f"\n\n[{meta}]" + notice


class TestQueryDatabase:
    def test_table_projection(self) -> None:
        rows = [{"order_id": i, "customer": f"c{i}", "total": 10.5 * i} for i in range(1, 6)]
        projected = project_tool_result(_TOOL + "query_database", _query_output(rows, row_count=1204))

        assert projected.summary == "Preview 5 of 1,204 rows · 312 ms"
        table = projected.result
        assert table["kind"] == "table"
        assert [c["name"] for c in table["columns"]] == ["order_id", "customer", "total"]
        assert table["rows"][0] == [1, "c1", 10.5]
        assert table["row_count"] == 1204
        assert table["preview_row_count"] == 5
        assert table["preview_truncated"] is True
        assert table["result_id"] == _RESULT_ID
        assert table["execution_ms"] == 312
        assert table["completeness"] == "complete"
        assert table["source"] == "parsed"
        assert projected.result_text is not None and projected.result_chars == len(projected.result_text)

    def test_complete_table_and_pii(self) -> None:
        rows = [{"email": "*****", "n": 1}, {"email": "*****", "n": 2}]
        projected = project_tool_result(_TOOL + "query_database", _query_output(rows, row_count=2, pii=["email"]))

        assert projected.summary == "2 rows · 312 ms"
        assert projected.result["preview_truncated"] is False
        assert projected.result["pii_redacted_columns"] == ["email"]

    def test_zero_rows(self) -> None:
        projected = project_tool_result(_TOOL + "query_database", _query_output([], row_count=0, ms=45))

        assert projected.summary == "0 rows · 45 ms"
        assert projected.result["kind"] == "table"
        assert projected.result["rows"] == [] and projected.result["row_count"] == 0
        assert projected.result["result_id"] == _RESULT_ID

    def test_row_and_column_caps(self) -> None:
        rows = [{f"col_{c}": c * r for c in range(40)} for r in range(400)]
        projected = project_tool_result(_TOOL + "query_database", _query_output(rows, row_count=400))

        assert len(projected.result["rows"]) == 50
        assert len(projected.result["columns"]) == 30
        assert all(len(row) == 30 for row in projected.result["rows"])
        assert projected.result["columns_truncated"] is True
        assert projected.result["preview_truncated"] is True
        assert projected.truncated is True
        assert projected.result_text is not None and len(projected.result_text) == RESULT_TEXT_MAX

    def test_query_error_and_route_reply(self) -> None:
        error = project_tool_result(_TOOL + "query_database", "Query error: relation does not exist")
        assert error.result == {"kind": "text"} and error.summary == "Query error: relation does not exist"

        route = project_tool_result(_TOOL + "query_database", json.dumps({"route": "approval", "approval_required": True}))
        assert route.result["kind"] == "json"
        assert route.summary == "Route: approval · approval required"


class TestValidateSql:
    def test_valid(self) -> None:
        text = "VALID ✓\nEstimated rows: 12,000\nWarning: query may be expensive\nLocal checks: no LIMIT; SELECT *"
        projected = project_tool_result(_TOOL + "validate_sql", text)

        assert projected.summary == "Valid · ~12,000 rows"
        assert projected.result == {
            "kind": "validation",
            "valid": True,
            "estimated_rows": 12000,
            "expensive": True,
            "checks": ["no LIMIT", "SELECT *"],
        }

    def test_invalid(self) -> None:
        text = 'INVALID ✗\nrelation "orders" does not exist\n\nSuggested fix: check the schema prefix'
        projected = project_tool_result(_TOOL + "validate_sql", text)

        assert projected.summary == 'Invalid · relation "orders" does not exist'
        assert projected.result["valid"] is False
        assert projected.result["suggested_fix"] == "check the schema prefix"


class TestSchemaTools:
    def test_list_tables_single_database(self) -> None:
        lines = ["Database: production (postgresql)", "Tables: 2", ""]
        lines.append("public.orders (1.2M rows): id*, customer_id→public.customers.id, total")
        lines.append("public.customers (45K rows): id*, email")
        projected = project_tool_result(_TOOL + "list_tables", "\n".join(lines))

        assert projected.summary == "2 tables"
        result = projected.result
        assert result["kind"] == "table_list" and result["db_type"] == "postgresql"
        assert result["total"] == 2
        orders = result["entries"][0]
        assert orders["name"] == "public.orders" and orders["row_count"] == 1_200_000
        assert orders["columns"][0] == {"name": "id", "primary_key": True}
        assert orders["columns"][1] == {"name": "customer_id", "primary_key": False, "references": "public.customers.id"}
        assert result["entries"][1]["row_count"] == 45_000

    def test_list_tables_database_mode(self) -> None:
        text = (
            "Connection: warehouse (mssql)\n"
            "This connection has 6 databases and 1930 tables total.\n"
            "Call list_tables again with a database name to see its tables. Databases (table counts):\n"
            "\n  analytics (400 tables)\n  raw (1530 tables)"
        )
        projected = project_tool_result(_TOOL + "list_tables", text)

        assert projected.summary == "6 databases · 1,930 tables"
        assert projected.result["databases"][0] == {"name": "analytics", "table_count": 400}
        assert projected.result["total"] == 1930

    def test_list_tables_cap(self) -> None:
        lines = ["Database: production (duckdb)", "Tables: 500", ""]
        lines.extend(f"main.t{i} ({i} rows): id*, v" for i in range(1, 501))
        projected = project_tool_result(_TOOL + "list_tables", "\n".join(lines))

        assert len(projected.result["entries"]) == 200
        assert projected.result["entries_truncated"] is True
        assert projected.result["total"] == 500
        assert projected.summary == "500 tables"

    def test_describe_table(self) -> None:
        text = (
            "Table: public.orders\nDescription: Order facts\nOwner: data\nColumns (3):\n\n"
            "  id — integer (NOT NULL) [PK]\n"
            "  email — text (nullable)\n    Customer email\n    [PII: email]\n"
            "  total — numeric (nullable)"
        )
        projected = project_tool_result(_TOOL + "describe_table", text)

        assert projected.summary == "orders · 3 columns"
        result = projected.result
        assert result["table"] == "public.orders" and result["owner"] == "data"
        assert result["columns"][0] == {"name": "id", "type": "integer", "nullable": False, "primary_key": True}
        assert result["columns"][1]["pii"] == "email" and result["columns"][1]["comment"] == "Customer email"

    def test_explore_table(self) -> None:
        text = (
            "Table: public.orders\nRows: 1,204\nEngine: heap\n\nColumns:\n"
            "  id integer [PK, NOT NULL]\n"
            "  customer_id integer [FK→public.customers.id] -- who bought\n"
            "  created_at timestamp without time zone\n"
            "\nOutgoing FKs (1):\n  customer_id → public.customers.id\n"
            "\nReferenced by (1):\n  public.items.order_id → id\n"
            "\nSample values:\n  id: 1, 2, 3"
        )
        projected = project_tool_result(_TOOL + "explore_table", text)

        assert projected.summary == "orders · 3 columns · 1,204 rows"
        result = projected.result
        assert result["columns"][1]["foreign_key"] == "public.customers.id"
        assert result["columns"][1]["comment"] == "who bought"
        assert result["columns"][2]["type"] == "timestamp without time zone"
        assert result["foreign_keys"] == [{"column": "customer_id", "references": "public.customers.id"}]
        assert result["referenced_by"] == [{"table": "public.items", "column": "order_id", "references_column": "id"}]
        assert result["sample_values"] == {"id": ["1", "2", "3"]}

    def test_explore_columns(self) -> None:
        text = (
            "Table: public.orders (1,204 rows)\n\n"
            "  status: text [NOT NULL] -- lifecycle\n    stats: distinct=4, uniqueness=0.00\n"
            "    values: 'paid', 'open'\n"
            "  total: numeric\n    range: min=1.5, max=99.0, avg=20.1"
        )
        projected = project_tool_result(_TOOL + "explore_columns", text)

        assert projected.summary == "orders · 2 columns profiled"
        columns = projected.result["columns"]
        assert columns[0]["distinct_count"] == 4 and columns[0]["sample_values"] == ["paid", "open"]
        assert columns[0]["nullable"] is False and columns[0]["comment"] == "lifecycle"
        assert columns[1] == {"name": "total", "type": "numeric", "nullable": True, "min": "1.5", "max": "99.0", "avg": "20.1"}

    def test_explore_column(self) -> None:
        text = (
            "Column: public.orders.status\nTotal rows: 1,204\nDistinct values: 4\nNULL: 12 (1.0%)\n\n"
            "Top values:\n  paid: 1,000\n  open: 192"
        )
        projected = project_tool_result(_TOOL + "explore_column", text)

        assert projected.summary == "public.orders.status · 4 distinct"
        column = projected.result["columns"][0]
        assert column["null_count"] == 12 and column["null_pct"] == 1.0
        assert column["top_values"] == [{"value": "paid", "count": 1000}, {"value": "open", "count": 192}]

    def test_schema_text_tools(self) -> None:
        projected = project_tool_result(_TOOL + "find_join_path", "orders → customers via customer_id\n(1 hop)")
        assert projected.result == {"kind": "text"}
        assert projected.summary == "orders → customers via customer_id"


class TestOpsTools:
    def test_dbt_execute(self) -> None:
        text = (
            "target_schema: dev_daniel\nexit_code: 1\noutput:\n12:00:01  Running with dbt=1.8\n"
            "12:00:41  Finished running 13 table models in 0 hours 0 minutes and 41.23 seconds (41.23s).\n"
            "run_results: error=1, success=12\nfailures:\nmodel.pilot.fct_orders: Division by zero"
        )
        projected = project_tool_result(_TOOL + "dbt_execute", text, tool_input={"command": "run"})

        assert projected.summary == "dbt run · 12 success, 1 error · 41 s"
        result = projected.result
        assert result["kind"] == "dbt_run" and result["exit_code"] == 1
        assert result["statuses"] == {"error": 1, "success": 12} and result["total"] == 13
        assert result["failures"] == [{"node": "model.pilot.fct_orders", "message": "Division by zero"}]
        assert result["target_schema"] == "dev_daniel" and result["elapsed_s"] == pytest.approx(41.23)
        assert result["log"].startswith("12:00:01") and result["log_truncated"] is False

    def test_sandbox_exec_and_bash(self) -> None:
        text = "exit_code: 0\nstdout:\nline one\nline two\nstderr:\nwarn"
        projected = project_tool_result(_TOOL + "sandbox_exec", text, tool_input={"command": "ls"})
        assert projected.summary == "exit 0 · 2 lines"
        assert projected.result["stdout"] == "line one\nline two" and projected.result["stderr"] == "warn"
        assert projected.result["command"] == "ls"

        bash = project_tool_result("Bash", "\n".join(f"line {i}" for i in range(214)), tool_input={"command": "wc"})
        assert bash.summary == "exit 0 · 214 lines" and bash.result["kind"] == "terminal"

        failed = project_tool_result("Bash", "Exit code 2\nno such file", is_error=True)
        assert failed.result["exit_code"] == 2 and failed.result["stderr"] == "no such file"
        assert failed.summary == "Exit code 2"

    def test_search_knowledge(self) -> None:
        lines = ["Found 7 result(s) for 'revenue':\n"]
        for i in range(7):
            lines.append(
                f"  id=doc-{i} scope=project:pilot category=definitions title=Revenue rule {i}\n"
                f"  snippet: 'net of refunds {i}'\n"
            )
        projected = project_tool_result(_TOOL + "search_knowledge", "\n".join(lines), tool_input={"query": "revenue"})

        assert projected.summary == "7 docs"
        result = projected.result
        assert result["mode"] == "search" and result["total"] == 7 and result["query"] == "revenue"
        assert result["docs"][0] == {
            "id": "doc-0",
            "scope": "project:pilot",
            "category": "definitions",
            "title": "Revenue rule 0",
            "snippet": "net of refunds 0",
        }

    def test_get_knowledge_sections(self) -> None:
        text = "[org:(org)][definitions]\n## Revenue\n\nNet of refunds.\n\n[project:pilot][gotchas]\n## Fan out\n\nJoin on grain.\n"
        projected = project_tool_result(_TOOL + "get_knowledge", text)

        assert projected.summary == "2 docs"
        assert projected.result["docs"][1] == {
            "scope": "project:pilot",
            "category": "gotchas",
            "title": "Fan out",
            "snippet": "Join on grain.",
        }
        empty = project_tool_result(_TOOL + "get_knowledge", "No knowledge base content found.")
        assert empty.summary == "0 docs" and empty.result["total"] == 0

    def test_artifacts(self) -> None:
        notebook = project_tool_result(
            "mcp__signalpilot-notebook__start_analysis_notebook",
            json.dumps({"session_id": "s_1", "status": "started", "notebook_path": "/w/analysis.py", "notebook": "analysis"}),
        )
        assert notebook.summary == "Notebook started"
        assert notebook.result["session_id"] == "s_1" and notebook.result["artifact_kind"] == "notebook"

        dashboard = project_tool_result(
            "mcp__signalpilot-notebook__create_dashboard_preview",
            json.dumps({"status": "preview_ready", "authoring_session_id": "a1", "dashboard_name": "Exec", "chart_count": 3}),
        )
        assert dashboard.summary == "Exec · 3 charts" and dashboard.result["dashboard_session_id"] == "a1"

    def test_json_and_text_fallbacks(self) -> None:
        as_json = project_tool_result("mcp__notion__search", json.dumps({"results": [1, 2], "status": "ok"}))
        assert as_json.result["kind"] == "json" and as_json.summary == "Search · ok"

        as_text = project_tool_result("mcp__signalpilot__unknown_tool", "plain words\nmore")
        assert as_text.result == {"kind": "text"} and as_text.summary == "plain words"


class TestErrorsAndGuards:
    def test_error_is_sanitized_and_keeps_sign_in_text(self) -> None:
        raw = "Error: postgresql://user:hunter2@db.internal/prod refused\n  File \"/opt/x.py\", line 1, in run"
        projected = project_tool_result(_TOOL + "query_database", raw, is_error=True)
        assert "hunter2" not in projected.summary and "hunter2" not in (projected.result_text or "")
        assert projected.result == {"kind": "text"}

        sign_in = project_tool_result("mcp__hubspot__list", "HubSpot needs you to sign in before use.", is_error=True)
        assert sign_in.summary == "HubSpot needs you to sign in before use."

    @pytest.mark.parametrize(
        "content",
        ["", "\x00", "|" * 200_000, "{not json", "[{'type': 'text', 'text': 'x'", None, 42],
        ids=["empty", "nul", "pipes-200k", "bad-json", "bad-repr", "none", "int"],
    )
    @pytest.mark.parametrize(
        "tool",
        [
            "query_database",
            "validate_sql",
            "list_tables",
            "describe_table",
            "explore_table",
            "explore_columns",
            "explore_column",
            "dbt_execute",
            "sandbox_exec",
            "Bash",
            "search_knowledge",
            "get_knowledge",
            "publish_table",
            "start_analysis_notebook",
            "plan_query",
            "notion_search",
        ],
    )
    def test_fuzz_never_raises(self, tool: str, content: Any) -> None:
        for is_error in (False, True):
            projected = project_tool_result(_TOOL + tool, content, is_error=is_error)
            assert projected.result.get("kind")
            assert projected.summary.strip()
            payload = finalize_payload({"summary": projected.summary, "result": projected.result, "result_text": projected.result_text})
            assert len(json.dumps(payload, separators=(",", ":")).encode()) <= PAYLOAD_MAX

    def test_legacy_repr_body(self) -> None:
        inner = json.dumps({"session_id": "s_1", "status": "started", "notebook_path": "/w/analysis.py"})
        dict_form = "[{'type': 'text', 'text': " + repr(inner) + "}]"
        assert legacy_repr_text(dict_form) == inner
        text_content_form = "[TextContent(type='text', text=" + repr(inner) + ", annotations=None)]"
        assert legacy_repr_text(text_content_form) == inner

        projected = project_tool_result(_TOOL + "start_analysis_notebook", dict_form)
        assert projected.result["session_id"] == "s_1"

    def test_result_chars_reflects_upstream_full_length(self) -> None:
        projected = project_tool_result(_TOOL + "unknown", "short", result_chars=90_000)
        assert projected.result_chars == 90_000 and projected.truncated is True


class TestFinalizePayload:
    def test_shrinks_oversize_table_payload(self) -> None:
        rows = [[("x" * 60) for _ in range(30)] for _ in range(50)]
        payload = {
            "tool_call_id": "t1",
            "summary": "50 rows",
            "result": {"kind": "table", "rows": rows, "columns": [{"name": f"c{i}"} for i in range(30)]},
            "result_text": "y" * RESULT_TEXT_MAX,
            "truncated": False,
        }
        assert len(json.dumps(payload, separators=(",", ":")).encode()) > PAYLOAD_MAX
        final = finalize_payload(payload)
        assert len(json.dumps(final, separators=(",", ":")).encode()) <= PAYLOAD_MAX
        assert final["truncated"] is True
        assert final["result"]["kind"] == "table" and len(final["result"]["rows"]) == 20

    def test_drops_result_when_still_too_big(self) -> None:
        payload = {"summary": "s", "result": {"kind": "json", "value": {"blob": "z" * 70_000}}, "result_text": "z" * 8000}
        final = finalize_payload(payload)
        assert final["result"] == {"kind": "text"} and final["truncated"] is True
        assert len(json.dumps(final, separators=(",", ":")).encode()) <= PAYLOAD_MAX

    def test_small_payload_untouched(self) -> None:
        payload = {"summary": "ok", "result": {"kind": "text"}, "truncated": False}
        assert finalize_payload(payload) == payload


class TestTextHelpers:
    def test_parse_helpers(self) -> None:
        assert parse_count("1,204") == 1204 and parse_count("1.2M") == 1_200_000 and parse_count("45K") == 45_000
        assert parse_count("nope") is None
        assert parse_ms("312ms") == 312 and parse_ms("1.5s") == 1500

    def test_compact_json_bounds(self) -> None:
        deep: Any = {"s": "x" * 600, "items": list(range(30)), "keys": {f"k{i}": i for i in range(60)}}
        for _ in range(7):
            deep = {"child": deep}
        compact = compact_json(deep)
        assert len(json.dumps(compact)) < 3000
        node = compact
        for _ in range(5):
            node = node["child"] if isinstance(node, dict) and "child" in node else node
        assert node == "…" or isinstance(node, dict)
