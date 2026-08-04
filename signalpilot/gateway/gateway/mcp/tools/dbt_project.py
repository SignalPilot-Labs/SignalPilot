"""dbt project tools: dbt_error_parser, generate_sql_skeleton."""


from gateway.mcp.audit import audited_tool
from gateway.mcp.server import mcp
from gateway.dbt.error_parse import parse_dbt_error
from gateway.mcp.validation import _MODEL_NAME_RE


@audited_tool(mcp)
async def dbt_error_parser(error_output: str) -> str:
    """
    Parse raw dbt stderr/stdout and extract structured, actionable error info.

    No LLM involved — pure regex and string pattern matching against dbt-core
    AND dbt Fusion error formats. Provides a suggested fix for known error
    categories.

    Args:
        error_output: Raw dbt command output (stderr or combined stdout/stderr)

    Returns:
        Structured error summary with model name, type, location, message, and suggested fix.
    """
    if not error_output or not error_output.strip():
        return "Error: error_output cannot be empty."

    parsed = parse_dbt_error(error_output)
    lines = [
        "dbt Error Summary:",
        f"  Model: {parsed.model}",
        f"  Type: {parsed.error_type}",
        f"  Location: {parsed.location}",
        f"  Message: {parsed.message}",
        f"  Suggested fix: {parsed.suggested_fix}",
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

    return (
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
