"""
LLM-optimized markdown rendering of a ProjectMap.

Design goals:
  - Compact: sub-2k tokens for chinook001-sized projects, sub-5k for synthea001
  - Self-explanatory: an LLM should know how to act on the output with no docs
  - Action-oriented: missing + stub models are prominent, complete models are
    summarized, orphans are noted
  - Focus-aware: the agent can ask for a targeted view instead of the whole map
  - Token-budgeted: truncates long sections with explicit "(+N more)" tails

Focus modes:
  - "all" (default): full project overview with all sections
  - "work_order": just the actionable models in build order
  - "missing": only models that need to be written from scratch
  - "stubs": only incomplete sql files that need rewriting
  - "sources": source tables grouped by namespace
  - "macros": available custom macros
  - "model:<name>": deep-dive on a single model (columns, deps, tests)

Icons used consistently across the output:
  ✓ complete       ⚠ stub           ✗ missing           ?  orphan (no yml)
  ←  depends on   →  blocks          •  list marker
"""

from __future__ import annotations

from pathlib import Path

from .inventory import scan_project
from .types import ModelInfo, ModelStatus, ProjectMap

# ── Icons ────────────────────────────────────────────────────────────────────

_ICON = {
    ModelStatus.COMPLETE: "✓",
    ModelStatus.STUB:     "⚠",
    ModelStatus.MISSING:  "✗",
    ModelStatus.ORPHAN:   "?",
}


def render_project_map(
    project_dir: str | Path,
    focus: str = "all",
    max_models_per_section: int = 40,
    include_columns: bool = False,
) -> str:
    """Scan and render a dbt project (uncached).

    This is the raw renderer. Callers should normally go through
    `gateway.dbt.build_project_map`, which adds an mtime-invalidated cache
    on top. Exposed here for tests and for callers that want to bypass the
    cache entirely.

    Args:
        project_dir: absolute path to the dbt project root
        focus: one of "all", "work_order", "missing", "stubs", "sources",
            "macros", or "model:<name>"
        max_models_per_section: per-section truncation threshold (prevents
            thousand-model projects from blowing out the prompt)
        include_columns: include column lists inline for complete models
            (expensive; default off)

    Returns:
        markdown-formatted string
    """
    project_dir = Path(project_dir)
    if not project_dir.exists():
        return f"Error: project directory does not exist: {project_dir}"

    project = scan_project(project_dir)

    focus = (focus or "all").strip()
    if focus.startswith("model:"):
        return render_single_model(project, focus[len("model:"):].strip())
    if focus == "work_order":
        return render_work_order(project)
    if focus == "missing":
        return render_filtered(project, {ModelStatus.MISSING}, "Missing Models")
    if focus == "stubs":
        return render_filtered(project, {ModelStatus.STUB}, "Stub Models")
    if focus == "sources":
        return render_sources(project)
    if focus == "macros":
        return render_macros(project)
    return render_full(project, max_models_per_section, include_columns)


# ── Full overview ────────────────────────────────────────────────────────────


