"""Projectors for the query tools (query_database, validate_sql, plans).

The text formats parsed here are produced by ``gateway/mcp/tools/query.py``.
Keep the two in sync: a format drift degrades to ``kind="text"`` and never
breaks a run, but the card loses its structure.
"""

from __future__ import annotations

import re
from typing import Any

from gateway.standalone_chat.tool_projection.base import ProjectedResult, build, text_result
from gateway.standalone_chat.tool_projection.limits import (
    CELL_MAX,
    TABLE_COLS_MAX,
    TABLE_ROWS_MAX,
)
from gateway.standalone_chat.tool_projection.text import (
    compact_json,
    first_line,
    format_count,
    format_ms,
    parse_count,
    parse_ms,
    summary_text,
    try_json,
)

_FOOTER_RE = re.compile(r"\[(\d+) rows, (\d+)ms, result ([0-9a-fA-F-]+), completeness: (\w+)\]")
_ZERO_ROWS_RE = re.compile(r"^Query returned 0 rows \(0 rows, (\d+)ms, result ([0-9a-fA-F-]+), completeness: (\w+)\)")
_INCOMPLETE_RE = re.compile(r"^\[INCOMPLETE DISPLAY\] (\d+) rows total; only the first (\d+) are shown above\.")
_COMPLETENESS_NOTE_RE = re.compile(r"^Completeness note: (.*)$")
_PII_RE = re.compile(r"\[PII REDACTED\] The following columns were redacted by policy: (.*?)\. Values shown")
_ESTIMATED_ROWS_RE = re.compile(r"Estimated rows:\s*([\d,]+)")
_ESTIMATED_USD_RE = re.compile(r"Estimated (?:USD|cost):\s*\$([\d.]+)")
_SEPARATOR = " | "


_INT_RE = re.compile(r"^-?\d{1,18}$")
_FLOAT_RE = re.compile(r"^-?\d{1,18}\.\d+$")


def _cell(value: str) -> Any:
    """Coerce one pipe-table cell: None/NULL, ints and plain decimals become
    typed values so the card can right-align numbers; everything else stays text."""
    text = value.strip()
    if text in ("None", "NULL"):
        return None
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        try:
            return float(text)
        except ValueError:
            return text
    if text in ("True", "False"):
        return text == "True"
    if len(text) > CELL_MAX:
        return text[:CELL_MAX] + "…"
    return text


def _parse_table_lines(lines: list[str]) -> tuple[list[dict[str, Any]], list[list[Any]], int]:
    """Parse header / dash / pipe rows. Returns (columns, rows, shown)."""
    if len(lines) < 2 or not set(lines[1].strip()) <= {"-"}:
        return [], [], 0
    names = lines[0].split(_SEPARATOR)
    columns = [{"name": name.strip(), "logical_type": None} for name in names]
    rows: list[list[Any]] = []
    shown = 0
    for line in lines[2:]:
        if line.startswith(("[INCOMPLETE DISPLAY]", "Completeness note:")):
            break
        shown += 1
        if len(rows) >= TABLE_ROWS_MAX:
            continue
        parts = line.split(_SEPARATOR)
        # Pipes inside cell text make the split ambiguous; keep the row
        # width stable and let the structured enrichment fix the values.
        if len(parts) > len(names):
            parts = [*parts[: len(names) - 1], _SEPARATOR.join(parts[len(names) - 1 :])]
        elif len(parts) < len(names):
            parts = [*parts, *([""] * (len(names) - len(parts)))]
        rows.append([_cell(part) for part in parts[:TABLE_COLS_MAX]])
    return columns, rows, shown


def _table_summary(row_count: int | None, preview: int, execution_ms: float | None) -> str:
    timing = format_ms(execution_ms)
    suffix = f" · {timing}" if timing else ""
    if row_count is not None and preview < row_count:
        return f"Preview {preview:,} of {format_count(row_count)} rows{suffix}"
    total = row_count if row_count is not None else preview
    return f"{format_count(total)} row{'s' if total != 1 else ''}{suffix}"


