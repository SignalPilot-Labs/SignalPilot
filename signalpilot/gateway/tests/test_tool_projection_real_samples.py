"""Projector cases built from real ``tool_completed`` rows on staging (2026-09-02 audit).

The synthetic cases in ``test_tool_projection.py`` were written from the tool
formatters; these were copied from what the agent runtime actually hands the
worker, which differs in three ways: MCP results arrive wrapped in a
``{"result": "..."}`` envelope, oversized results are replaced by a
"saved to file" notice, and builtin tool failures wear ``<tool_use_error>``
tags.
"""

from __future__ import annotations

import json

from gateway.standalone_chat.tool_projection import project_tool_result
from gateway.standalone_chat.tool_projection.text import normalize_content

_QUERY_HEADER = "row_count | distinct_dates | null_rev | null_op | distinct_other_expense_values | min_other | max_other"
QUERY_TEXT = "\n".join(
    [
        _QUERY_HEADER,
        "-" * len(_QUERY_HEADER),
        "365 | 365 | 0 | 0 | 3 | 10968.36 | 12142.30",
        "",
        "[1 rows, 4214ms, result 7f0af485-46e2-4780-b930-f5a0f71e788e, completeness: complete]",
    ]
)
QUERY_ENVELOPE = json.dumps({"result": QUERY_TEXT})

MART_TEXT = (
    "mart | min_d | max_d | n\n"
    "------------------------\n"
    "daily_prof | 2021-01-01 | 2026-06-30 | 2007\n"
    "sales_cogs_daily | 2019-01-01 | 2026-07-01 | 2739\n"
    "total_ppc | 2019-01-01 | 2026-06-30 | 580456\n\n"
    "[3 rows, 4498ms, result 48b26688-6851-4bc5-9ef2-dae9b75910b7, completeness: complete]"
)

TOO_LARGE = (
    "Error: result (72,461 characters) exceeds maximum allowed tokens. Output has been saved to "
    "/home/notebook/.sp/claude-sessions/f4d31883/tool-results/mcp-signalpilot-list_tables-1788377323102.txt.\n"
    "Format: JSON with schema: {result: string}\n"
    "Use offset and limit parameters to read specific portions of the file, search within it for "
    "specific content, and jq to make structured queries.\n"
    "REQUIREMENTS FOR SUMMARIZATION/ANALYSIS/REVIEW:\n"
    "- You MUST read the content from the file"
)

GREP_ERROR = (
    "<tool_use_error>InputValidationError: Grep failed due to the following issue:\n"
    "An unexpected parameter `-o` was provided</tool_use_error>"
)

READ_TEXT = "\n".join(
    [
        "1\t{#-",
        "2\t    Customer retention by acquisition cohort. One row per first-order month: how many",
        "3\t    customers were acquired, how many went on to order again, and what the cohort has",
        "4\t-#}",
        "5\t",
        "6\twith customers as (",
    ]
)

TOOL_SEARCH = "\n".join(
    json.dumps({"type": "tool_reference", "tool_name": name})
    for name in (
        "mcp__signalpilot__query_database",
        "mcp__signalpilot__list_tables",
        "mcp__standalone-chat__start_analysis_notebook",
        "mcp__standalone-chat__publish_chart",
        "mcp__standalone-chat__publish_table",
        "mcp__standalone-chat__publish_report",
    )
)


class TestResultEnvelope:
    def test_normalize_unwraps_single_key_string_envelope(self):
        assert normalize_content(QUERY_ENVELOPE) == QUERY_TEXT

    def test_real_json_tools_keep_their_shape(self):
        payload = json.dumps({"result": {"rows": 3}, "status": "ok"})
        assert normalize_content(payload) == payload
        assert normalize_content(json.dumps({"published": True})) == json.dumps({"published": True})

    def test_query_database_in_envelope_projects_a_table(self):
        projected = project_tool_result(
            "mcp__signalpilot__query_database",
            QUERY_ENVELOPE,
            tool_input={"connection_name": "dumpsters", "sql": "select 1"},
        )
        assert projected.result["kind"] == "table"
        assert [c["name"] for c in projected.result["columns"]][:3] == ["row_count", "distinct_dates", "null_rev"]
        assert projected.result["rows"] == [[365, 365, 0, 0, 3, 10968.36, 12142.30]]
        assert projected.result["result_id"] == "7f0af485-46e2-4780-b930-f5a0f71e788e"
        assert projected.result["execution_ms"] == 4214
        assert projected.summary == "1 row · 4.2 s"

    def test_multi_row_query_keeps_text_cells_and_typed_numbers(self):
        projected = project_tool_result(
            "mcp__signalpilot__query_database", json.dumps({"result": MART_TEXT}), tool_input=None
        )
        assert projected.result["kind"] == "table"
        assert projected.result["rows"][2] == ["total_ppc", "2019-01-01", "2026-06-30", 580456]
        assert projected.result["row_count"] == 3
        assert projected.summary.startswith("3 rows")


class TestRuntimeNotices:
    def test_too_large_notice_is_not_an_error(self):
        projected = project_tool_result("mcp__signalpilot__list_tables", json.dumps({"result": TOO_LARGE}))
        assert projected.result["kind"] == "text"
        assert projected.result["too_large"] is True
        assert projected.result["result_chars_reported"] == 72461
        assert projected.result["saved_path"].endswith("list_tables-1788377323102.txt")
        assert projected.summary == "Result too large to display (72,461 chars) · saved for the agent"

    def test_tool_use_error_tags_are_stripped_from_the_summary(self):
        projected = project_tool_result("Grep", GREP_ERROR, is_error=True)
        assert projected.summary.startswith("InputValidationError: Grep failed")
        assert "<tool_use_error>" not in projected.summary
        assert "<tool_use_error>" not in projected.result_text


class TestBuiltinSummaries:
    def test_read_counts_numbered_lines_and_names_the_file(self):
        projected = project_tool_result(
            "Read", READ_TEXT, tool_input={"file_path": "/work/models/marts/rpt_customer_retention.sql"}
        )
        assert projected.summary == "6 lines · rpt_customer_retention.sql"
        assert projected.result == {"kind": "text"}

    def test_tool_search_lists_the_loaded_tools(self):
        projected = project_tool_result("ToolSearch", TOOL_SEARCH)
        assert projected.summary == "6 tools loaded"
        assert projected.result["tools"][0] == "mcp__signalpilot__query_database"

    def test_skill_and_todo_and_grep(self):
        assert project_tool_result("Skill", "Launching skill: signalpilot-dbt:dbt-workflow").summary == (
            "Loaded signalpilot-dbt:dbt-workflow"
        )
        todos = [{"status": "completed"}] * 9 + [{"status": "pending"}] * 3
        assert (
            project_tool_result(
                "TodoWrite",
                "Todos have been modified successfully. Ensure that you continue to use the todo list",
                tool_input={"todos": todos},
            ).summary
            == "Plan updated · 9/12 done"
        )
        assert project_tool_result("Grep", "a.sql:1:select\nb.sql:4:select").summary == "2 matches"
        assert project_tool_result("Glob", "No files found").summary == "0 files"

    def test_write_and_edit_name_the_file(self):
        assert project_tool_result("Write", "ok", tool_input={"file_path": "a/b/c.sql"}).summary == "Wrote c.sql"
        assert project_tool_result("Edit", "ok", tool_input={"file_path": "a/b/c.sql"}).summary == "Edited c.sql"