def render_full(
    project: ProjectMap,
    max_per_section: int,
    include_columns: bool,
) -> str:
    lines: list[str] = []
    lines.append(_header(project))
    lines.append("")

    # Counts line — glance summary at the top.
    lines.append(
        f"Models: {project.model_count} total "
        f"({_ICON[ModelStatus.COMPLETE]} {project.complete_count} complete, "
        f"{_ICON[ModelStatus.STUB]} {project.stub_count} stub, "
        f"{_ICON[ModelStatus.MISSING]} {project.missing_count} missing, "
        f"{_ICON[ModelStatus.ORPHAN]} {project.orphan_count} orphan). "
        f"Sources: {len(project.sources)}. Macros: {len(project.macros)}. "
        f"Packages: {len(project.packages)}."
    )
    if project.parse_errors:
        lines.append(f"⚠ {len(project.parse_errors)} yml parse error(s) — see 'Parse errors' section below.")

    if project.current_date_warnings:
        lines.append("")
        lines.append(f"## ⚠ ACTION REQUIRED: Date spine uses CURRENT_DATE ({len(project.current_date_warnings)} hits)")
        lines.append("These models will produce WRONG ROW COUNTS because they generate rows up to today's date.")
        lines.append("You MUST edit these files BEFORE running dbt or writing new models:")
        for w in project.current_date_warnings[:15]:
            lines.append(f"  {w['file']}:{w['line']} — `{w['match']}`")
        if len(project.current_date_warnings) > 15:
            lines.append(f"  (+{len(project.current_date_warnings) - 15} more)")
        lines.append("")
        lines.append("FIX: Open each file above and replace `current_date` (or equivalent) with the max date")
        lines.append("from the source data. Steps:")
        lines.append("  1. Query the source table that feeds the spine: SELECT MAX(date_col) FROM source_table")
        lines.append("  2. Replace `current_date` with a cast of that date: cast('YYYY-MM-DD' as date)")
        lines.append("  3. If the file uses `greatest(max_date, current_date)`, remove the greatest() and keep only max_date")
        lines.append("Do NOT skip this — pre-existing models are NOT read-only. Edit them directly.")

    lines.append("")

    # Models by directory
    groups = project.models_by_directory()
    for directory, items in groups.items():
        lines.extend(_render_group(directory, items, max_per_section, include_columns))
        lines.append("")

    # Work order — the actionable list in build order
    if project.work_order:
        lines.append("## Work order (build in this sequence)")
        for i, name in enumerate(project.work_order, 1):
            m = project.models.get(name)
            if not m:
                continue
            deps = _format_dep_list(m, project)
            status_icon = _ICON[m.status]
            col_hint = f" [{len(m.columns)} cols]" if m.columns else ""
            lines.append(f"  {i:>2}. {status_icon} {name}{col_hint}{deps}")
        if project.cycles:
            lines.append("")
            lines.append("  ⚠ CYCLES DETECTED (resolve before building):")
            for cycle in project.cycles:
                lines.append(f"    {' → '.join(cycle)}")
        if project.unresolved_refs:
            lines.append("")
            lines.append("  ⚠ UNRESOLVED REFS (ref() targets that don't exist in this project):")
            for name, refs in sorted(project.unresolved_refs.items()):
                lines.append(f"    {name}: {', '.join(refs)}")
        lines.append("")

    # Sources (compact)
    if project.sources:
        lines.append(f"## Sources ({len(project.sources)})")
        for src_name in sorted(project.sources):
            src = project.sources[src_name]
            schema_hint = f" ({src.schema})" if src.schema else ""
            table_list = ", ".join(src.tables[:10])
            if len(src.tables) > 10:
                table_list += f", +{len(src.tables) - 10} more"
            lines.append(f"  • {src_name}{schema_hint} [{len(src.tables)} tables]: {table_list}")
        lines.append("")

    # Macros (compact)
    if project.macros:
        lines.append(f"## Macros ({len(project.macros)})")
        macro_names = sorted(project.macros)
        show = macro_names[:max_per_section]
        for name in show:
            mc = project.macros[name]
            sig = f"({mc.signature})" if mc.signature else "()"
            lines.append(f"  • {name}{sig}")
        if len(macro_names) > max_per_section:
            lines.append(f"  (+{len(macro_names) - max_per_section} more — ask with focus=macros)")
        lines.append("")

    # Parse errors (if any)
    if project.parse_errors:
        lines.append(f"## Parse errors ({len(project.parse_errors)})")
        for err in project.parse_errors[:20]:
            lines.append(f"  • {err.file_path}: {err.error}")
        if len(project.parse_errors) > 20:
            lines.append(f"  (+{len(project.parse_errors) - 20} more)")
        lines.append("")

    # Footer — actionable next step hint
    lines.append(_footer(project))

    return "\n".join(lines).rstrip() + "\n"


def _header(project: ProjectMap) -> str:
    parts = [f"# dbt project: {project.project_name}"]
    if not project.project_yml_present:
        parts.append("(no dbt_project.yml — treating as project directory)")
    return " ".join(parts)


def _footer(project: ProjectMap) -> str:
    if project.actionable_count == 0:
        return "Status: project looks complete. No missing or stub models to build."
    return (
        f"Next step: {project.actionable_count} actionable model(s) need work. "
        f"Call `dbt_project_map focus=work_order` for the build sequence, or "
        f"`dbt_project_map focus=model:<name>` for a single model's full contract."
    )


# ── Group rendering (models under one directory) ────────────────────────────


def _render_group(
    directory: str,
    models: list[ModelInfo],
    max_per_section: int,
    include_columns: bool,
) -> list[str]:
    lines: list[str] = []
    status_counts = _count_statuses(models)
    header = f"## {directory or 'models'}/ ({len(models)} models"
    bits = []
    if status_counts[ModelStatus.COMPLETE]:
        bits.append(f"{status_counts[ModelStatus.COMPLETE]} complete")
    if status_counts[ModelStatus.STUB]:
        bits.append(f"{status_counts[ModelStatus.STUB]} stub")
    if status_counts[ModelStatus.MISSING]:
        bits.append(f"{status_counts[ModelStatus.MISSING]} missing")
    if status_counts[ModelStatus.ORPHAN]:
        bits.append(f"{status_counts[ModelStatus.ORPHAN]} orphan")
    if bits:
        header += " — " + ", ".join(bits)
    header += ")"
    lines.append(header)

    shown = 0
    for m in models:
        if shown >= max_per_section:
            remaining = len(models) - shown
            lines.append(f"  (+{remaining} more — ask with focus=model:<name> for detail)")
            break
        lines.append(_render_model_line(m, include_columns))
        shown += 1
    return lines


