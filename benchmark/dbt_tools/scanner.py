"""Static analysis of a dbt project's models/ directory and YML specs."""

from __future__ import annotations

import re
from pathlib import Path

SKIP_DIRS = (".claude", "dbt_packages", "target", "macros")


def _extract_model_names(yml_content: str) -> set[str]:
    """Extract top-level model names from a dbt YAML file.

    Only picks up names directly under 'models:' (indented 2 spaces),
    not column names (indented 6+ spaces) or source table names.
    """
    names: set[str] = set()
    in_models_block = False
    for line in yml_content.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("models:") and indent <= 2:
            in_models_block = True
            continue
        if in_models_block and indent <= 0 and stripped and not stripped.startswith("#"):
            if not stripped.startswith("-"):
                in_models_block = False
                continue
        if in_models_block and 1 <= indent <= 4:
            m = re.match(r'-\s*name:\s*(\S+)', stripped)
            if m:
                names.add(m.group(1))
    return names


def scan_yml_models(work_dir: Path) -> set[str]:
    """Return all model names declared in any .yml/.yaml file in the project."""
    yml_models: set[str] = set()
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                yml_models.update(_extract_model_names(yml_file.read_text()))
            except Exception:
                pass
    return yml_models


def classify_sql_models(work_dir: Path) -> tuple[set[str], set[str]]:
    """Return (complete_models, stub_models).

    A file is a stub/incomplete if it is 0 bytes, its entire content is a
    single ``select * from ...`` line, or it ends with a trailing comma
    (truncated CTE).
    """
    complete: set[str] = set()
    stubs: set[str] = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        content = sql_file.read_text().strip()
        is_stub = (
            len(content) < 5
            or re.match(r'^select\s+\*\s+from\s+', content, re.IGNORECASE)
            or content.endswith(",")
            or content.endswith("(")
            or (content.count("(") > content.count(")"))
        )
        if is_stub:
            stubs.add(sql_file.stem)
        else:
            complete.add(sql_file.stem)
    return complete, stubs


def extract_model_deps(work_dir: Path) -> dict[str, list[str]]:
    """Extract model dependency info (refs) from YML files."""
    import yaml

    deps: dict[str, list[str]] = {}
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "models" in data:
                    for model in data["models"]:
                        name = model.get("name")
                        refs = model.get("refs", [])
                        if name and refs:
                            deps[name] = [r["name"] if isinstance(r, dict) else str(r) for r in refs]
            except Exception:
                pass
    return deps


def extract_model_columns(work_dir: Path) -> dict[str, list[str]]:
    """Extract column names from YML model definitions."""
    import yaml

    result: dict[str, list[str]] = {}
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "models" in data:
                    for model in data["models"]:
                        name = model.get("name")
                        columns = model.get("columns", [])
                        if name and columns:
                            result[name] = [c["name"] for c in columns if "name" in c]
            except Exception:
                pass
    return result


def extract_unique_keys(work_dir: Path) -> dict[str, str]:
    """Extract the first unique-tested column per model from YML definitions."""
    import yaml

    result: dict[str, str] = {}
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "models" in data:
                    for model in data["models"]:
                        name = model.get("name")
                        if not name or name in result:
                            continue
                        for col in model.get("columns", []):
                            col_name = col.get("name")
                            if not col_name:
                                continue
                            tests = col.get("tests", [])
                            has_unique = any(
                                t == "unique" or (isinstance(t, dict) and "unique" in t)
                                for t in tests
                            )
                            if has_unique:
                                result[name] = col_name
                                break
            except Exception:
                pass
    return result


def extract_model_descriptions(work_dir: Path) -> dict[str, str]:
    """Extract model description text from YML files. Returns {model_name: description}."""
    import yaml

    result: dict[str, str] = {}
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "models" in data:
                    for model in data["models"]:
                        name = model.get("name")
                        desc = model.get("description", "").strip()
                        if name and desc:
                            result[name] = desc[:200].replace("\n", " ")
            except Exception:
                pass
    return result


