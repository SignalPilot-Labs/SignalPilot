#!/usr/bin/env python3
"""Pre-scan a dbt project and emit a structured context block.

Used by the dbt-workflow SKILL.md via !`python3 scan_project.py` to inject
project state for the workflow before model work starts.

Filesystem-only scan: YML models, SQL stubs, dependencies, required columns,
sources, macros, and current_date hazards. Database-derived hints (lookup joins,
staging gaps, parent-child driving tables, materialization) come from the
analyze_project_db / list_tables MCP tools.
"""

from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows (prevents mojibake on em dashes, arrows, etc.)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SKIP_DIRS = (".claude", "dbt_packages", "target", "macros", "__pycache__")

# Directory names never walked into. SKIP_DIRS is a substring check applied to
# whole paths after the fact; these prune the walk itself.
# Macro bodies are useful but they are not the point of the scan; these keep the
# section from crowding out everything else in the agent's context.
MACRO_BODY_MAX_LINES = 40
# Longest sibling list printed for one directory before it is summarised.
SIBLING_LIST_MAX = 25
MACRO_BODY_LINE_BUDGET = 400

WALK_SKIP_DIRS = frozenset(
    {
        ".claude", "dbt_packages", "target", "__pycache__", ".git", ".venv",
        "node_modules", "logs", ".ruff_cache", ".pytest_cache",
    }
)


def _read_text(path: Path) -> str:
    """Read a text file, stripping UTF-8 BOM if present."""
    raw = path.read_bytes()
    if raw[:3] == b'\xef\xbb\xbf':
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


# ── YML parsing ───────────────────────────────────────────────────────────
#
# dbt schema files are read with PyYAML, once each. The regex readers below are
# the fallback for a runtime without PyYAML; they are indentation-fragile and
# must not be trusted when the real parser is available. Both of these are the
# same document to YAML, and the flush form inverts a depth-by-indent guess --
# the model entry sits where a column entry sits in the indented form:
#
#     models:                     models:
#       - name: my_model          - name: my_model
#         columns:                  columns:
#           - name: col_a           - name: col_a
#
# A repo can hold both styles, so guessing cost us 259 "models" in one file
# that really declares 1, and those phantoms then drove a quadratic lookup.


class YmlFacts:
    """Everything one pass over the schema files yields."""

    def __init__(self) -> None:
        self.models: set[str] = set()
        self.columns: dict[str, list[str]] = {}
        self.descriptions: dict[str, str] = {}
        self.materializations: dict[str, str] = {}
        self.sources: list[str] = []
        # model name -> the schema file that declares it, and its siblings there
        self.declared_in: dict[str, str] = {}
        self.siblings: dict[str, list[str]] = {}


def _yaml_module():
    try:
        import yaml
    except ImportError:
        return None
    return yaml


def _facts_from_parsed(doc: object, rel_path: str, facts: YmlFacts) -> bool:
    """Fold one parsed schema document into ``facts``. False when the document
    is not a mapping we understand (caller falls back to the regex readers)."""
    if not isinstance(doc, dict):
        return False
    models = doc.get("models")
    if isinstance(models, list):
        names_here = [
            m["name"] for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)
        ]
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name")
            if not isinstance(name, str):
                continue
            facts.models.add(name)
            facts.declared_in[name] = rel_path
            facts.siblings[name] = [n for n in names_here if n != name]
            cols = model.get("columns")
            if isinstance(cols, list):
                facts.columns[name] = [
                    c["name"] for c in cols if isinstance(c, dict) and isinstance(c.get("name"), str)
                ]
            desc = model.get("description")
            if isinstance(desc, str) and desc.strip():
                facts.descriptions[name] = desc.strip()[:200].replace("\n", " ")
            config = model.get("config")
            if isinstance(config, dict) and isinstance(config.get("materialized"), str):
                facts.materializations[name] = config["materialized"]
    sources = doc.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("name"), str):
                continue
            src = source["name"]
            tables = source.get("tables")
            if isinstance(tables, list):
                for table in tables:
                    if isinstance(table, dict) and isinstance(table.get("name"), str):
                        facts.sources.append(f"{src}.{table['name']}")
            else:
                facts.sources.append(src)
    return True