def project_query_database(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    stripped = text.strip()
    if stripped.startswith("Query error:"):
        return text_result(text, summary=first_line(text))
    parsed = try_json(stripped)
    if isinstance(parsed, dict):
        route = parsed.get("route")
        summary = f"Route: {route}" if route else summary_text(text, "Query planned")
        if parsed.get("approval_required"):
            summary += " · approval required"
        return build({"kind": "json", "value": compact_json(parsed)}, summary=summary, text=text)
    zero = _ZERO_ROWS_RE.match(stripped)
    if zero:
        execution_ms = parse_ms(zero.group(1))
        result = _table(
            columns=[],
            rows=[],
            preview=0,
            row_count=0,
            execution_ms=execution_ms,
            result_id=zero.group(2),
            completeness=zero.group(3),
            pii=_pii_columns(text),
        )
        return build(result, summary=_table_summary(0, 0, execution_ms), text=text)
    footer = _FOOTER_RE.search(text)
    if footer is None:
        return text_result(text, summary=summary_text(text, "Query completed"))
    body = text[: footer.start()].rstrip()
    lines = body.split("\n")
    columns, rows, shown = _parse_table_lines(lines)
    if not columns:
        return text_result(text, summary=summary_text(text, "Query completed"))
    row_count = parse_count(footer.group(1))
    execution_ms = parse_ms(footer.group(2))
    incomplete = next((m for m in map(_INCOMPLETE_RE.match, lines) if m), None)
    note = next((m for m in map(_COMPLETENESS_NOTE_RE.match, lines) if m), None)
    if incomplete:
        shown = int(incomplete.group(2))
    completeness = footer.group(4)
    result = _table(
        columns=columns[:TABLE_COLS_MAX],
        rows=rows,
        preview=shown,
        row_count=row_count,
        execution_ms=execution_ms,
        result_id=footer.group(3),
        completeness=completeness if completeness in ("complete", "truncated") else "unknown",
        truncation_reason=note.group(1) if note else None,
        columns_truncated=len(columns) > TABLE_COLS_MAX,
        pii=_pii_columns(text),
    )
    return build(
        result,
        summary=_table_summary(row_count, shown, execution_ms),
        text=text,
        truncated=bool(result["preview_truncated"] or result["columns_truncated"]),
    )


def _pii_columns(text: str) -> list[str]:
    match = _PII_RE.search(text)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _table(
    *,
    columns: list[dict[str, Any]],
    rows: list[list[Any]],
    preview: int,
    row_count: int | None,
    execution_ms: float | None,
    result_id: str | None,
    completeness: str,
    truncation_reason: str | None = None,
    columns_truncated: bool = False,
    pii: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "table",
        "columns": columns,
        "rows": rows,
        "preview_row_count": preview,
        "row_count": row_count,
        "preview_truncated": (row_count is not None and len(rows) < row_count) or len(rows) < preview,
        "columns_truncated": columns_truncated,
        "result_id": result_id,
        "execution_ms": execution_ms,
        "completeness": completeness,
        "truncation_reason": truncation_reason,
        "source": "parsed",
    }
    if pii:
        result["pii_redacted_columns"] = pii
    return result


def project_validate_sql(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    lines = text.splitlines()
    head = lines[0].strip() if lines else ""
    result: dict[str, Any] = {"kind": "validation", "valid": False}
    if head.startswith("VALID"):
        result["valid"] = True
        summary = "Valid"
        checks: list[str] = []
        for line in lines[1:]:
            line = line.strip()
            match = _ESTIMATED_ROWS_RE.match(line)
            if match:
                result["estimated_rows"] = parse_count(match.group(1))
                summary = f"Valid · ~{format_count(result['estimated_rows'])} rows"
            elif line.startswith("Warning: query may be expensive"):
                result["expensive"] = True
            elif line.startswith("Local checks:"):
                checks = [part.strip() for part in line[len("Local checks:") :].split(";") if part.strip()]
        if checks:
            result["checks"] = checks
        return build(result, summary=summary, text=text)
    body: list[str] = []
    for line in lines[1:]:
        if line.strip().startswith("Suggested fix:"):
            result["suggested_fix"] = line.strip()[len("Suggested fix:") :].strip()
        elif line.strip():
            body.append(line.strip())
    if head.startswith("INVALID"):
        message = "\n".join(body) or head
    else:
        message = "\n".join([head, *body]).strip()
    if message:
        result["message"] = message
    return build(result, summary=f"Invalid · {first_line(message) or 'validation failed'}", text=text)


def project_explain_query(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    rows = _ESTIMATED_ROWS_RE.search(text)
    summary = f"Plan · ~{format_count(parse_count(rows.group(1)))} rows" if rows else "Query plan"
    if "WARNING" in text:
        summary += " · expensive"
    return text_result(text, summary=summary)


def project_estimate_query_cost(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    rows = _ESTIMATED_ROWS_RE.search(text)
    usd = _ESTIMATED_USD_RE.search(text)
    parts = []
    if rows:
        parts.append(f"~{format_count(parse_count(rows.group(1)))} rows")
    if usd:
        parts.append(f"${usd.group(1)}")
    if "WARNING" in text:
        parts.append("expensive")
    return text_result(text, summary=" · ".join(parts) if parts else summary_text(text, "Cost estimate"))


def project_plan_query(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    parsed = try_json(text)
    if isinstance(parsed, dict):
        route = parsed.get("route")
        summary = f"Route: {route}" if route else "Query planned"
        if parsed.get("approval_required"):
            summary += " · approval required"
        return build({"kind": "json", "value": compact_json(parsed)}, summary=summary, text=text)
    return text_result(text, summary=summary_text(text, "Query planned"))
