"""Projectors for the schema tools (list_tables, describe/explore_*).

Formats parsed here come from ``gateway/mcp/tools/schema/catalog.py``,
``exploration_table.py``, ``exploration_columns.py`` and ``explore_value.py``.
"""

from __future__ import annotations

import re
from typing import Any

from gateway.standalone_chat.tool_projection.base import ProjectedResult, build, text_result
from gateway.standalone_chat.tool_projection.limits import (
    SAMPLE_VALUES_MAX,
    SCHEMA_COLS_MAX,
    TABLE_LIST_COLS_MAX,
    TABLE_LIST_MAX,
    TOP_VALUES_MAX,
)
from gateway.standalone_chat.tool_projection.text import (
    first_line,
    format_count,
    parse_count,
    summary_text,
)

_DB_MODE_RE = re.compile(r"This connection has (\d+) databases and (\d+) tables total\.")
_DB_LINE_RE = re.compile(r"^\s+(\S+) \((\d+) tables\)$")
_HEADER_RE = re.compile(r"^(?:Database|Connection): (.+?) \(([^)]*)\)$")
_TABLE_LINE_RE = re.compile(r"^(\S+?)(?: \(([\d.]+[MK]?) rows\))?: (.*)$")
_DESCRIBE_COL_RE = re.compile(r"^  (\S+) — (.+?) \((nullable|NOT NULL)\)( \[PK\])?$")
_EXPLORE_COL_RE = re.compile(r"^  (\S+) (.+?)(?: \[([^\]]*)\])?(?: -- (.*))?$")
_PROFILE_HEADER_RE = re.compile(r"^(Table|View): (.+?) \(([\d,]+|\?) rows\)$")
_PROFILE_COL_RE = re.compile(r"^  (\S+): (.+?)(?: \[([^\]]*)\])?(?: -- (.*))?$")
_FK_LINE_RE = re.compile(r"^  (\S+) → (\S+)\.(\S+)$")
_REF_LINE_RE = re.compile(r"^  (\S+)\.(\S+) → (\S+)$")
_TOP_VALUE_RE = re.compile(r"^  (.*): ([\d,]+)$")


def _short(table: str) -> str:
    return table.rsplit(".", 1)[-1] if table else table