def collect_yml_facts(yml_files: list[Path], work_dir: Path) -> YmlFacts:
    """One pass over the schema files. PyYAML when available, regex otherwise."""
    facts = YmlFacts()
    yaml = _yaml_module()
    for yml_file in yml_files:
        try:
            text = _read_text(yml_file)
        except Exception:
            continue
        rel = str(yml_file.relative_to(work_dir)) if yml_file.is_relative_to(work_dir) else yml_file.name
        parsed_ok = False
        if yaml is not None:
            try:
                parsed_ok = _facts_from_parsed(yaml.safe_load(text), rel, facts)
            except Exception:
                parsed_ok = False  # malformed file: fall back for this one
        if not parsed_ok:
            names = _extract_model_names(text)
            facts.models.update(names)
            for name in names:
                facts.declared_in.setdefault(name, rel)
                facts.siblings.setdefault(name, [n for n in names if n != name])
            facts.columns.update(_extract_columns(text))
            facts.descriptions.update(_extract_descriptions(text))
            facts.materializations.update(_extract_materializations(text))
            facts.sources.extend(_extract_sources(text))
    return facts



def _extract_model_names(yml_text: str) -> set[str]:
    names: set[str] = set()
    in_models = False
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("models:") and indent <= 2:
            in_models = True
            continue
        if in_models and indent <= 0 and stripped and not stripped.startswith("#"):
            if not stripped.startswith("-"):
                in_models = False
                continue
        if in_models and 1 <= indent <= 4:
            m = re.match(r'-\s*name:\s*(\S+)', stripped)
            if m:
                names.add(m.group(1))
    return names


def _extract_columns(yml_text: str) -> dict[str, list[str]]:
    """Extract column names per model from YML. Simple regex parser."""
    result: dict[str, list[str]] = {}
    current_model = None
    in_columns = False
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        # Model name
        m = re.match(r'-\s*name:\s*(\S+)', stripped)
        if m and 1 <= indent <= 4:
            current_model = m.group(1)
            in_columns = False
            continue
        if current_model and stripped.startswith("columns:"):
            in_columns = True
            continue
        if in_columns and indent <= 4 and stripped and not stripped.startswith("-"):
            in_columns = False
            continue
        if in_columns:
            cm = re.match(r'-\s*name:\s*(\S+)', stripped)
            if cm:
                result.setdefault(current_model, []).append(cm.group(1))
    return result


def _extract_descriptions(yml_text: str) -> dict[str, str]:
    """Extract model descriptions from YML."""
    result: dict[str, str] = {}
    current_model = None
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        m = re.match(r'-\s*name:\s*(\S+)', stripped)
        if m and 1 <= indent <= 4:
            current_model = m.group(1)
            continue
        if current_model and stripped.startswith("description:"):
            desc = stripped[len("description:"):].strip().strip("'\"")
            if desc:
                result[current_model] = desc[:200].replace("\n", " ")
    return result


def _extract_materializations(yml_text: str) -> dict[str, str]:
    """Extract model materializations from YML config blocks."""
    result: dict[str, str] = {}
    current_model = None
    in_config = False
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        m = re.match(r'-\s*name:\s*(\S+)', stripped)
        if m and 1 <= indent <= 4:
            current_model = m.group(1)
            in_config = False
            continue
        if current_model and stripped.startswith("config:"):
            in_config = True
            continue
        if in_config and indent <= 4 and stripped and not stripped.startswith("materialized"):
            if not stripped.startswith(" ") and not stripped.startswith("-"):
                in_config = False
                continue
        if in_config and current_model:
            mat = re.match(r'materialized:\s*(\S+)', stripped)
            if mat:
                result[current_model] = mat.group(1).strip("'\"")
                in_config = False
    return result


