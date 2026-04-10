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

# Stub-detection patterns (heuristics for incomplete sql files).
# Matches any "select * from ..." where "..." is a bareword, a quoted
# identifier, or a Jinja ref/source/macro call — all forms of trivial
# passthrough that indicate unfinished work in a benchmark context.
_RE_TRIVIAL_SELECT = re.compile(
    r"""^\s*select\s+\*\s+from\s+(\w|"|`|\{\s*\{)""",
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
        "scan_ms": scan_ms,
    }


def _coerce_str(value) -> str | None:
    """Coerce a value to a stripped string, or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    return value or None