def _render_model_line(m: ModelInfo, include_columns: bool) -> str:
    icon = _ICON[m.status]
    dep_str = ""
    refs = m.all_refs
    if refs:
        shown = ", ".join(refs[:4])
        if len(refs) > 4:
            shown += f", +{len(refs) - 4}"
        dep_str = f"  ← {shown}"
    col_str = ""
    if m.columns:
        col_str = f"  [{len(m.columns)} cols]"
    elif not m.yml_path:
        # Any model without a yml entry — true orphan or orphan-sql-stub —
        # should carry this marker so the agent knows there's no contract.
        col_str = "  [no yml contract]"

    mat_str = f"  ({m.materialization})" if m.materialization else ""
    primary = f"  {icon} {m.name}{col_str}{dep_str}{mat_str}"

    if m.status in (ModelStatus.MISSING, ModelStatus.STUB) and m.description:
        # Include a short description for actionable models — the agent needs the intent.
        desc = m.description.strip().splitlines()[0][:120]
        primary += f"\n      desc: {desc}"

    if include_columns and m.columns:
        col_names = ", ".join(c.name for c in m.columns[:10])
        if len(m.columns) > 10:
            col_names += f", +{len(m.columns) - 10}"
        primary += f"\n      cols: {col_names}"

    return primary


def _count_statuses(models: list[ModelInfo]) -> dict[ModelStatus, int]:
    out = {s: 0 for s in ModelStatus}
    for m in models:
        out[m.status] = out.get(m.status, 0) + 1
    return out


# ── Focused views ────────────────────────────────────────────────────────────