def _extract_sources(yml_text: str) -> list[str]:
    """Extract source definitions from YML."""
    sources: list[str] = []
    in_sources = False
    current_source = None
    in_tables = False
    table_names: list[str] = []
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("sources:"):
            in_sources = True
            continue
        if in_sources and indent <= 0 and stripped and not stripped.startswith("#") and not stripped.startswith("-"):
            # Flush last source
            if current_source and table_names:
                sources.append(f"  source('{current_source}', '<table>') — tables: {', '.join(table_names)}")
            in_sources = False
            continue
        if in_sources:
            m = re.match(r'-\s*name:\s*(\S+)', stripped)
            if m and indent <= 4:
                # Flush previous source
                if current_source and table_names:
                    sources.append(f"  source('{current_source}', '<table>') — tables: {', '.join(table_names)}")
                current_source = m.group(1)
                table_names = []
                in_tables = False
                continue
            if stripped.startswith("tables:"):
                in_tables = True
                continue
            if in_tables:
                tm = re.match(r'-\s*name:\s*(\S+)', stripped)
                if tm:
                    table_names.append(tm.group(1))
    # Flush final
    if current_source and table_names:
        sources.append(f"  source('{current_source}', '<table>') — tables: {', '.join(table_names)}")
    return sources


def _extract_deps_from_sql(work_dir: Path) -> dict[str, list[str]]:
    """Extract ref() dependencies from SQL files."""
    deps: dict[str, list[str]] = {}
    ref_pat = re.compile(r"\{\{\s*ref\(['\"](\w+)['\"]\)\s*\}\}")
    for sql_file in iter_project_files(work_dir, (".sql",)):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            content = _read_text(sql_file)
            refs = ref_pat.findall(content)
            if refs:
                deps[sql_file.stem] = sorted(set(refs))
        except Exception:
            pass
    return deps


# ── SQL classification ────────────────────────────────────────────────────

def classify_sql_models(work_dir: Path) -> tuple[set[str], set[str]]:
    complete: set[str] = set()
    stubs: set[str] = set()
    for sql_file in iter_project_files(work_dir, (".sql",)):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            content = _read_text(sql_file).strip()
        except Exception:
            continue
        is_stub = (
            len(content) < 5
            or re.match(r'^select\s+\*\s+from\s+', content, re.IGNORECASE)
            or content.endswith(",")
            or content.endswith("(")
            or (content.count("(") > content.count(")"))
            or re.search(r'(?i)\bREPLACE\b.*\bENTIRE\b.*\bFILE\b', content)
            or re.match(r'^--\s*(TODO|FIXME|PLACEHOLDER)', content, re.IGNORECASE)
        )
        if is_stub:
            stubs.add(sql_file.stem)
        else:
            complete.add(sql_file.stem)
    return complete, stubs


# ── Macro scanner ─────────────────────────────────────────────────────────

def scan_macros(work_dir: Path) -> list[tuple[str, str]]:
    """Return list of (macro_name, full_body) tuples from the macros/ directory."""
    macros_dir = work_dir / "macros"
    if not macros_dir.exists():
        return []
    # One entry per macro, holding that macro's own block. Carrying the whole
    # file per macro multiplied the output by the macros-per-file count: a
    # 354-line file defining 20 macros emitted 7,080 lines, and one real project
    # produced 18,837 lines of macro listing.
    start_pat = re.compile(r"\{%-?\s*macro\s+(\w+)\s*\(([^)]*)\)", re.IGNORECASE)
    end_pat = re.compile(r"\{%-?\s*endmacro\s*-?%\}", re.IGNORECASE)
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sql_file in iter_project_files(macros_dir, (".sql",)):
        try:
            text = _read_text(sql_file)
        except Exception:
            continue
        for match in start_pat.finditer(text):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            end = end_pat.search(text, match.end())
            block = text[match.start() : end.end() if end else match.end()]
            signature = f"{name}({match.group(2).strip()})"
            result.append((signature, block.strip()))
    return sorted(result, key=lambda x: x[0])


# ── current_date scanner ─────────────────────────────────────────────────

