"""Structured parsing of dbt error output — pure regex, no MCP dependency.

Handles both engines:
  dbt-core:  'Database Error in model foo', 'at [12:3]', dbt.exceptions.*
  dbt Fusion: '[error] [DependencyNotFound (dbt1048)]: msg'
              '  --> models/broken.sql:1:15' and DB errors with 'LINE 5:'.

The Fusion type marker is matched FIRST — its dbtNNNN code is the stable
machine identifier the Rust engine introduced; the human-readable core
category is the fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MODEL_PATTERNS = (
    re.compile(r'model\s+"[^.]+\.[^.]+\.([^"]+)"'),
    re.compile(r"(?:Compilation|Database|Runtime|Test)\s+Error\s+in\s+model\s+(\S+)"),
)
_FUSION_TYPE = re.compile(r"\[error\]\s*\[(\w+)\s*\((dbt\d+)\)\]", re.IGNORECASE)
_CORE_TYPE = re.compile(r"(Compilation Error|Database Error|Runtime Error|Test Error|dbt\.exceptions\.\w+)")
# Fusion parse errors point at the offending file: '  --> models/x.sql:1:15'
_ARROW_LOC = re.compile(r"-->\s*(\S+?):(\d+):(\d+)")
_AT_LOC = re.compile(r"at \[(\d+):(\d+)\]")
_LINE_LOC = re.compile(r"line\s+(\d+)", re.IGNORECASE)
_FUSION_MSG = re.compile(r"\[error\]\s*\[[^\]]+\]:\s*(.+)", re.IGNORECASE)
_CORE_MSG = re.compile(r"(?:ERROR|error):\s+(.+)")
_COL_MISSING = re.compile(r'column "?([^"\s]+)"? does not exist', re.IGNORECASE)
_TABLE_MISSING = re.compile(r'(?:table|relation)\s+(?:with name\s+)?"?([^"\s]+)"?\s+does not exist', re.IGNORECASE)


@dataclass
class ParsedDbtError:
    model: str
    error_type: str
    location: str
    message: str
    suggested_fix: str


def parse_dbt_error(error_output: str) -> ParsedDbtError:
    model = "(not detected)"
    for pat in _MODEL_PATTERNS:
        m = pat.search(error_output)
        if m:
            model = m.group(1)
            break

    fusion_type = _FUSION_TYPE.search(error_output)
    core_type = _CORE_TYPE.search(error_output)
    if fusion_type:
        error_type = f"{fusion_type.group(1)} ({fusion_type.group(2)})"
        if core_type:
            error_type = f"{core_type.group(1)} — {fusion_type.group(1)} ({fusion_type.group(2)})"
    elif core_type:
        error_type = core_type.group(1)
    else:
        error_type = "(not detected)"

    if m := _ARROW_LOC.search(error_output):
        location = f"{m.group(1)} line {m.group(2)}, col {m.group(3)}"
    elif m := _AT_LOC.search(error_output):
        location = f"line {m.group(1)}, col {m.group(2)}"
    elif m := _LINE_LOC.search(error_output):
        location = f"line {m.group(1)}"
    else:
        location = "(not detected)"

    msg_match = _CORE_MSG.search(error_output) or _FUSION_MSG.search(error_output)
    message = msg_match.group(1).strip() if msg_match else "(not detected)"

    error_lower = error_output.lower()
    col_missing = _COL_MISSING.search(error_output)
    table_missing = _TABLE_MISSING.search(error_output)
    if col_missing:
        suggested_fix = (
            f"Check column name {col_missing.group(1)} in your SELECT. "
            "Use check_model_schema to compare actual vs expected columns."
        )
    elif table_missing:
        tbl = table_missing.group(1)
        suggested_fix = f"Model {tbl} has not been materialized. Run `dbt run --select {tbl}` first."
    elif "syntax error" in error_lower:
        suggested_fix = "Review the SQL at the indicated line number."
    elif "ambiguous column" in error_lower:
        suggested_fix = "Qualify the column with a table alias."
    elif "divide by zero" in error_lower or "division by zero" in error_lower:
        suggested_fix = "Wrap denominator in NULLIF(denominator, 0)."
    elif "unique constraint" in error_lower:
        suggested_fix = "Deduplicate source data or add a ROW_NUMBER() window to resolve duplicates."
    else:
        suggested_fix = "Review the error message above."

    return ParsedDbtError(
        model=model,
        error_type=error_type,
        location=location,
        message=message,
        suggested_fix=suggested_fix,
    )