def scan_macros(work_dir: Path) -> dict[str, str]:
    """Find macro names in macros/ dir by parsing {% macro name(...) %} patterns."""
    macros_dir = work_dir / "macros"
    if not macros_dir.exists():
        return {}

    macro_pattern = re.compile(r'\{%-?\s*macro\s+(\w+)\s*\(', re.IGNORECASE)
    result: dict[str, str] = {}

    for sql_file in macros_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in ("dbt_packages", ".claude", "target")):
            continue
        try:
            content = sql_file.read_text()
            for line in content.splitlines():
                m = macro_pattern.search(line)
                if m:
                    result[m.group(1)] = line.strip()
        except Exception:
            pass
    return result


def scan_current_date_models(work_dir: Path) -> list[tuple[str, int, str]]:
    """Find .sql files that reference current_date/now() and return [(path, line_no, line)]."""
    matches: list[tuple[str, int, str]] = []
    models_dir = work_dir / "models"
    if not models_dir.exists():
        return matches
    pat = re.compile(
        r'\bcurrent_date\b|\bCURRENT_DATE\b|\bnow\(\)|\bcurrent_timestamp\b'
        r'|\bCURRENT_TIMESTAMP\b|\bcurrent_timestamp_backcompat\b|\bgetdate\(\)',
        re.IGNORECASE,
    )
    for sql_file in models_dir.rglob("*.sql"):
        try:
            content = sql_file.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if pat.search(line):
                    rel_path = str(sql_file.relative_to(work_dir))
                    matches.append((rel_path, i, line.strip()))
        except Exception:
            pass
    return matches


def scan_nondeterministic_ordering(work_dir: Path) -> list[tuple[str, int, str]]:
    """Find .sql files with ROW_NUMBER/RANK/DENSE_RANK whose ORDER BY may not be unique.

    Returns [(rel_path, line_no, line)] for each window function call where the
    ORDER BY clause within a 5-line lookahead window is absent or contains a single
    column that does not carry a primary-key identifier suffix.
    """
    matches: list[tuple[str, int, str]] = []
    models_dir = work_dir / "models"
    if not models_dir.exists():
        return matches
    window_fn_pat = re.compile(
        r"ROW_NUMBER\s*\(\s*\)|DENSE_RANK\s*\(\s*\)|RANK\s*\(\s*\)",
        re.IGNORECASE,
    )
    order_by_pat = re.compile(r"ORDER\s+BY\s+(.*?)(?:\)|$)", re.IGNORECASE | re.DOTALL)
    pk_suffixes = ("_id", "_key", "_pk", "_uuid")
    for sql_file in models_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            lines = sql_file.read_text().splitlines()
            for i, line in enumerate(lines):
                if not window_fn_pat.search(line):
                    continue
                window = lines[i : min(len(lines), i + 5)]
                window_str = "\n".join(window)
                order_match = order_by_pat.search(window_str)
                if not order_match:
                    rel_path = str(sql_file.relative_to(work_dir))
                    matches.append((rel_path, i + 1, line.strip()))
                    continue
                order_cols = [c.strip() for c in order_match.group(1).split(",") if c.strip()]
                if len(order_cols) >= 2:
                    continue
                col_token = order_cols[0].lower() if order_cols else ""
                is_pk = col_token == "id" or any(col_token.endswith(s) for s in pk_suffixes)
                if not is_pk:
                    rel_path = str(sql_file.relative_to(work_dir))
                    matches.append((rel_path, i + 1, line.strip()))
        except Exception:
            pass
    return matches



def check_package_availability(work_dir: Path) -> list[str]:
    """Warn if any SQL files reference macros from packages not installed in dbt_packages/."""
    warnings: list[str] = []
    dbt_pkg_dir = work_dir / "dbt_packages"
    installed_namespaces: set[str] = set()
    if dbt_pkg_dir.exists():
        for child in dbt_pkg_dir.iterdir():
            if child.is_dir():
                installed_namespaces.add(child.name)

    referenced_namespaces: set[str] = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in (".claude", "dbt_packages", "target")):
            continue
        content = sql_file.read_text()
        for m in re.finditer(r'\{\{\s*(\w+)\.\w+\s*\(', content):
            ns = m.group(1)
            if ns not in ("ref", "source", "config", "this", "adapter", "var", "env_var"):
                referenced_namespaces.add(ns)

    for ns in referenced_namespaces - installed_namespaces:
        if ns != "dbt_utils" or "dbt_utils" not in installed_namespaces:
            warnings.append(f"Package '{ns}' referenced in SQL but not found in dbt_packages/")
    return warnings