def scan_current_date(work_dir: Path) -> list[str]:
    models_dir = work_dir / "models"
    if not models_dir.exists():
        return []
    pat = re.compile(
        r'\bcurrent_date\b|\bnow\(\)|\bcurrent_timestamp\b|\bgetdate\(\)',
        re.IGNORECASE,
    )
    hits: list[str] = []
    for sql_file in models_dir.rglob("*.sql"):
        try:
            for i, line in enumerate(_read_text(sql_file).splitlines(), 1):
                if pat.search(line):
                    rel = str(sql_file.relative_to(work_dir))
                    hits.append(f"  {rel}:{i}: {line.strip()}")
        except Exception:
            pass
    return hits


# ── Package scanner ───────────────────────────────────────────────────────

def _find_sibling_patterns(
    work_dir: Path,
    work_models: set[str],
    complete_models: set[str],
    all_columns: dict[str, list[str]],
) -> dict[str, list[tuple[str, int]]]:
    """For each stub/missing model, find complete siblings in the same directory."""
    sql_dirs: dict[str, Path] = {}
    for sql_file in iter_project_files(work_dir, (".sql",)):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        sql_dirs[sql_file.stem] = sql_file.parent

    result: dict[str, list[tuple[str, int]]] = {}
    for model in sorted(work_models):
        target_dir = sql_dirs.get(model)
        if not target_dir:
            continue
        siblings = []
        for sql_file in target_dir.glob("*.sql"):
            sib = sql_file.stem
            if sib == model or sib not in complete_models:
                continue
            cols = all_columns.get(sib, [])
            siblings.append((sib, len(cols) if cols else 0))
        if siblings:
            result[model] = siblings
    return result


def scan_packages(work_dir: Path) -> str:
    if not (work_dir / "packages.yml").exists():
        return ""
    lines: list[str] = []
    pkg_dir = work_dir / "dbt_packages"
    if pkg_dir.exists():
        pkg_models: list[str] = []
        for sql_file in pkg_dir.rglob("*.sql"):
            if sql_file.stem.startswith("stg_") or sql_file.stem.startswith("int_"):
                pkg_models.append(sql_file.stem)
        if pkg_models:
            lines.append(f"Package staging/intermediate models available: {', '.join(sorted(set(pkg_models))[:20])}")

    # Check for dbt.* namespace usage in existing SQL
    for sql_file in iter_project_files(work_dir, (".sql",)):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            if "dbt." in _read_text(sql_file):
                lines.append("dbt.* cross-adapter macros ARE available: dbt.date_trunc(), dbt.length(), dbt.replace(), etc.")
                break
        except Exception:
            pass
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────

def _resolve_work_dir(argv: list[str]) -> Path | None:
    """The dbt project to scan.

    An explicit path wins, then ``SP_DBT_PROJECT_DIR`` (the directory the
    platform configured for this project), then the current directory. Only as
    a last resort is a child guessed, and never when several children hold a
    dbt_project.yml -- a repo with five dbt projects would otherwise be scanned
    as whichever one the filesystem listed first.
    """
    candidates: list[Path] = []
    if len(argv) > 1:
        candidates.append(Path(argv[1]))
    configured = os.environ.get("SP_DBT_PROJECT_DIR", "").strip()
    base = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    if configured:
        candidates.append(base / configured)
        candidates.append(Path(configured))
    candidates.append(Path.cwd())
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if (resolved / "dbt_project.yml").is_file():
            return resolved
    root = candidates[0].resolve()
    children = sorted(
        child for child in root.iterdir() if child.is_dir() and (child / "dbt_project.yml").is_file()
    ) if root.is_dir() else []
    if len(children) == 1:
        return children[0]
    if len(children) > 1:
        names = ", ".join(child.name for child in children)
        print(f"(several dbt projects here: {names})")
        print("(pass the project directory, or set SP_DBT_PROJECT_DIR — skip project scan)")
        return None
    return None


_WALK_CACHE: dict[tuple[str, tuple[str, ...]], list[Path]] = {}


