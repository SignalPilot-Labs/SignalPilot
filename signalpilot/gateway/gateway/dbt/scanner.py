"""
Filesystem-based dbt project scanner.

This module is the heart of the discovery layer. It walks the project tree,
parses yml files with PyYAML, classifies sql files, and extracts refs/sources/
macros — all WITHOUT depending on `dbt parse`. That's the whole point: the
scanner must work on projects that dbt itself refuses to parse, because those
are the exact states the agent needs discovery information to recover from.

Design rules:
- Every file-level failure is isolated (try/except around each file).
- No global state. Each top-level function is pure given its inputs.
- Regex-based sql extraction is good enough for ref()/source()/config();
  we do not attempt full Jinja evaluation.
- Skips dbt_packages, target, logs, .claude, __pycache__ — always.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable

import yaml

from .types import (
    ColumnSpec,
    MacroInfo,
    ModelInfo,
    ModelStatus,
    ParseError,
    SourceInfo,
)

# Directories we never descend into.
_SKIP_DIRS = frozenset({"dbt_packages", "target", "logs", ".claude", "__pycache__", ".git"})

# Regex patterns for Jinja calls in sql files.
# Dbt Jinja uses {{ ref('x') }} with either single or double quotes.
_RE_REF = re.compile(r"""\{\{\s*ref\s*\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""")
# {{ source('schema', 'table') }} — two arguments.
_RE_SOURCE = re.compile(
    r"""\{\{\s*source\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}"""
)
# {{ config(materialized='table') }} — extract the materialized value.
_RE_CONFIG_MAT = re.compile(
    r"""\{\{\s*config\s*\([^)]*materialized\s*=\s*['"]([^'"]+)['"]""",
    re.DOTALL,
)
_RE_CONFIG_UK = re.compile(
    r"""\{\{\s*config\s*\([^)]*unique_key\s*=\s*['"]([^'"]+)['"]""",
    re.DOTALL,
)
# {% macro name(args) %} — extract name and arg string.
_RE_MACRO = re.compile(
    r"""\{%\s*macro\s+(\w+)\s*\(([^)]*)\)\s*%\}""",
    re.DOTALL,
)

# Matches bare current_date / current_timestamp / now() / getdate() / getutcdate() / sysdate
# in SQL files. Case-insensitive. Used to flag models that produce future-dated rows
# when the run date is past the source data's date range.
_RE_CURRENT_DATE = re.compile(
    r"\b(current_date\b|current_timestamp\b|now\s*\(\s*\)|getdate\s*\(\s*\)|getutcdate\s*\(\s*\)|sysdate\b)",
    re.IGNORECASE,
)

# Matches ROW_NUMBER() OVER ( ... ) — full content regex with DOTALL since
# OVER clauses routinely span multiple lines. Captures the OVER body in group 1.
# Uses a simple one-level paren nesting pattern sufficient for benchmark SQL.
_RE_NONDETERMINISTIC_ROWNUM = re.compile(
    r"ROW_NUMBER\s*\(\s*\)\s*OVER\s*\(\s*((?:[^()]*|\([^()]*\))*)\)",
    re.IGNORECASE | re.DOTALL,
)

# Stub-detection patterns (heuristics for incomplete sql files).
# Matches any "select * from ..." where "..." is a bareword, a quoted
# identifier, or a Jinja ref/source/macro call — all forms of trivial
# passthrough that indicate unfinished work in a benchmark context.
_RE_TRIVIAL_SELECT = re.compile(
    r"""^\s*select\s+\*\s+from\s+(\w|"|`|\{\s*\{)""",
    re.IGNORECASE,
)

# Date hazard detection: SQL functions that produce the current date at runtime.
# When used as spine endpoints in pre-shipped model files, they cause row-count
# inflation when the project is run years after the source data was collected.
_RE_DATE_HAZARD = re.compile(
    r"\b(current_date|current_timestamp|now\(\)|getdate\(\)|sysdate)\b",
    re.IGNORECASE,
)

# Non-determinism detection: window functions that may produce different results
# across runs when the ORDER BY clause does not uniquely identify rows.
# Flags ROW_NUMBER, RANK, and DENSE_RANK — all share the same non-determinism
# problem when the ORDER BY is not unique within the partition.
_RE_NONDETERMINISTIC_WINDOW = re.compile(
    r"(ROW_NUMBER|RANK|DENSE_RANK)\s*\(\s*\)\s*OVER\s*\(",
    re.IGNORECASE,
)


def _iter_files(root: Path, suffixes: tuple[str, ...]) -> Iterable[Path]:
    """Yield files under root whose suffix is in `suffixes`, skipping _SKIP_DIRS."""
    if not root.exists():
        return
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIRS:
                    continue
                stack.append(entry)
            elif entry.suffix.lower() in suffixes:
                yield entry


def _rel(path: Path, root: Path) -> str:
    """Return a POSIX-style relative path string."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


# ── dbt_project.yml + packages.yml + profiles.yml ─────────────────────────────


def parse_dbt_project(project_dir: Path) -> tuple[str, bool, list[str], bool, bool]:
    """Parse dbt_project.yml. Return (project_name, project_yml_present,
    packages_list, profiles_present, packages_yml_present).

    Never raises. Missing or broken files produce sane defaults.
    """
    project_yml = project_dir / "dbt_project.yml"
    profiles_yml = project_dir / "profiles.yml"
    packages_yml = project_dir / "packages.yml"

    project_name = project_dir.name
    project_present = project_yml.exists()
    profiles_present = profiles_yml.exists()
    packages_present = packages_yml.exists()

    if project_present:
        try:
            data = yaml.safe_load(project_yml.read_text(encoding="utf-8", errors="replace")) or {}
            if isinstance(data, dict):
                project_name = data.get("name") or project_name
        except Exception:
            pass

    packages: list[str] = []
    if packages_present:
        try:
            data = yaml.safe_load(packages_yml.read_text(encoding="utf-8", errors="replace")) or {}
            if isinstance(data, dict):
                for pkg in data.get("packages", []) or []:
                    if isinstance(pkg, dict):
                        if "package" in pkg:
                            packages.append(str(pkg["package"]))
                        elif "git" in pkg:
                            packages.append(str(pkg["git"]))
                        elif "local" in pkg:
                            packages.append(f"local:{pkg['local']}")
        except Exception:
            pass

    return project_name, project_present, packages, profiles_present, packages_present


# ── YML parsing ───────────────────────────────────────────────────────────────


def parse_yml_file(path: Path) -> tuple[dict | None, str | None]:
    """Load a single yml file. Return (data, error_message). Never raises."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return None, f"read failed: {e}"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        # Use the short form — full yaml error with context can be huge.
        msg = str(e).splitlines()[0] if str(e) else "yaml parse error"
        return None, msg
    if data is None:
        return {}, None  # empty yml is fine
    if not isinstance(data, dict):
        return None, f"top level is {type(data).__name__}, expected mapping"
    return data, None


def extract_models_from_yml(
    data: dict, yml_rel_path: str, project_dir: Path
) -> list[ModelInfo]:
    """Pull model definitions out of a parsed yml dict. Tolerates missing fields."""
    models: list[ModelInfo] = []
    raw_models = data.get("models")
    if not isinstance(raw_models, list):
        return models

    yml_dir = str(Path(yml_rel_path).parent).replace("\\", "/")
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue

        m = ModelInfo(
            name=name,
            yml_path=yml_rel_path,
            status=ModelStatus.MISSING,
            directory=yml_dir,
        )
        if isinstance(entry.get("description"), str):
            m.description = entry["description"].strip() or None

        # columns block
        cols_raw = entry.get("columns")
        if isinstance(cols_raw, list):
            for col in cols_raw:
                if not isinstance(col, dict):
                    continue
                col_name = col.get("name")
                if not isinstance(col_name, str) or not col_name:
                    continue
                spec = ColumnSpec(
                    name=col_name,
                    data_type=_coerce_str(col.get("data_type") or col.get("type")),
                    description=_coerce_str(col.get("description")),
                )
                tests_raw = col.get("tests") or col.get("data_tests") or []
                if isinstance(tests_raw, list):
                    for t in tests_raw:
                        if isinstance(t, str):
                            spec.tests.append(t)
                            if t == "unique" and m.unique_key is None:
                                m.unique_key = col_name
                        elif isinstance(t, dict) and t:
                            test_name = next(iter(t.keys()))
                            spec.tests.append(str(test_name))
                            if test_name == "unique" and m.unique_key is None:
                                m.unique_key = col_name
                m.columns.append(spec)

        # model-level tests
        tests_raw = entry.get("tests") or entry.get("data_tests") or []
        if isinstance(tests_raw, list):
            for t in tests_raw:
                if isinstance(t, str):
                    m.tests.append(t)
                elif isinstance(t, dict) and t:
                    m.tests.append(str(next(iter(t.keys()))))

        # config block
        config_raw = entry.get("config")
        if isinstance(config_raw, dict):
            m.config = dict(config_raw)
            mat = config_raw.get("materialized")
            if isinstance(mat, str):
                m.materialization = mat
            uk = config_raw.get("unique_key")
            if isinstance(uk, str) and m.unique_key is None:
                m.unique_key = uk

        # explicit refs
        refs_raw = entry.get("refs")
        if isinstance(refs_raw, list):
            for r in refs_raw:
                if isinstance(r, str):
                    m.refs_yml.append(r)
                elif isinstance(r, dict):
                    rn = r.get("name")
                    if isinstance(rn, str):
                        m.refs_yml.append(rn)

        # tags
        tags_raw = entry.get("tags")
        if isinstance(tags_raw, list):
            m.tags = [str(t) for t in tags_raw if isinstance(t, (str, int))]
        elif isinstance(tags_raw, str):
            m.tags = [tags_raw]

        models.append(m)
    return models


def extract_sources_from_yml(data: dict, yml_rel_path: str) -> list[SourceInfo]:
    """Pull source definitions out of a parsed yml dict."""
    sources: list[SourceInfo] = []
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list):
        return sources

    for entry in raw_sources:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue

        s = SourceInfo(
            name=name,
            yml_path=yml_rel_path,
            schema=_coerce_str(entry.get("schema")),
            database=_coerce_str(entry.get("database")),
            description=_coerce_str(entry.get("description")),
        )
        tables_raw = entry.get("tables")
        if isinstance(tables_raw, list):
            for t in tables_raw:
                if isinstance(t, dict):
                    tn = t.get("name")
                    if isinstance(tn, str):
                        s.tables.append(tn)
                        desc = t.get("description")
                        if isinstance(desc, str) and desc.strip():
                            s.table_descriptions[tn] = desc.strip()
        sources.append(s)
    return sources


# ── SQL file classification and ref/source extraction ────────────────────────


def classify_sql_file(path: Path) -> tuple[ModelStatus, int, str]:
    """Decide if a sql file is a stub or complete. Returns (status, size, content).

    The content is returned so callers can reuse it for ref extraction without
    a second read.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ModelStatus.STUB, 0, ""

    size = len(content.encode("utf-8"))
    stripped = content.strip()
    if len(stripped) < 5:
        return ModelStatus.STUB, size, content

    # Strip comments / config blocks for the stub check so a file that is
    # ONLY config doesn't count as complete.
    body = re.sub(r"\{\{\s*config\([^}]*\}\}", "", stripped, flags=re.DOTALL)
    body = re.sub(r"--[^\n]*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL).strip()

    if len(body) < 5:
        return ModelStatus.STUB, size, content
    if _RE_TRIVIAL_SELECT.match(body):
        # Trivial pass-through select * — treat as stub unless there are more statements.
        if body.lower().count("select") == 1 and "join" not in body.lower():
            return ModelStatus.STUB, size, content
    if body.endswith(","):
        return ModelStatus.STUB, size, content
    if body.endswith("("):
        return ModelStatus.STUB, size, content
    if body.count("(") > body.count(")"):
        return ModelStatus.STUB, size, content
    if body.count("{") > body.count("}"):
        return ModelStatus.STUB, size, content

    # Heuristic: anything that contains a REPLACE_THIS or TODO placeholder is a stub.
    if re.search(r"REPLACE_THIS_ENTIRE_FILE|<\s*TODO\s*:", body):
        return ModelStatus.STUB, size, content

    return ModelStatus.COMPLETE, size, content


def extract_refs_from_sql(content: str) -> list[str]:
    """Find every {{ ref('x') }} in the sql content, deduped, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _RE_REF.finditer(content):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def extract_sources_from_sql(content: str) -> list[tuple[str, str]]:
    """Find every {{ source('schema', 'table') }} call, deduped."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for m in _RE_SOURCE.finditer(content):
        pair = (m.group(1), m.group(2))
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def extract_config_from_sql(content: str) -> tuple[str | None, str | None]:
    """Extract (materialization, unique_key) from {{ config(...) }} calls."""
    mat_match = _RE_CONFIG_MAT.search(content)
    uk_match = _RE_CONFIG_UK.search(content)
    return (
        mat_match.group(1) if mat_match else None,
        uk_match.group(1) if uk_match else None,
    )


# ── Macros ────────────────────────────────────────────────────────────────────


def extract_macros_from_file(path: Path, project_dir: Path) -> list[MacroInfo]:
    """Find {% macro name(args) %} definitions in a file under macros/."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel = _rel(path, project_dir)
    out: list[MacroInfo] = []
    for m in _RE_MACRO.finditer(content):
        name = m.group(1)
        args = m.group(2).strip()
        if not name or name.startswith("_"):
            continue
        out.append(MacroInfo(name=name, file_path=rel, signature=args or None))
    return out


# ── dbt_packages/ hazard detection ───────────────────────────────────────────

# Skip set for use inside dbt_packages/ traversal.
# Keeps dbt_packages in the set (prevents recursing into nested package installs)
# and reuses the rest of _SKIP_DIRS as-is.
_PKG_SKIP_DIRS = _SKIP_DIRS  # same set — dbt_packages in it blocks nested installs


def scan_dbt_packages(project_dir: Path) -> tuple[list[dict], list[dict]]:
    """Walk dbt_packages/ and return (date_hazards, nondeterminism_warnings).

    All .sql files inside dbt_packages/ are treated as COMPLETE without calling
    classify_sql_file — they are authored third-party code, not benchmark stubs.
    Results include ``package: True`` and ``override_path`` so the formatter can
    instruct the agent to create a local override in models/.

    Returns empty lists if dbt_packages/ does not exist (e.g. before dbt deps).
    """
    pkg_dir = project_dir / "dbt_packages"
    if not pkg_dir.exists():
        return [], []

    date_hazards: list[dict] = []
    nd_warnings: list[dict] = []

    # Walk pkg_dir using an explicit stack to respect _PKG_SKIP_DIRS.
    # We start from pkg_dir itself, not the project root, so the dbt_packages
    # entry in _PKG_SKIP_DIRS only blocks *nested* installs inside packages.
    stack: list[Path] = []
    try:
        for entry in pkg_dir.iterdir():
            if entry.is_dir() and entry.name not in _PKG_SKIP_DIRS:
                stack.append(entry)
            elif entry.is_file() and entry.suffix.lower() == ".sql":
                stack.append(entry)
    except OSError:
        return [], []

    while stack:
        current = stack.pop()
        try:
            if current.is_dir():
                for entry in current.iterdir():
                    if entry.is_dir():
                        if entry.name not in _PKG_SKIP_DIRS:
                            stack.append(entry)
                    elif entry.suffix.lower() == ".sql":
                        stack.append(entry)
            elif current.suffix.lower() == ".sql":
                # Only scan model files, not macros or integration tests.
                # Creating a model override for a macro has no effect and
                # produces broken SQL when the fixer replaces inside Jinja calls.
                parts = current.relative_to(pkg_dir).parts
                if not any(p in ("macros", "integration_tests") for p in parts):
                    _scan_pkg_sql_file(current, project_dir, date_hazards, nd_warnings)
        except OSError:
            continue

    return date_hazards, nd_warnings


def _scan_pkg_sql_file(
    sql_path: Path,
    project_dir: Path,
    date_hazards: list[dict],
    nd_warnings: list[dict],
) -> None:
    """Scan a single package .sql file for date hazards and non-determinism."""
    try:
        content = sql_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    rel = _rel(sql_path, project_dir)
    stem = sql_path.stem
    override_path = f"models/{stem}.sql"

    matched_patterns = list(dict.fromkeys(
        m.group(0).lower() for m in _RE_DATE_HAZARD.finditer(content)
    ))
    if matched_patterns:
        date_hazards.append({
            "file": rel,
            "pattern": ", ".join(matched_patterns),
            "model_name": stem,
            "package": True,
            "override_path": override_path,
        })

    if _RE_NONDETERMINISTIC_WINDOW.search(content):
        nd_warnings.append({
            "file": rel,
            "model_name": stem,
            "pattern": "ROW_NUMBER/RANK/DENSE_RANK without verified unique ORDER BY",
            "package": True,
            "override_path": override_path,
        })


# ── Top-level orchestration ──────────────────────────────────────────────────


def scan_filesystem(project_dir: Path) -> dict:
    """Walk the project and return a raw scan dict.

    Returns a flat structure; inventory.py assembles it into a ProjectMap.
    This split lets inventory do cross-file reconciliation (yml ↔ sql) without
    the scanner having to know about the final data model.
    """
    t0 = time.perf_counter()

    project_name, pyml, packages, prof, pkg_yml = parse_dbt_project(project_dir)

    models_dir = project_dir / "models"
    macros_dir = project_dir / "macros"

    yml_models: list[ModelInfo] = []
    yml_sources: list[SourceInfo] = []
    parse_errors: list[ParseError] = []

    # Walk models/ for yml files.
    for yml_path in _iter_files(models_dir, (".yml", ".yaml")):
        rel = _rel(yml_path, project_dir)
        data, err = parse_yml_file(yml_path)
        if err:
            parse_errors.append(ParseError(file_path=rel, error=err))
            continue
        if data is None:
            continue
        yml_models.extend(extract_models_from_yml(data, rel, project_dir))
        yml_sources.extend(extract_sources_from_yml(data, rel))

    # Also look for sources.yml at the project root or models root.
    for candidate in (project_dir / "sources.yml", models_dir / "sources.yml"):
        if candidate.exists():
            rel = _rel(candidate, project_dir)
            data, err = parse_yml_file(candidate)
            if err:
                parse_errors.append(ParseError(file_path=rel, error=err))
                continue
            if data is not None:
                yml_sources.extend(extract_sources_from_yml(data, rel))

    # Walk models/ for sql files.
    sql_records: list[dict] = []
    date_hazards: list[dict] = []
    nondeterminism_warnings: list[dict] = []
    for sql_path in _iter_files(models_dir, (".sql",)):
        rel = _rel(sql_path, project_dir)
        status, size, content = classify_sql_file(sql_path)
        refs = extract_refs_from_sql(content)
        sources_in_sql = extract_sources_from_sql(content)
        sql_mat, sql_uk = extract_config_from_sql(content)
        directory = str(Path(rel).parent).replace("\\", "/")
        sql_records.append({
            "name": sql_path.stem,
            "path": rel,
            "directory": directory,
            "status": status,
            "size": size,
            "refs": refs,
            "sources": sources_in_sql,
            "materialization": sql_mat,
            "unique_key": sql_uk,
        })
        # Only flag COMPLETE models — stubs are going to be rewritten anyway,
        # and flagging incomplete SQL wastes agent attention.
        if status == ModelStatus.COMPLETE:
            matched_patterns = list(dict.fromkeys(
                m.group(0).lower() for m in _RE_DATE_HAZARD.finditer(content)
            ))
            if matched_patterns:
                date_hazards.append({
                    "file": rel,
                    "pattern": ", ".join(matched_patterns),
                    "model_name": sql_path.stem,
                })
            if _RE_NONDETERMINISTIC_WINDOW.search(content):
                nondeterminism_warnings.append({
                    "file": rel,
                    "model_name": sql_path.stem,
                    "pattern": "ROW_NUMBER/RANK/DENSE_RANK without verified unique ORDER BY",
                })

    # Walk dbt_packages/ for date hazards and non-determinism (read-only detection).
    # Package models are not added to sql_records — they are third-party code.
    pkg_date_hazards, pkg_nd_warnings = scan_dbt_packages(project_dir)
    date_hazards.extend(pkg_date_hazards)
    nondeterminism_warnings.extend(pkg_nd_warnings)

    # Walk macros/.
    macros: list[MacroInfo] = []
    for mp in _iter_files(macros_dir, (".sql",)):
        macros.extend(extract_macros_from_file(mp, project_dir))

    scan_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "project_name": project_name,
        "project_yml_present": pyml,
        "profiles_yml_present": prof,
        "packages_yml_present": pkg_yml,
        "packages": packages,
        "yml_models": yml_models,
        "yml_sources": yml_sources,
        "sql_records": sql_records,
        "macros": macros,
        "parse_errors": parse_errors,
        "current_date_warnings": date_hazards,
        "nondeterministic_warnings": nondeterminism_warnings,
        "scan_ms": scan_ms,
        "date_hazards": date_hazards,
        "nondeterminism_warnings": nondeterminism_warnings,
    }


def _coerce_str(value) -> str | None:
    """Coerce a value to a stripped string, or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    return value or None


def _strip_sql_line_comment(line: str) -> str:
    """Remove a `--` line-comment suffix from a single line.

    Strips everything from the first `--` to end of line. This is a heuristic
    and does not handle `--` inside string literals, which is an accepted
    tradeoff for a regex-based scanner.
    """
    idx = line.find("--")
    if idx == -1:
        return line
    return line[:idx]


def _blank_sql_comments(content: str) -> str:
    """Replace SQL comments with same-length whitespace to preserve character offsets.

    Line comments (`--` to end of line) are replaced with spaces up to the
    newline; block comments (`/* ... */`) are replaced with spaces, keeping
    newlines in place so line numbers derived from offset counting stay correct.
    """
    result = list(content)
    i = 0
    length = len(content)
    while i < length:
        # Check for block comment start
        if content[i] == "/" and i + 1 < length and content[i + 1] == "*":
            j = i + 2
            while j < length - 1:
                if content[j] == "*" and content[j + 1] == "/":
                    j += 2
                    break
                j += 1
            else:
                j = length
            # Replace from i to j with spaces, preserving newlines
            for k in range(i, j):
                if result[k] != "\n":
                    result[k] = " "
            i = j
        # Check for line comment start
        elif content[i] == "-" and i + 1 < length and content[i + 1] == "-":
            j = i
            while j < length and content[j] != "\n":
                result[j] = " "
                j += 1
            i = j
        else:
            i += 1
    return "".join(result)


def _count_order_by_columns(order_by_text: str) -> int:
    """Count comma-separated items in an ORDER BY clause, ignoring commas inside parens.

    Returns the number of segments. Used to determine if ORDER BY has only one
    column (flag as potentially non-deterministic) or multiple columns (skip).
    """
    depth = 0
    segments = 0
    has_content = False
    for ch in order_by_text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            if has_content:
                segments += 1
            has_content = False
        else:
            if not ch.isspace():
                has_content = True
    if has_content:
        segments += 1
    return segments


def _normalize_clause(text: str) -> str:
    """Lowercase and strip all whitespace from a clause text for comparison."""
    return "".join(text.lower().split())


def detect_nondeterministic_row_number(content: str, rel_path: str) -> list[dict]:
    """Scan SQL content for ROW_NUMBER() OVER (...) calls that are non-deterministic.

    Operates on full file content with re.DOTALL because OVER clauses span
    multiple lines. Pre-processes content to blank out comments before matching.

    Flags as non-deterministic when:
    - ORDER BY is missing from the OVER body
    - ORDER BY has only one comma-separated item (one column)
    - PARTITION BY text exactly equals ORDER BY text (after normalization)

    Returns list of dicts with keys: file, line, match, partition_by, order_by.
    Line numbers are 1-indexed, computed from original content offsets.
    """
    cleaned = _blank_sql_comments(content)
    warnings: list[dict] = []

    for m in _RE_NONDETERMINISTIC_ROWNUM.finditer(cleaned):
        over_body = m.group(1)
        over_body_upper = over_body.upper()

        # Extract ORDER BY text
        order_by_text: str | None = None
        ob_idx = over_body_upper.find("ORDER BY")
        if ob_idx != -1:
            order_by_text = over_body[ob_idx + len("ORDER BY"):].strip()

        # Extract PARTITION BY text (everything between PARTITION BY and ORDER BY or end)
        partition_by_text: str | None = None
        pb_idx = over_body_upper.find("PARTITION BY")
        if pb_idx != -1:
            pb_end = ob_idx if ob_idx != -1 and ob_idx > pb_idx else len(over_body)
            partition_by_text = over_body[pb_idx + len("PARTITION BY"):pb_end].strip()

        # Determine if this is non-deterministic
        is_nondeterministic = False

        if order_by_text is None:
            # No ORDER BY at all
            is_nondeterministic = True
        else:
            col_count = _count_order_by_columns(order_by_text)
            if col_count <= 1:
                is_nondeterministic = True
            elif (
                partition_by_text is not None
                and _normalize_clause(partition_by_text) == _normalize_clause(order_by_text)
            ):
                is_nondeterministic = True

        if not is_nondeterministic:
            continue

        # Compute line number from original content (not cleaned — same offsets)
        line_num = content[: m.start()].count("\n") + 1

        # Build a trimmed display of the full match
        full_match = m.group(0).strip()
        # Normalize whitespace runs in the match for compact display
        display_match = " ".join(full_match.split())

        warnings.append({
            "file": rel_path,
            "line": line_num,
            "match": display_match,
            "partition_by": partition_by_text,
            "order_by": order_by_text,
        })

    return warnings


def detect_current_date_usage(content: str, rel_path: str) -> list[dict]:
    """Scan SQL content line-by-line for bare current_date / now() / etc. calls.

    Processes each line individually so match positions map directly to correct
    line numbers without any offset translation. Tracks `/* */` block comment
    state across lines to skip commented-out code.

    Returns a list of dicts, each with keys: file (str), line (int), match (str).
    Line numbers are 1-indexed. At most one warning per occurrence is emitted.
    """
    warnings: list[dict] = []
    in_block_comment = False

    for line_num, line in enumerate(content.splitlines(), start=1):
        # Handle block comment state transitions for this line.
        # We process the line in segments separated by `/*` and `*/` markers.
        processed_line = ""
        remaining = line

        while remaining:
            if in_block_comment:
                end = remaining.find("*/")
                if end == -1:
                    # Entire remaining line is inside a block comment — discard.
                    remaining = ""
                else:
                    in_block_comment = False
                    remaining = remaining[end + 2:]
            else:
                start = remaining.find("/*")
                if start == -1:
                    # No block comment start — rest of line is live SQL.
                    processed_line += remaining
                    remaining = ""
                else:
                    # Everything before `/*` is live SQL.
                    processed_line += remaining[:start]
                    in_block_comment = True
                    remaining = remaining[start + 2:]

        # Strip `--` line-comment suffix from the live SQL portion.
        processed_line = _strip_sql_line_comment(processed_line)

        for m in _RE_CURRENT_DATE.finditer(processed_line):
            warnings.append({
                "file": rel_path,
                "line": line_num,
                "match": m.group(0),
            })

    return warnings
