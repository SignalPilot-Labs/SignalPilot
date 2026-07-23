"""PR scan: find changed dbt models, verify them against the warehouse,
render a markdown report.

Report-first MVP of the PipelineProof battery: existence, row count, grain
duplicates on the inferred key, and null-saturated columns. Each model gets a
verdict (pass / warn / fail); the PR status is the worst verdict.
"""

from __future__ import annotations

import logging
import posixpath
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_MODEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NULL_SATURATION = 0.95
_KEY_CANDIDATES = ("id", "{model}_id", "{model}_key", "pk", "surrogate_key")
_QUERY_TIMEOUT_S = 60
_MAX_MODELS_PER_SCAN = 30


def parse_changed_models(files: list[dict]) -> list[str]:
    """Model names from PR file entries: *.sql under a models/ directory,
    excluding removed files. Deduplicated, order-preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        path = f.get("filename", "")
        if f.get("status") == "removed" or not path.endswith(".sql"):
            continue
        parts = path.split("/")
        if "models" not in parts[:-1]:
            continue
        name = posixpath.basename(path)[: -len(".sql")]
        if _MODEL_RE.match(name) and name not in seen:
            seen.add(name)
            out.append(name)
    return out


@dataclass
class ModelCheck:
    model: str
    verdict: str = "pass"  # pass | warn | fail
    exists: bool = False
    row_count: int | None = None
    grain_key: str | None = None
    grain_duplicates: int | None = None
    null_saturated: list[str] = field(default_factory=list)
    error: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ScanReport:
    repo: str
    pr_number: int
    connection: str
    checks: list[ModelCheck]
    skipped: list[str]  # changed sql files that aren't verifiable models
    started_at: float
    duration_s: float

    @property
    def verdict(self) -> str:
        if any(c.verdict == "fail" for c in self.checks):
            return "fail"
        if any(c.verdict == "warn" for c in self.checks):
            return "warn"
        return "pass"


def _qid(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _get_columns(connector, db_type: str, table_name: str) -> tuple[str | None, list[str]]:
    """Dialect-aware column introspection → (resolved qualified name, columns).

    Unqualified names are resolved by searching information_schema across all
    non-system schemas — dbt materializes into per-project schemas, so a bare
    model name almost never lives in 'public'. On multiple matches the first
    schema alphabetically wins (deterministic).

    Standalone (not the MCP helper) — importing gateway.mcp registers the tool
    server, which the bot must not do.
    """
    if db_type in ("sqlite", "duckdb"):
        rows = await connector.execute(f"PRAGMA table_info('{table_name}')")
        cols = [r.get("name", "") for r in rows if r.get("name")]
        return (table_name if cols else None), cols
    parts = table_name.split(".")
    if len(parts) == 2:
        schema, tbl = parts
        rows = await connector.execute(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{tbl}' "
            "ORDER BY ordinal_position"
        )
        cols = [r.get("column_name", "") for r in rows if r.get("column_name")]
        return (table_name if cols else None), cols
    rows = await connector.execute(
        "SELECT table_schema, column_name FROM information_schema.columns "
        f"WHERE table_name = '{parts[0]}' "
        "AND table_schema NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY table_schema, ordinal_position"
    )
    by_schema: dict[str, list[str]] = {}
    for r in rows:
        if r.get("column_name"):
            by_schema.setdefault(r.get("table_schema", ""), []).append(r["column_name"])
    if not by_schema:
        return None, []
    schema = sorted(by_schema)[0]
    return f"{schema}.{parts[0]}", by_schema[schema]


def _qname(qualified: str) -> str:
    """Quote a possibly schema-qualified name part-by-part."""
    return ".".join(_qid(p) for p in qualified.split("."))


def _pick_grain_key(model: str, columns: list[str]) -> tuple[str | None, bool]:
    """(key column, from_fallback). Fallback = first column ending in _id —
    on fact tables that can be a foreign key, so its dup findings only warn."""
    lower_cols = {c.lower(): c for c in columns}
    for cand in _KEY_CANDIDATES:
        cname = cand.format(model=model.lower())
        if cname in lower_cols:
            return lower_cols[cname], False
    if columns and columns[0].lower().endswith("_id"):
        return columns[0], True
    return None, False


async def _check_model(connector, db_type: str, model: str) -> ModelCheck:
    check = ModelCheck(model=model)
    try:
        resolved, columns = await _get_columns(connector, db_type, model)
    except Exception as exc:
        check.verdict = "fail"
        check.error = f"column introspection failed: {exc}"
        return check
    if not resolved or not columns:
        check.verdict = "fail"
        check.error = "table not found — has the model been materialized?"
        return check
    check.exists = True
    if resolved != model:
        check.notes.append(f"resolved to {resolved}")

    grain_key, key_is_fallback = _pick_grain_key(model, columns)

    # Single full-table pass: row count + grain distinct + null saturation in
    # one aggregate query (matters on RPU/bytes-billed warehouses).
    probe_cols = columns[:40]
    exprs = ["COUNT(*) AS row_n"]
    if grain_key:
        exprs.append(f"COUNT(DISTINCT {_qid(grain_key)}) AS key_distinct")
    exprs += [
        f"SUM(CASE WHEN {_qid(c)} IS NULL THEN 1 ELSE 0 END) AS {_qid('null_' + str(i))}"
        for i, c in enumerate(probe_cols)
    ]
    try:
        rows = await connector.execute(
            f"SELECT {', '.join(exprs)} FROM {_qname(resolved)}", timeout=_QUERY_TIMEOUT_S
        )
    except TypeError:
        # Some connectors don't accept a timeout kwarg
        try:
            rows = await connector.execute(f"SELECT {', '.join(exprs)} FROM {_qname(resolved)}")
        except Exception as exc:
            check.verdict = "warn"
            check.notes.append(f"aggregate scan failed: {exc}")
            return check
    except Exception as exc:
        check.verdict = "warn"
        check.notes.append(f"aggregate scan failed: {exc}")
        return check

    if not rows:
        check.verdict = "warn"
        check.notes.append("aggregate scan returned no rows")
        return check
    agg = rows[0]
    values = list(agg.values())
    check.row_count = int(values[0]) if values and values[0] is not None else None

    if check.row_count == 0:
        check.verdict = "warn"
        check.notes.append("model materialized 0 rows")
        return check

    offset = 1
    if grain_key:
        key_distinct = values[1]
        offset = 2
        if key_distinct is not None and check.row_count is not None:
            check.grain_key = grain_key
            check.grain_duplicates = check.row_count - int(key_distinct)
            if check.grain_duplicates > 0:
                if key_is_fallback:
                    # FK-looking fallback key: duplicates may be legitimate
                    # composite grain — surface loudly but don't fail.
                    factor = check.row_count / max(1, int(key_distinct))
                    check.verdict = "warn"
                    check.notes.append(
                        f"'{grain_key}' is {factor:.1f}x rows (inferred key — composite grain or fan-out?)"
                    )
                else:
                    check.verdict = "fail"
                    check.notes.append(
                        f"{check.grain_duplicates} duplicate value(s) on key '{grain_key}' — possible join fan-out"
                    )

    null_counts = values[offset : offset + len(probe_cols)]
    for c, n in zip(probe_cols, null_counts):
        if n is not None and check.row_count and int(n) / check.row_count >= _NULL_SATURATION:
            check.null_saturated.append(c)
    if check.null_saturated:
        if check.verdict == "pass":
            check.verdict = "warn"
        check.notes.append(
            f"column(s) ≥{int(_NULL_SATURATION * 100)}% NULL: {', '.join(check.null_saturated)}"
        )

    return check


async def scan_pr_models(
    store,
    *,
    repo: str,
    pr_number: int,
    connection_name: str,
    files: list[dict],
) -> ScanReport:
    """Verify every changed model against the connection. Store must be org-scoped."""
    started = time.time()
    models = parse_changed_models(files)
    sql_files = [f.get("filename", "") for f in files if f.get("filename", "").endswith(".sql")]
    skipped = [p for p in sql_files if posixpath.basename(p)[: -len(".sql")] not in models]

    if len(models) > _MAX_MODELS_PER_SCAN:
        skipped += [f"{m}.sql (over {_MAX_MODELS_PER_SCAN}-model scan cap)" for m in models[_MAX_MODELS_PER_SCAN:]]
        models = models[:_MAX_MODELS_PER_SCAN]

    checks: list[ModelCheck] = []
    if not connection_name:
        # Server misconfiguration must not read as per-model data failures.
        return ScanReport(
            repo=repo,
            pr_number=pr_number,
            connection="(not configured)",
            checks=[
                ModelCheck(
                    model=m,
                    verdict="fail",
                    error="bot not configured: set SP_GITHUB_BOT_CONNECTION or pass connection_name",
                )
                for m in models
            ],
            skipped=skipped,
            started_at=started,
            duration_s=round(time.time() - started, 2),
        )
    if models:
        conn_info = await store.get_connection(connection_name)
        if conn_info is None:
            for m in models:
                checks.append(
                    ModelCheck(model=m, verdict="fail", error=f"connection '{connection_name}' not found")
                )
        else:
            conn_str = await store.get_connection_string(connection_name)
            extras = await store.get_credential_extras(connection_name)
            from gateway.connectors.pool_manager import pool_manager

            try:
                async with pool_manager.connection(
                    conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                ) as connector:
                    for m in models:
                        checks.append(await _check_model(connector, conn_info.db_type, m))
            except Exception as exc:
                logger.warning("PR scan connection failed (%s): %r", connection_name, exc)
                for m in models[len(checks):]:
                    checks.append(ModelCheck(model=m, verdict="fail", error=f"connection error: {exc}"))

    return ScanReport(
        repo=repo,
        pr_number=pr_number,
        connection=connection_name,
        checks=checks,
        skipped=skipped,
        started_at=started,
        duration_s=round(time.time() - started, 2),
    )


_VERDICT_EMOJI = {"pass": "✅", "warn": "⚠️", "fail": "❌"}


def render_report_markdown(report: ScanReport) -> str:
    """PR comment body. Starts with the marker so re-scans update in place."""
    from gateway.github_bot.client import COMMENT_MARKER

    lines = [
        COMMENT_MARKER,
        f"## {_VERDICT_EMOJI[report.verdict]} PipelineProof — model verification",
        "",
        f"Verified **{len(report.checks)}** changed model(s) against connection "
        f"`{report.connection}` in {report.duration_s}s.",
        "",
    ]
    if report.checks:
        lines += [
            "| Model | Verdict | Rows | Grain | Findings |",
            "|---|---|---:|---|---|",
        ]
        for c in report.checks:
            grain = (
                f"`{c.grain_key}`" + (f" ({c.grain_duplicates} dup)" if c.grain_duplicates else " ✓")
                if c.grain_key
                else "—"
            )
            findings = c.error or "; ".join(c.notes) or "all checks passed"
            rows = f"{c.row_count:,}" if c.row_count is not None else "—"
            lines.append(
                f"| `{c.model}` | {_VERDICT_EMOJI[c.verdict]} {c.verdict} | {rows} | {grain} | {findings} |"
            )
    else:
        lines.append("_No dbt models changed in this PR (no `models/**/*.sql` files)._")
    if report.skipped:
        lines += ["", f"<sub>Skipped non-model SQL: {', '.join(f'`{s}`' for s in report.skipped[:10])}</sub>"]
    lines += [
        "",
        "<sub>Checks: table exists · row count · grain duplicates on inferred key · "
        "null-saturated columns. Report-first: this bot never blocks a merge by itself.</sub>",
    ]
    return "\n".join(lines)