def render_work_order(project: ProjectMap) -> str:
    lines = [f"# Work order for {project.project_name}", ""]
    if not project.work_order:
        lines.append("No actionable models — project looks complete.")
        return "\n".join(lines) + "\n"

    lines.append(
        f"{len(project.work_order)} actionable model(s). Build top to bottom; "
        f"each model's dependencies are already resolved by the time you reach it."
    )
    lines.append("")
    for i, name in enumerate(project.work_order, 1):
        m = project.models.get(name)
        if not m:
            continue
        icon = _ICON[m.status]
        refs_str = ", ".join(m.all_refs) if m.all_refs else "no refs"
        col_count = len(m.columns)
        mat = f" {m.materialization}" if m.materialization else ""
        lines.append(f"{i:>2}. {icon} {name} [{col_count} cols]{mat}")
        lines.append(f"     yml:  {m.yml_path or '(none)'}")
        lines.append(f"     deps: {refs_str}")
        if m.description:
            desc = m.description.strip().splitlines()[0][:200]
            lines.append(f"     desc: {desc}")
        cols = [c.name for c in m.columns]
        if cols:
            col_display = ", ".join(cols[:15])
            if len(cols) > 15:
                col_display += f", +{len(cols) - 15} more"
            lines.append(f"     cols: {col_display}")
        lines.append("")

    if project.cycles:
        lines.append("⚠ CYCLES (fix before building):")
        for cycle in project.cycles:
            lines.append(f"   {' → '.join(cycle)}")
        lines.append("")
    if project.unresolved_refs:
        lines.append("⚠ UNRESOLVED REFS:")
        for name, refs in sorted(project.unresolved_refs.items()):
            lines.append(f"   {name}: {', '.join(refs)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_filtered(project: ProjectMap, statuses: set[ModelStatus], title: str) -> str:
    models = [m for m in project.models.values() if m.status in statuses]
    models.sort(key=lambda m: (m.directory, m.name))
    lines = [f"# {title} in {project.project_name}", ""]
    if not models:
        lines.append(f"None — no models with status in {sorted(s.value for s in statuses)}.")
        return "\n".join(lines) + "\n"
    lines.append(f"{len(models)} model(s):")
    lines.append("")
    for m in models:
        icon = _ICON[m.status]
        refs_str = ", ".join(m.all_refs) if m.all_refs else "no refs"
        lines.append(f"{icon} {m.name}  ({m.directory}/)")
        lines.append(f"   yml:  {m.yml_path or '(none)'}")
        lines.append(f"   sql:  {m.sql_path or '(none)'}")
        lines.append(f"   deps: {refs_str}")
        if m.description:
            lines.append(f"   desc: {m.description.strip().splitlines()[0][:200]}")
        if m.columns:
            col_names = [c.name for c in m.columns]
            display = ", ".join(col_names[:15])
            if len(col_names) > 15:
                display += f", +{len(col_names) - 15} more"
            lines.append(f"   cols: {display}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_single_model(project: ProjectMap, name: str) -> str:
    m = project.models.get(name)
    if m is None:
        # Helpful hint: did they mean something close?
        candidates = [n for n in project.models if name.lower() in n.lower()]
        hint = ""
        if candidates[:5]:
            hint = f" Did you mean: {', '.join(candidates[:5])}?"
        return f"Model '{name}' not found in project {project.project_name}.{hint}\n"

    lines = [f"# Model: {m.name}", ""]
    lines.append(f"Status:         {_ICON[m.status]} {m.status.value}")
    lines.append(f"Directory:      {m.directory}")
    lines.append(f"YML path:       {m.yml_path or '(none)'}")
    lines.append(f"SQL path:       {m.sql_path or '(none)'}")
    if m.materialization:
        lines.append(f"Materialization: {m.materialization}")
    if m.unique_key:
        lines.append(f"Unique key:     {m.unique_key}")
    if m.sql_size:
        lines.append(f"SQL size:       {m.sql_size} bytes")
    lines.append("")

    if m.description:
        lines.append("## Description")
        lines.append(m.description.strip())
        lines.append("")

    refs = m.all_refs
    if refs:
        lines.append(f"## Dependencies ({len(refs)})")
        for ref in refs:
            dep_model = project.models.get(ref)
            if dep_model:
                dep_icon = _ICON[dep_model.status]
                lines.append(f"  {dep_icon} ref('{ref}')  [{dep_model.status.value}]")
            else:
                lines.append(f"  ⚠ ref('{ref}')  [UNRESOLVED — no model with this name]")
        lines.append("")

    src_calls = m.sources_sql or m.sources_yml
    if src_calls:
        lines.append(f"## Source calls ({len(src_calls)})")
        for schema, table in src_calls:
            lines.append(f"  source('{schema}', '{table}')")
        lines.append("")

    if m.columns:
        lines.append(f"## Columns ({len(m.columns)})")
        for c in m.columns:
            type_hint = f"  [{c.data_type}]" if c.data_type else ""
            tests_hint = f"  tests: {', '.join(c.tests)}" if c.tests else ""
            lines.append(f"  • {c.name}{type_hint}{tests_hint}")
            if c.description:
                lines.append(f"      {c.description.strip()[:200]}")
        lines.append("")

    if m.tests:
        lines.append(f"## Model-level tests ({len(m.tests)})")
        for t in m.tests:
            lines.append(f"  • {t}")
        lines.append("")

    if m.tags:
        lines.append(f"Tags: {', '.join(m.tags)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_sources(project: ProjectMap) -> str:
    lines = [f"# Sources in {project.project_name}", ""]
    if not project.sources:
        lines.append("No sources declared in yml.")
        return "\n".join(lines) + "\n"
    for name in sorted(project.sources):
        src = project.sources[name]
        schema = src.schema or "(no schema)"
        database = f" database={src.database}" if src.database else ""
        lines.append(f"## {name}  schema={schema}{database}  [{len(src.tables)} tables]")
        if src.description:
            lines.append(f"   {src.description.strip()[:200]}")
        for t in src.tables:
            desc = src.table_descriptions.get(t)
            if desc:
                lines.append(f"   • {t} — {desc[:100]}")
            else:
                lines.append(f"   • {t}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_macros(project: ProjectMap) -> str:
    lines = [f"# Macros in {project.project_name}", ""]
    if not project.macros:
        lines.append("No macros found under macros/.")
        return "\n".join(lines) + "\n"
    by_file: dict[str, list] = {}
    for name in sorted(project.macros):
        mc = project.macros[name]
        by_file.setdefault(mc.file_path, []).append(mc)
    for file_path in sorted(by_file):
        lines.append(f"## {file_path}")
        for mc in by_file[file_path]:
            sig = f"({mc.signature})" if mc.signature else "()"
            lines.append(f"  • {mc.name}{sig}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_dep_list(m: ModelInfo, project: ProjectMap) -> str:
    """Short inline dep display for the work-order summary."""
    refs = m.all_refs
    if not refs:
        return ""
    shown = ", ".join(refs[:3])
    if len(refs) > 3:
        shown += f", +{len(refs) - 3}"
    return f"  ← {shown}"
