"""dbt project tools: dbt_project_map, dbt_project_validate, dbt_error_parser, generate_sql_skeleton."""

from __future__ import annotations

import re

from gateway.dbt import (
    build_project_map as _build_project_map,
)
from gateway.dbt import (
    format_validation_result as _format_validation_result,
)
from gateway.dbt import (
    validate_project as _validate_project,
)
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _is_cloud
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MODEL_NAME_RE

if not _is_cloud:

    @audited_tool(mcp)
    async def dbt_project_map(
        project_dir: str,
        focus: str = "all",
        max_models_per_section: int = 40,
        include_columns: bool = False,
    ) -> str:
        """
        Yml-direct dbt project discovery — fast, comprehensive, broken-project safe.

        Scans a dbt project directory and returns a compact, LLM-optimized markdown
        view of every model (complete, stub, missing, or orphan), every source,
        every macro, plus a topologically-sorted work order for actionable models.

        Unlike `dbt parse`, this tool DOES NOT depend on dbt itself — it reads yml
        files and sql files directly with PyYAML and regex. That means it works on
        broken projects, projects with missing packages, projects with no profile,
        and projects where dbt parse would refuse to run. Critically, it surfaces
        missing-model yml entries that `dbt parse` silently drops as "orphan
        patches" — the exact thing the agent needs to find.

        Args:
            project_dir: absolute path to the dbt project root (where dbt_project.yml lives)
            focus: which view to render. One of:
                - "all" (default): full project overview grouped by directory
                - "work_order": just the actionable models in build order, with deps + columns
                - "missing": only models defined in yml but with no .sql file
                - "stubs": only sql files classified as incomplete/stubbed
                - "sources": source namespaces with their tables
                - "macros": available custom macros grouped by file
                - "model:<name>": deep-dive on one model (columns, deps, tests, description)
            max_models_per_section: per-section truncation threshold (default 40)
            include_columns: include column lists inline for complete models (default off)

        Returns:
            markdown-formatted project map
        """
        import asyncio

        from gateway.deployment import is_cloud_mode

        if is_cloud_mode():
            return "Error: dbt project map is not available in cloud mode"
        if not project_dir or not project_dir.strip():
            return "Error: project_dir is required"
        # Offload the sync scan + render to a worker thread so the MCP event loop
        # stays responsive on large projects.
        return await asyncio.to_thread(
            _build_project_map,
            project_dir.strip(),
            focus,
            max_models_per_section,
            include_columns,
        )

    @audited_tool(mcp)
    async def dbt_project_validate(
        project_dir: str,
        timeout: int = 60,
    ) -> str:
        """
        Run `dbt parse` against a project and surface structural errors + warnings.

        This is the pre-build validation step — does the project compile? Use it
        when the agent suspects a problem (after editing yml files, after adding
        new models, before running `dbt run`). Much cheaper than `dbt run` because
        it does not execute any SQL, but catches the same class of Jinja / ref /
        source / yml-syntax errors that would fail a run.

        Output includes:
          - success/failure + degradation mode (profile_missing, packages_missing,
            parse_failed, dbt_not_installed, timeout, etc.)
          - error list with context
          - orphan-patch list (yml-defined models with no .sql file — the "missing
            models" that `dbt_project_map` surfaces via the yml-direct path)
          - non-orphan warnings

        Args:
            project_dir: absolute path to the dbt project root
            timeout: subprocess timeout in seconds (default 60, clamped to 1-300)

        Returns:
            markdown-formatted validation report
        """
        import asyncio
        from pathlib import Path as _Path

        from gateway.deployment import is_cloud_mode

        if is_cloud_mode():
            return "Error: dbt project validation is not available in cloud mode"
        if not project_dir or not project_dir.strip():
            return "Error: project_dir is required"

        clean_dir = project_dir.strip()

        # Require absolute path to prevent relative path confusion.
        if not _Path(clean_dir).is_absolute():
            return "Error: project_dir must be an absolute path"

        # Reject path traversal — check resolved path for .. segments.
        try:
            resolved = _Path(clean_dir).resolve()
        except (ValueError, OSError) as exc:
            return f"Error: invalid project_dir: {exc}"

        # Reject if any part of the original (unresolved) path contains .. segments.
        if ".." in _Path(clean_dir).parts:
            return "Error: project_dir must not contain '..' segments"

        # Clamp timeout to a safe range: minimum 1s, maximum 300s (5 minutes).
        clamped_timeout = max(1, min(timeout, 300))

        # _validate_project calls subprocess.run, which would block this handler's
        # event loop and can stall MCP heartbeats on Windows. Offload to a thread.
        result = await asyncio.to_thread(
            _validate_project,
            str(resolved),
            clamped_timeout,
        )
        return _format_validation_result(result)

    @audited_tool(mcp)
    async def dbt_error_parser(error_output: str) -> str:
        """
        Parse raw dbt stderr/stdout and extract structured, actionable error info.

        No LLM involved — pure regex and string pattern matching against common
        dbt error formats. Provides a suggested fix for known error categories.

        Args:
            error_output: Raw dbt command output (stderr or combined stdout/stderr)

        Returns:
            Structured error summary with model name, type, location, message, and suggested fix.
        """
        from gateway.deployment import is_cloud_mode

        if is_cloud_mode():
            return "Error: dbt error parsing is not available in cloud mode"
        if not error_output or not error_output.strip():
            return "Error: error_output cannot be empty."

        model_match = re.search(r'model\s+"[^.]+\.[^.]+\.([^"]+)"', error_output) or re.search(
            r"(?:Compilation|Database|Runtime|Test)\s+Error\s+in\s+model\s+(\S+)", error_output
        )
        model_name = model_match.group(1) if model_match else "(not detected)"

        type_match = re.search(
            r"(Compilation Error|Database Error|Runtime Error|Test Error|dbt\.exceptions\.\w+)", error_output
        )
        error_type = type_match.group(1) if type_match else "(not detected)"

        location_match = re.search(r"at \[(\d+):(\d+)\]", error_output) or re.search(r"[Ll]ine\s+(\d+)", error_output)
        if location_match:
            location = (
                f"line {location_match.group(1)}"
                if len(location_match.groups()) == 1
                else f"line {location_match.group(1)}, col {location_match.group(2)}"
            )
        else:
            location = "(not detected)"

        msg_match = re.search(r"(?:ERROR|error):\s+(.+)", error_output)
        core_message = msg_match.group(1).strip() if msg_match else "(not detected)"

        error_lower = error_output.lower()
        col_missing = re.search(r'column "?([^"\s]+)"? does not exist', error_output, re.IGNORECASE)
        table_missing = re.search(r'(?:table|relation)\s+"?([^"\s]+)"?\s+does not exist', error_output, re.IGNORECASE)

        if col_missing:
            col = col_missing.group(1)
            suggested_fix = (
                f"Check column name {col} in your SELECT. Use check_model_schema to compare actual vs expected columns."
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

        lines = [
            "dbt Error Summary:",
            f"  Model: {model_name}",
            f"  Type: {error_type}",
            f"  Location: {location}",
            f"  Message: {core_message}",
            f"  Suggested fix: {suggested_fix}",
        ]
        return "\n".join(lines)


@audited_tool(mcp)
async def generate_sql_skeleton(model_name: str, yml_columns: str, ref_tables: str = "") -> str:
    """
    Generate a dbt SQL template from a YML column spec.

    Produces a properly structured Jinja SQL file with config block, source
    CTEs using {{ ref() }}, and a final CTE listing all expected output columns
    as null placeholders. Helps agents start from the correct shape.

    Args:
        model_name: Name of the dbt model being scaffolded
        yml_columns: Comma-separated list of expected output column names
        ref_tables: Optional comma-separated list of upstream ref() table names

    Returns:
        A dbt-compatible SQL skeleton string.
    """
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not yml_columns or not yml_columns.strip():
        return "Error: yml_columns cannot be empty."

    columns: list[str] = [c.strip() for c in yml_columns.split(",") if c.strip()]
    if not columns:
        return "Error: No column names found in yml_columns."

    refs: list[str] = [t.strip() for t in ref_tables.split(",") if t.strip()] if ref_tables else []

    col_lines = "\n".join(f"        null as {col}," for col in columns)
    # Remove trailing comma from last column line
    col_lines = col_lines.rstrip(",")

    config_block = "{{\n    config(\n        materialized='table'\n    )\n}}"

    if refs:
        cte_blocks = []
        for ref_table in refs:
            cte_blocks.append(f"{ref_table} as (\n\n    select * from {{{{ ref('{ref_table}') }}}}\n\n)")
        source_ctes = ",\n\n".join(cte_blocks)
        from_clause = refs[0]
    else:
        source_ctes = (
            "source as (\n\n    -- TODO: replace SOURCE_TABLE\n    select * from {{{{ ref('SOURCE_TABLE') }}}}\n\n)"
        )
        from_clause = "source"

    sql = (
        f"{config_block}\n\n"
        f"with\n\n"
        f"{source_ctes},\n\n"
        f"final as (\n\n"
        f"    select\n\n"
        f"        -- TODO: fill in transformations\n"
        f"{col_lines}\n\n"
        f"    from {from_clause}\n\n"
        f")\n\n"
        f"select * from final"
    )
    return sql