def iter_project_files(work_dir: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """Files under ``work_dir`` with these suffixes, pruning skipped directories
    during the walk. ``rglob`` descends into dbt_packages/target/.git first and
    filters afterwards, which is both slower and easy to get wrong."""
    key = (str(work_dir), suffixes)
    cached = _WALK_CACHE.get(key)
    if cached is not None:
        return cached
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(work_dir):
        dirnames[:] = [d for d in dirnames if d not in WALK_SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if filename.endswith(suffixes):
                found.append(Path(dirpath) / filename)
    _WALK_CACHE[key] = found
    return found


def main():
    work_dir = _resolve_work_dir(sys.argv)
    if work_dir is None:
        if not any(Path(a).is_dir() for a in sys.argv[1:2]):
            print("(no dbt_project.yml found — skip project scan)")
        return

    # Scan YML
    yml_models: set[str] = set()
    all_columns: dict[str, list[str]] = {}
    all_descriptions: dict[str, str] = {}
    all_materializations: dict[str, str] = {}
    all_sources: list[str] = []

    yml_files = iter_project_files(work_dir, (".yml", ".yaml"))
    facts = collect_yml_facts(yml_files, work_dir)
    yml_models = facts.models
    all_columns = facts.columns
    all_descriptions = facts.descriptions
    all_materializations = facts.materializations
    all_sources = facts.sources

    # Classify SQL
    complete_models, stub_models = classify_sql_models(work_dir)
    sql_models = complete_models | stub_models
    missing_models = yml_models - sql_models

    # Complete models = those with a non-stub SQL file. Materialization status
    # (which exist as tables) and other DB-derived hints come from the
    # analyze_project_db MCP tool, not this filesystem scanner.
    complete = yml_models & complete_models

    # Dependencies
    deps = _extract_deps_from_sql(work_dir)

    # Packages
    has_packages = (work_dir / "packages.yml").exists()

    # ── Output ────────────────────────────────────────────────────────────

    print(f"## dbt Project Scan: {work_dir.name}")
    print()

    if has_packages:
        print("Run `dbt deps` first — this project has a packages.yml.")
    else:
        print("Do NOT run `dbt deps` — packages are pre-installed.")
    print()

    print("MODELS TO BUILD (defined in YML but no SQL file — create EXACT filenames):")
    if missing_models:
        for m in sorted(missing_models):
            mat = all_materializations.get(m, "table")
            # Both recorded by the single YML pass. Re-parsing every schema
            # file per missing model was O(models x files) yaml.safe_load calls
            # and hung for minutes on a real project.
            yml_file = facts.declared_in.get(m, "")
            siblings_in_yml = facts.siblings.get(m, [])
            sib_str = f"  siblings: {', '.join(siblings_in_yml)}" if siblings_in_yml else ""
            yml_str = f"  YML: {yml_file}" if yml_file else ""
            print(f"  → {m}.sql  (materialized={mat}){yml_str}")
            if sib_str:
                print(f"    Read sibling YML descriptions for column vocabulary hints")
    else:
        print("  none")
    print()

    # Detect var() reference conventions from dbt_project.yml
    dbt_project_yml = work_dir / "dbt_project.yml"
    if dbt_project_yml.exists():
        try:
            import yaml
            with open(dbt_project_yml) as f:
                proj_cfg = yaml.safe_load(f) or {}
            all_vars = proj_cfg.get("vars", {})
            var_refs: list[str] = []
            for section_key, section_val in all_vars.items():
                if isinstance(section_val, dict):
                    for var_name, var_val in section_val.items():
                        if isinstance(var_val, str) and "ref(" in var_val:
                            var_refs.append(
                                f"  var('{var_name}') → {var_val}"
                            )
            if var_refs:
                print("VAR ALIASES (use var() instead of ref() in new models — project convention):")
                for vr in var_refs:
                    print(vr)
                print()
        except Exception:
            pass

    print("STUBS TO REWRITE (SQL file exists but is incomplete):")
    print(f"  {', '.join(sorted(stub_models)) if stub_models else 'none'}")
    print()

    print("COMPLETE MODELS (have a non-stub SQL file — call list_tables to confirm which are materialized):")
    print(f"  {', '.join(sorted(complete)) if complete else 'none'}")
    if complete:
        print("  ⚠ These SQL files already exist and compile. Do NOT delete or recreate them.")

    # Orphan SQL files (SQL exists but no YML model)
    orphans = sql_models - yml_models
    if orphans:
        print()
        print("SQL FILES WITHOUT YML (usable as ref() targets — prefer ref() over source()):")
        for o in sorted(orphans):
            if missing_models:
                for m in sorted(missing_models):
                    if o in m or m in o or (len(o) > 5 and o[:5] == m[:5]):
                        print(f"  {o}.sql — possible match: {m} (defined in YML)")
                        break
                else:
                    print(f"  {o}.sql — no YML definition found")
            else:
                print(f"  {o}.sql — no YML definition found")
    print()

    # Sibling patterns for ALL yml models (helps with column conventions)
    all_work = yml_models  # Show siblings for every model, not just stubs/missing
    sibling_info = _find_sibling_patterns(work_dir, all_work, complete_models | stub_models, all_columns)
    if sibling_info:
        print("SIBLING PATTERNS (complete models in same directory — read for column conventions):")
        # Grouped by the sibling set, not printed per model. Every model in a
        # directory has the same siblings, so the per-model form repeated the
        # directory's whole model list once per model: 150 KB for one project,
        # quadratic in models per directory.
        # Key on the directory's whole model set (siblings + the model itself),
        # which is identical for every model in that directory. Keying on the
        # sibling list alone never collapses, because it excludes self.
        by_siblings: dict[frozenset[str], list[str]] = {}
        members: dict[frozenset[str], list[tuple[str, int]]] = {}
        for model, siblings in sibling_info.items():
            key = frozenset([model, *(name for name, _ in siblings)])
            by_siblings.setdefault(key, []).append(model)
            members.setdefault(key, sorted({*siblings, *[(model, len(all_columns.get(model, [])))]}))
        for key, models in sorted(by_siblings.items(), key=lambda kv: sorted(kv[1])[0]):
            siblings = members[key]
            shown = list(siblings)[:SIBLING_LIST_MAX]
            sib_strs = [f"{s} ({c} cols)" if c else f"{s} (? cols)" for s, c in shown]
            more = len(siblings) - len(shown)
            if more > 0:
                sib_strs.append(f"... {more} more")
            print(f"  models in this directory ({len(models)} being worked on): {', '.join(sorted(models))}")
            print(f"    directory contents: {', '.join(sib_strs)}")
        print()

    # Reverse dependencies — models that ref() other models
    work_models = missing_models | stub_models
    reverse_deps: dict[str, list[str]] = {}
    for src_model, ref_list in deps.items():
        for ref_name in ref_list:
            if ref_name in yml_models and src_model != ref_name:
                reverse_deps.setdefault(ref_name, []).append(src_model)
    if reverse_deps:
        print("REFERENCING MODELS (models that ref() these — read for column conventions):")
        for model, consumers in sorted(reverse_deps.items()):
            print(f"  {model} is referenced by: {', '.join(sorted(consumers))}")
        print()

    # Upstream convention — who reads what, and layering violations worth copying
    model_paths: dict[str, str] = {}
    for sql_file in iter_project_files(work_dir, (".sql",)):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        model_paths[sql_file.stem] = str(sql_file.relative_to(work_dir)).replace("\\", "/")

    def _model_layer(name: str) -> str:
        p = model_paths.get(name, "")
        if name.startswith("stg_") or "/staging/" in p or p.startswith("staging/"):
            return "staging"
        if name.startswith("int_") or "/intermediate/" in p or p.startswith("intermediate/"):
            return "intermediate"
        return "mart"

    all_consumers: dict[str, list[str]] = {}
    for src_model, ref_list in deps.items():
        for ref_name in ref_list:
            if src_model != ref_name:
                all_consumers.setdefault(ref_name, []).append(src_model)

    int_summary: list[str] = []
    convention_lines: list[str] = []
    for m, consumers in sorted(all_consumers.items()):
        layer = _model_layer(m)
        if layer == "intermediate":
            marts = sorted(c for c in set(consumers) if _model_layer(c) == "mart")
            if marts:
                int_summary.append(f"  {len(marts)} mart(s) read {m}: {', '.join(marts)}")
        elif layer == "staging":
            wrapping_ints = sorted(c for c in set(consumers) if _model_layer(c) == "intermediate")
            direct_marts = sorted(c for c in set(consumers) if _model_layer(c) == "mart")
            if wrapping_ints and direct_marts:
                convention_lines.append(
                    f"  {m}: intermediate(s) {', '.join(wrapping_ints)} wrap it, and mart(s) "
                    f"{', '.join(direct_marts)} also read it directly — check which convention "
                    f"your model's siblings follow"
                )
    if int_summary or convention_lines:
        print("UPSTREAM CONVENTION (who reads what — new models follow the project's layering):")
        for line in int_summary[:12]:
            print(line)
        for line in convention_lines[:12]:
            print(line)
        print()

    # Dependencies for models to build/rewrite
    dep_lines = []
    for model in sorted(work_models):
        if model in deps:
            dep_lines.append(f"  {model} depends on: {', '.join(deps[model])}")
    if dep_lines:
        print("DEPENDENCIES (build in this order):")
        print("\n".join(dep_lines))
    else:
        print("DEPENDENCIES: (check YML refs and existing SQL for dependency info)")
    print()

    # Required columns
    col_lines = []
    for model in sorted(work_models):
        desc = all_descriptions.get(model, "")
        desc_str = f" | DESC: {desc}" if desc else ""
        if model in all_columns:
            col_lines.append(f"  {model}: {', '.join(all_columns[model])}{desc_str}")
    if col_lines:
        print("REQUIRED COLUMNS (must match exactly — missing columns = guaranteed fail):")
        print("\n".join(col_lines))
    else:
        print("REQUIRED COLUMNS: (read YML files for column specs)")
    print()

    # Sources
    if all_sources:
        print("AVAILABLE SOURCES:")
        print("\n".join(all_sources))
        print()

    # Macros — include full definitions so the agent knows what they do
    macros = scan_macros(work_dir)
    if macros:
        print("AVAILABLE MACROS (use these in your models — they exist for a reason):")
        # Signatures are the part that changes what the agent writes. Bodies are
        # included only while they stay within budget; `Read` the file for the
        # rest. Printing every body in full is what made this section 18k lines.
        budget = MACRO_BODY_LINE_BUDGET
        for name, body in macros:
            lines = body.splitlines()
            print(f"\n  ### {name}")
            if budget <= 0:
                continue
            shown = lines[: min(len(lines), budget, MACRO_BODY_MAX_LINES)]
            for line in shown:
                print(f"  {line}")
            budget -= len(shown)
            if len(shown) < len(lines):
                print(f"  ... {len(lines) - len(shown)} more lines — Read the macro file for the rest")
        if budget <= 0:
            print("\n  (macro bodies truncated — signatures above are complete)")
        print()

    # Packages
    pkg_info = scan_packages(work_dir)
    if pkg_info:
        print("PACKAGES:")
        print(f"  {pkg_info}")
        print()

    # Snapshot detection
    snapshots_dir = work_dir / "snapshots"
    if snapshots_dir.exists():
        snap_files = list(snapshots_dir.rglob("*.sql"))
        print(f"SNAPSHOTS DIRECTORY: {len(snap_files)} snapshot file(s) in snapshots/")
        print("  Load `/signalpilot-dbt:dbt-snapshots` skill. Run DESCRIBE on source tables for exact column casing.")
        print()

    # Database-derived hints (lookup joins, staging-vs-raw gaps, parent-child
    # driving tables) come from the analyze_project_db MCP tool — not this scanner.
    print("DB HINTS: call analyze_project_db(connection_name) for lookup joins, "
          "staging-vs-raw gaps, and parent-child driving-table hints.")
    print()

    # current_date warnings
    cd_hits = scan_current_date(work_dir)
    if cd_hits:
        print("WARNING — FILES USING current_date (fix date spines and date caps with fix_date_spine_hazards; keep current_date that implements a present-anchored YML rule like 'current fiscal year' or 'as of today'):")
        print("\n".join(cd_hits))
        print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"(project scan error: {e})")
