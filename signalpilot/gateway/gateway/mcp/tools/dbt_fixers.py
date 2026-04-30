"""dbt fixer tools: fix_date_spine_hazards, fix_nondeterminism_hazards (cloud-gated)."""

from __future__ import annotations

from gateway.dbt.date_spine_fixer import generate_date_spine_fixes
from gateway.dbt.inventory import scan_project as _scan_project
from gateway.dbt.nondeterminism_fixer import (
    build_table_columns_from_schema,
    generate_nondeterminism_fixes,
)
from gateway.errors.mcp import sanitize_mcp_error
from gateway.governance.context import current_org_id_var
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _is_cloud, _store_session
from gateway.mcp.helpers import _extract_replacement_snippet, _fetch_date_boundaries, _find_hazard_table_date
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name

if not _is_cloud:

    @audited_tool(mcp)
    async def fix_date_spine_hazards(
        project_dir: str,
        connection_name: str,
        replacement_date: str = "",
    ) -> str:
        """
        Auto-fix all date spine hazards in a dbt project in one call.

        Reads the project scan to find all current_date/current_timestamp/now() hazards,
        then creates local override files for package models and edits project models
        in-place. Uses the largest-table max date from the connection as the replacement
        literal date, or an explicit replacement_date if provided.

        Args:
            project_dir: Absolute path to the dbt project root.
            connection_name: Name of a configured database connection (used to auto-detect
                             the replacement date from the largest fact table).
            replacement_date: Optional override date string like "2022-01-31". If omitted,
                              the date is auto-detected from the connection's largest table.

        Returns:
            Markdown report listing every file created/modified and a dbt run command.
        """
        from pathlib import Path as _Path

        if err := _validate_connection_name(connection_name):
            return f"Error: {err}"

        project_path = _Path(project_dir)
        if not project_path.exists():
            return f"Error: project directory does not exist: {project_dir}"

        # Determine the replacement date and whether to add a +1 day offset.
        # add_day_offset=True only when the date comes from raw source data (global_max),
        # where max_data_date + 1 = current_date. When the date comes from a pre-existing
        # hazard table or is provided explicitly by the caller, it already reflects the
        # correct current_date value, so no offset is needed.
        resolved_date: str
        date_source: str
        add_day_offset: bool
        if replacement_date.strip():
            resolved_date = replacement_date.strip()
            date_source = f"{resolved_date} (provided explicitly)"
            add_day_offset = False
        else:
            try:
                boundaries = await _fetch_date_boundaries(connection_name)
            except Exception as e:
                return f"Error fetching date boundaries: {sanitize_mcp_error(str(e))}"

            if not boundaries.found_any:
                return (
                    f"Error: No DATE/TIMESTAMP columns found in connection '{connection_name}'. "
                    "Pass replacement_date explicitly."
                )

            # Strategy: look for the hazard model(s) as pre-existing tables in the
            # DB — their max date reflects the gold generation date. This is more
            # reliable than global_max (which picks up outlier dates from raw data,
            # e.g. purchase orders dated 2050) or largest_table_max (which misses
            # derived tables that aren't the largest).
            hazard_date = await _find_hazard_table_date(connection_name, project_path, boundaries)
            if hazard_date:
                resolved_date, date_source = hazard_date
                add_day_offset = False
            elif boundaries.global_max:
                resolved_date = boundaries.global_max
                date_source = f"{resolved_date} (global max date — no hazard table found)"
                add_day_offset = True
            else:
                return (
                    f"Error: Could not determine a replacement date from connection '{connection_name}'. "
                    "Pass replacement_date explicitly."
                )

        # Scan the project to get hazards.
        project = _scan_project(project_path)
        hazards = project.date_hazards

        if not hazards:
            return "No date spine hazards found — nothing to fix."

        # Generate fixes (pure, no I/O).
        try:
            fixes = generate_date_spine_fixes(project_path, hazards, resolved_date, add_day_offset)
        except OSError as e:
            return f"Error reading source files: {sanitize_mcp_error(str(e))}"

        # Write files.
        written: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        for fix in fixes:
            if fix.already_overridden:
                skipped.append(fix.original_path)
                continue
            try:
                fix.output_path.parent.mkdir(parents=True, exist_ok=True)
                fix.output_path.write_text(fix.content, encoding="utf-8")
                written.append(fix.output_path.name.removesuffix(".sql"))
            except OSError as e:
                errors.append(f"{fix.output_path.name}: {sanitize_mcp_error(str(e), cap=100)}")

        # Build markdown report.
        report_lines = [
            f"## Date spine hazards fixed ({len([f for f in fixes if not f.already_overridden])} files)",
            "",
        ]

        item_num = 0
        for fix in fixes:
            if fix.already_overridden:
                report_lines.append(f"  SKIPPED {fix.original_path} — override already exists")
                continue

            item_num += 1
            action = "CREATED" if fix.is_package else "MODIFIED"
            out_rel = str(fix.output_path.relative_to(project_path))

            # Include a short snippet: first replacement found in context.
            snippet = _extract_replacement_snippet(fix.content, resolved_date)
            snippet_str = f"\n     snippet: {snippet}" if snippet else ""

            patterns_str = ", ".join(fix.patterns_replaced) if fix.patterns_replaced else "unknown"
            if fix.is_package:
                report_lines.append(
                    f"{item_num}. {action} {out_rel} (override of {fix.original_path})\n"
                    f"   Replaced: {patterns_str} -> ('{resolved_date}'::date + INTERVAL '1 day'){snippet_str}"
                )
            else:
                report_lines.append(
                    f"{item_num}. {action} {out_rel} (project model, edited in-place)\n"
                    f"   Replaced: {patterns_str} -> ('{resolved_date}'::date + INTERVAL '1 day'){snippet_str}"
                )

        if errors:
            report_lines.append("")
            report_lines.append("## Errors")
            for err in errors:
                report_lines.append(f"  - {err}")

        if written:
            model_list = " ".join(written)
            report_lines.append("")
            report_lines.append(f"Verify: dbt run --select {model_list}")

        report_lines.append("")
        report_lines.append(f"Date used: {date_source}")

        return "\n".join(report_lines)

    @audited_tool(mcp)
    async def fix_nondeterminism_hazards(
        project_dir: str,
        connection_name: str,
    ) -> str:
        """
        Auto-fix all non-deterministic window function hazards in a dbt project.

        Finds ROW_NUMBER/RANK/DENSE_RANK OVER(...) clauses whose ORDER BY may not be
        unique, then appends a tiebreaker column (first *_id column found in referenced
        tables) to each ambiguous ORDER BY.

        Creates local override files for package models; edits project models in-place.
        If the DB connection is unavailable, skips all fixes and returns a warning
        listing the affected models for manual review.

        Args:
            project_dir: Absolute path to the dbt project root.
            connection_name: Name of a configured database connection (used to discover
                             column names for tiebreaker selection).

        Returns:
            Markdown report listing every file fixed and a dbt run --select command.
        """
        from pathlib import Path as _Path

        if err := _validate_connection_name(connection_name):
            return f"Error: {err}"

        project_path = _Path(project_dir)
        if not project_path.exists():
            return f"Error: project directory does not exist: {project_dir}"

        # Scan the project to get nd_warnings.
        project = _scan_project(project_path)
        nd_warnings = project.nondeterminism_warnings

        if not nd_warnings:
            return "No non-determinism hazards found — nothing to fix."

        # Fetch schema to build table->columns map (graceful degradation if unavailable).
        table_columns: dict[str, list[str]] = {}
        schema_error: str = ""

        tool_org_id: str
        async with _store_session() as store:
            tool_org_id = store.org_id or "local"
            conn_info = await store.get_connection(connection_name)
            if not conn_info:
                available = [c.name for c in await store.list_connections()]
                conn_str = None
                extras = None
            else:
                conn_str = await store.get_connection_string(connection_name)
                extras = await store.get_credential_extras(connection_name) if conn_str else None

        if not conn_info:
            schema_error = (
                f"Connection '{connection_name}' not found (available: {available}). "
                "Tiebreaker selection skipped — all patterns will need manual fixes."
            )
        else:
            if not conn_str:
                schema_error = "No credentials stored for this connection. Tiebreaker selection skipped."
            else:
                from gateway.connectors.pool_manager import pool_manager
                from gateway.connectors.schema_cache import schema_cache

                _org_token = current_org_id_var.set(tool_org_id)
                try:
                    schema = schema_cache.get(connection_name)
                    if schema is None:
                        try:
                            async with pool_manager.connection(
                                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                            ) as connector:
                                schema = await connector.get_schema()
                            schema_cache.put(connection_name, schema)
                        except Exception as e:
                            schema_error = (
                                f"Could not fetch schema: {sanitize_mcp_error(str(e))}. Tiebreaker selection skipped."
                            )
                            schema = {}
                    table_columns = build_table_columns_from_schema(schema)
                finally:
                    current_org_id_var.reset(_org_token)

        # Generate fixes (pure, no I/O).
        try:
            fixes = generate_nondeterminism_fixes(project_path, nd_warnings, table_columns)
        except OSError as e:
            return f"Error reading source files: {sanitize_mcp_error(str(e))}"

        # Write files.
        written: list[str] = []
        skipped_files: list[str] = []
        errors: list[str] = []

        for fix in fixes:
            if fix.already_overridden:
                skipped_files.append(fix.original_path)
                continue
            if not fix.content:
                # No content means nothing could be fixed (no tiebreaker, read error, etc.)
                skipped_files.append(fix.original_path)
                continue
            if not fix.fixes_applied:
                # Parsed OK but nothing needed changing.
                skipped_files.append(fix.original_path)
                continue
            try:
                fix.output_path.parent.mkdir(parents=True, exist_ok=True)
                fix.output_path.write_text(fix.content, encoding="utf-8")
                written.append(fix.output_path.name.removesuffix(".sql"))
            except OSError as e:
                errors.append(f"{fix.output_path.name}: {sanitize_mcp_error(str(e), cap=100)}")

        # Build markdown report.
        total_fixed = len([f for f in fixes if f.fixes_applied and not f.already_overridden])
        report_lines = [f"## Non-determinism hazards fixed ({total_fixed} files)", ""]

        if schema_error:
            report_lines.append(f"Warning: {schema_error}")
            report_lines.append("")

        item_num = 0
        for fix in fixes:
            if fix.already_overridden:
                report_lines.append(f"  SKIPPED {fix.original_path} — override already exists")
                continue

            if not fix.fixes_applied and not fix.skipped_patterns:
                continue

            item_num += 1
            if fix.fixes_applied:
                action = "CREATED" if fix.is_package else "MODIFIED"
                try:
                    out_rel = str(fix.output_path.relative_to(project_path))
                except ValueError:
                    out_rel = str(fix.output_path)
                source_note = f" (override of {fix.original_path})" if fix.is_package else " (edited in-place)"
                report_lines.append(f"{item_num}. {action} {out_rel}{source_note}")
                for applied in fix.fixes_applied:
                    report_lines.append(f"   Fixed: {applied}")

            for skipped in fix.skipped_patterns:
                report_lines.append(f"   SKIPPED: {skipped}")

        if errors:
            report_lines.append("")
            report_lines.append("## Errors")
            for err in errors:
                report_lines.append(f"  - {err}")

        if written:
            model_list = " ".join(written)
            report_lines.append("")
            report_lines.append(f"Verify: dbt run --select {model_list}")

        return "\n".join(report_lines)