def project_list_tables(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    lines = text.splitlines()
    if not lines or lines[0].startswith("Error"):
        return text_result(text, summary=summary_text(text, "No tables"))
    header = _HEADER_RE.match(lines[0].strip())
    result: dict[str, Any] = {"kind": "table_list", "entries": [], "entries_truncated": False, "total": 0}
    if header:
        result["db_type"] = header.group(2)
    db_mode = _DB_MODE_RE.search(text)
    if db_mode:
        databases = []
        for line in lines:
            match = _DB_LINE_RE.match(line)
            if match:
                databases.append({"name": match.group(1), "table_count": int(match.group(2))})
        result["connection"] = header.group(1) if header else None
        result["databases"] = databases
        result["total"] = int(db_mode.group(2))
        summary = f"{format_count(int(db_mode.group(1)))} databases · {format_count(result['total'])} tables"
        return build(result, summary=summary, text=text)
    if header:
        if tool_input and tool_input.get("database"):
            result["database"] = header.group(1)
        else:
            result["connection"] = header.group(1)
    entries: list[dict[str, Any]] = []
    declared: int | None = None
    for line in lines[1:]:
        if line.startswith("Tables: "):
            declared = parse_count(line[len("Tables: ") :])
            continue
        match = _TABLE_LINE_RE.match(line)
        if not match:
            continue
        if len(entries) >= TABLE_LIST_MAX:
            result["entries_truncated"] = True
            continue
        columns = []
        raw_columns = [part.strip() for part in match.group(3).split(",") if part.strip()]
        for raw in raw_columns[:TABLE_LIST_COLS_MAX]:
            name, _, reference = raw.partition("→")
            column: dict[str, Any] = {"name": name.rstrip("*"), "primary_key": name.endswith("*")}
            if reference:
                column["references"] = reference
            columns.append(column)
        entry: dict[str, Any] = {
            "name": match.group(1),
            "row_count": parse_count(match.group(2)) if match.group(2) else None,
            "columns": columns,
            "columns_truncated": len(raw_columns) > TABLE_LIST_COLS_MAX,
        }
        if match.group(2):
            entry["row_count_label"] = match.group(2)
        entries.append(entry)
    total = declared if declared is not None else len(entries)
    result["entries"] = entries
    result["total"] = total
    return build(
        result,
        summary=f"{format_count(total)} tables",
        text=text,
        truncated=result["entries_truncated"],
    )


def project_describe_table(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Table: "):
        return text_result(text, summary=summary_text(text, "Table schema"))
    result: dict[str, Any] = {"kind": "schema", "table": lines[0][len("Table: ") :].strip(), "columns": []}
    columns: list[dict[str, Any]] = []
    for line in lines[1:]:
        if line.startswith("Description: "):
            result["description"] = line[len("Description: ") :]
        elif line.startswith("Owner: "):
            result["owner"] = line[len("Owner: ") :]
        elif match := _DESCRIBE_COL_RE.match(line):
            columns.append(
                {
                    "name": match.group(1),
                    "type": match.group(2),
                    "nullable": match.group(3) == "nullable",
                    "primary_key": bool(match.group(4)),
                }
            )
        elif line.startswith("    ") and columns:
            note = line.strip()
            if note.startswith("[PII: ") and note.endswith("]"):
                columns[-1]["pii"] = note[len("[PII: ") : -1]
            else:
                columns[-1]["comment"] = note
    result["columns"] = columns[:SCHEMA_COLS_MAX]
    result["columns_truncated"] = len(columns) > SCHEMA_COLS_MAX
    summary = f"{_short(result['table'])} · {len(columns)} columns"
    return build(result, summary=summary, text=text, truncated=result["columns_truncated"])


def _flags(raw: str | None) -> tuple[bool, bool, str | None]:
    primary_key = nullable_false = False
    foreign_key = None
    for flag in (part.strip() for part in (raw or "").split(",")):
        if flag == "PK":
            primary_key = True
        elif flag == "NOT NULL":
            nullable_false = True
        elif flag.startswith("FK→"):
            foreign_key = flag[len("FK→") :]
    return primary_key, nullable_false, foreign_key


def project_explore_table(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Table: "):
        return text_result(text, summary=summary_text(text, "Table schema"))
    result: dict[str, Any] = {"kind": "schema", "table": lines[0][len("Table: ") :].strip(), "columns": []}
    columns: list[dict[str, Any]] = []
    foreign_keys: list[dict[str, str]] = []
    referenced_by: list[dict[str, str]] = []
    samples: dict[str, list[str]] = {}
    section = ""
    for line in lines[1:]:
        if line.startswith("Rows: "):
            result["row_count"] = parse_count(line[len("Rows: ") :])
        elif line.startswith("Engine: "):
            result["engine"] = line[len("Engine: ") :]
        elif line == "Columns:" or line.startswith(("Outgoing FKs", "Referenced by", "Sample values")):
            section = line.split(" ")[0]
        elif section == "Columns:" and (match := _EXPLORE_COL_RE.match(line)):
            primary_key, not_null, foreign_key = _flags(match.group(3))
            column: dict[str, Any] = {
                "name": match.group(1),
                "type": match.group(2),
                "nullable": not not_null,
                "primary_key": primary_key,
            }
            if foreign_key:
                column["foreign_key"] = foreign_key
            if match.group(4):
                column["comment"] = match.group(4)
            columns.append(column)
        elif section == "Outgoing" and (match := _FK_LINE_RE.match(line)):
            foreign_keys.append({"column": match.group(1), "references": f"{match.group(2)}.{match.group(3)}"})
        elif section == "Referenced" and (match := _REF_LINE_RE.match(line)):
            referenced_by.append({"table": match.group(1), "column": match.group(2), "references_column": match.group(3)})
        elif section == "Sample" and line.startswith("  ") and ": " in line:
            name, _, values = line.strip().partition(": ")
            samples[name] = [value.strip() for value in values.split(",")][:SAMPLE_VALUES_MAX]
    result["columns"] = columns[:SCHEMA_COLS_MAX]
    result["columns_truncated"] = len(columns) > SCHEMA_COLS_MAX
    if foreign_keys:
        result["foreign_keys"] = foreign_keys
    if referenced_by:
        result["referenced_by"] = referenced_by
    if samples:
        result["sample_values"] = samples
    summary = f"{_short(result['table'])} · {len(columns)} columns"
    if result.get("row_count") is not None:
        summary += f" · {format_count(result['row_count'])} rows"
    return build(result, summary=summary, text=text, truncated=result["columns_truncated"])


def _parse_kv(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(","):
        key, sep, value = part.strip().partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def project_explore_columns(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    lines = text.splitlines()
    header = _PROFILE_HEADER_RE.match(lines[0].strip()) if lines else None
    if header is None:
        return text_result(text, summary=summary_text(text, "Column profile"))
    result: dict[str, Any] = {"kind": "column_profile", "table": header.group(2), "columns": []}
    if header.group(3) != "?":
        result["row_count"] = parse_count(header.group(3))
    columns: list[dict[str, Any]] = []
    for line in lines[1:]:
        if match := _PROFILE_COL_RE.match(line):
            primary_key, not_null, _ = _flags(match.group(3))
            column: dict[str, Any] = {"name": match.group(1), "type": match.group(2)}
            if primary_key:
                column["primary_key"] = True
            column["nullable"] = not not_null
            if match.group(4):
                column["comment"] = match.group(4)
            columns.append(column)
        elif columns and line.startswith("    stats: "):
            stats = _parse_kv(line[len("    stats: ") :])
            if "distinct" in stats:
                columns[-1]["distinct_count"] = parse_count(stats["distinct"])
            if "uniqueness" in stats:
                try:
                    columns[-1]["uniqueness"] = float(stats["uniqueness"])
                except ValueError:
                    pass
        elif columns and line.startswith("    range: "):
            for key, value in _parse_kv(line[len("    range: ") :]).items():
                if key in ("min", "max", "avg"):
                    columns[-1][key] = value
        elif columns and line.startswith("    values: "):
            raw_values = line[len("    values: ") :]
            columns[-1]["sample_values"] = [value.strip().strip("'\"") for value in raw_values.split(", ")][
                :SAMPLE_VALUES_MAX
            ]
    result["columns"] = columns[:SCHEMA_COLS_MAX]
    result["columns_truncated"] = len(columns) > SCHEMA_COLS_MAX
    summary = f"{_short(result['table'])} · {len(columns)} columns profiled"
    return build(result, summary=summary, text=text, truncated=result["columns_truncated"])


def project_explore_column(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Column: "):
        return text_result(text, summary=summary_text(text, "Column profile"))
    qualified = lines[0][len("Column: ") :].strip()
    table, _, name = qualified.rpartition(".")
    column: dict[str, Any] = {"name": name or qualified}
    result: dict[str, Any] = {"kind": "column_profile", "table": table or qualified, "columns": [column]}
    top_values: list[dict[str, Any]] = []
    in_values = False
    for line in lines[1:]:
        if line.startswith("Total rows: "):
            result["row_count"] = parse_count(line[len("Total rows: ") :])
        elif line.startswith("Distinct values: "):
            column["distinct_count"] = parse_count(line[len("Distinct values: ") :])
        elif line.startswith("NULL: "):
            count, _, pct = line[len("NULL: ") :].partition(" (")
            column["null_count"] = parse_count(count)
            try:
                column["null_pct"] = float(pct.rstrip("%)"))
            except ValueError:
                pass
        elif line.startswith("Filter: "):
            result["filter"] = line[len("Filter: ") :]
        elif line.startswith("Top values:"):
            in_values = True
        elif in_values and (match := _TOP_VALUE_RE.match(line)) and len(top_values) < TOP_VALUES_MAX:
            top_values.append({"value": match.group(1), "count": parse_count(match.group(2)) or 0})
    if top_values:
        column["top_values"] = top_values
    result["columns_truncated"] = False
    distinct = column.get("distinct_count")
    summary = f"{qualified} · {format_count(distinct)} distinct" if distinct is not None else qualified
    return build(result, summary=summary, text=text)


def project_schema_text(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    """schema_overview / get_date_boundaries / find_join_path / get_relationships / schema_link."""
    text = content or ""
    return text_result(text, summary=first_line(text) or "Schema information")
