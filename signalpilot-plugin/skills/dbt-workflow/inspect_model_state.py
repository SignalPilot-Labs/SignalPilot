#!/usr/bin/env python3
"""Report dbt materialization and incremental-branch state before a build."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


EXCLUDED_PARTS = {".git", "dbt_packages", "logs", "target"}
CONFIG_BLOCK_RE = re.compile(r"{{\s*config\s*\((.*?)\)\s*}}", re.IGNORECASE | re.DOTALL)
CONFIG_VALUE_RE = re.compile(
    r"\b(?P<key>materialized|unique_key|incremental_strategy)\s*=\s*"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
JINJA_CONTROL_RE = re.compile(r"{%[-\s]*(if\b.*?|endif)\s*-?%}", re.IGNORECASE | re.DOTALL)
POPULATION_SQL_RE = re.compile(r"\b(where|and|or|join|having|qualify|limit)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ModelState:
    name: str
    path: Path
    project_materialization: str
    yaml_materialization: str | None
    inline_materialization: str | None
    effective_materialization: str
    unique_key: str | None
    incremental_strategy: str | None
    incremental_blocks: tuple[str, ...]
    population_blocks: tuple[str, ...]


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected a mapping in {path}")
    return value


def _materialized_value(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    for key in ("+materialized", "materialized"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _walk_project_config(node: Any, parts: Iterable[str], current: str) -> str:
    if not isinstance(node, dict):
        return current
    current = _materialized_value(node) or current
    for part in parts:
        child = node.get(part)
        if not isinstance(child, dict):
            break
        node = child
        current = _materialized_value(node) or current
    return current


def project_materialization(project: dict[str, Any], relative_sql: Path) -> str:
    models_config = project.get("models")
    if not isinstance(models_config, dict):
        return "view"

    parts = list(relative_sql.with_suffix("").parts)
    current = _materialized_value(models_config) or "view"
    project_name = project.get("name")
    if isinstance(project_name, str) and isinstance(models_config.get(project_name), dict):
        return _walk_project_config(models_config[project_name], parts, current)
    return _walk_project_config(models_config, parts, current)


def yaml_materializations(project_dir: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(project_dir.rglob("*.yml")) + sorted(project_dir.rglob("*.yaml")):
        if EXCLUDED_PARTS.intersection(path.relative_to(project_dir).parts):
            continue
        try:
            document = _load_yaml(path)
        except ValueError:
            continue
        models = document.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                continue
            config = model.get("config")
            materialized = _materialized_value(config)
            if materialized:
                values[model["name"]] = materialized
    return values


def sql_config(sql: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for block in CONFIG_BLOCK_RE.findall(sql):
        for match in CONFIG_VALUE_RE.finditer(block):
            values[match.group("key").lower()] = match.group("value").strip()
    return values


def incremental_blocks(sql: str) -> tuple[str, ...]:
    blocks: list[str] = []
    stack: list[tuple[bool, int]] = []
    for match in JINJA_CONTROL_RE.finditer(sql):
        token = match.group(1).strip()
        if token.lower().startswith("if"):
            stack.append((bool(re.search(r"\bis_incremental\s*\(\s*\)", token, re.I)), match.end()))
            continue
        if not stack:
            continue
        is_incremental, start = stack.pop()
        if is_incremental:
            body = re.sub(r"\s+", " ", sql[start : match.start()]).strip()
            blocks.append(body or "<empty>")
    return tuple(blocks)


def find_model_paths(project_dir: Path) -> dict[str, list[Path]]:
    paths: dict[str, list[Path]] = {}
    for path in sorted(project_dir.rglob("*.sql")):
        if EXCLUDED_PARTS.intersection(path.relative_to(project_dir).parts):
            continue
        paths.setdefault(path.stem, []).append(path)
    return paths


def inspect_model(
    project_dir: Path,
    project: dict[str, Any],
    yaml_configs: dict[str, str],
    path: Path,
) -> ModelState:
    sql = path.read_text(encoding="utf-8")
    config = sql_config(sql)
    models_dir = project_dir / str(project.get("model-paths", ["models"])[0])
    try:
        relative_sql = path.relative_to(models_dir)
    except ValueError:
        relative_sql = path.relative_to(project_dir)

    project_mat = project_materialization(project, relative_sql)
    yaml_mat = yaml_configs.get(path.stem)
    inline_mat = config.get("materialized")
    effective = (inline_mat or yaml_mat or project_mat).lower()
    blocks = incremental_blocks(sql)
    population = tuple(block for block in blocks if POPULATION_SQL_RE.search(block))
    return ModelState(
        name=path.stem,
        path=path,
        project_materialization=project_mat,
        yaml_materialization=yaml_mat,
        inline_materialization=inline_mat.lower() if inline_mat else None,
        effective_materialization=effective,
        unique_key=config.get("unique_key"),
        incremental_strategy=config.get("incremental_strategy"),
        incremental_blocks=blocks,
        population_blocks=population,
    )


def format_state(state: ModelState, project_dir: Path) -> tuple[list[str], bool]:
    lines = [f"MODEL {state.name} ({state.path.relative_to(project_dir).as_posix()})"]
    lines.append(f"  project materialization: {state.project_materialization}")
    lines.append(f"  YML materialization: {state.yaml_materialization or 'none'}")
    lines.append(f"  inline materialization: {state.inline_materialization or 'none'}")
    lines.append(f"  effective materialization: {state.effective_materialization}")

    failed = False
    declared = state.yaml_materialization or state.project_materialization
    if state.inline_materialization and state.inline_materialization != declared:
        lines.append(
            f"  REVIEW: inline materialization overrides declared {declared} materialization"
        )
    if state.incremental_blocks and state.effective_materialization != "incremental":
        lines.append("  FAIL: is_incremental() cannot execute for this materialization")
        failed = True
    if state.effective_materialization == "incremental" and not state.incremental_blocks:
        lines.append("  WARN: incremental model has no is_incremental() branch")
    if state.population_blocks:
        lines.append("  WARN: first-build and later-run populations differ")
        for block in state.population_blocks:
            preview = block if len(block) <= 180 else f"{block[:177]}..."
            lines.append(f"    incremental SQL: {preview}")
    if state.unique_key:
        lines.append(f"  unique_key: {state.unique_key}")
    if state.incremental_strategy:
        lines.append(f"  incremental_strategy: {state.incremental_strategy}")
    if len(lines) == 5:
        lines.append("  PASS: no materialization-state hazard found")
    return lines, failed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect dbt model materialization and incremental branch state."
    )
    parser.add_argument("project_directory", type=Path)
    parser.add_argument("model_names", nargs="+", help="Exact dbt model names")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    project_dir = args.project_directory.resolve()
    project_file = project_dir / "dbt_project.yml"
    if not project_file.is_file():
        print(f"ERROR: dbt_project.yml not found under {project_dir}", file=sys.stderr)
        return 2

    try:
        project = _load_yaml(project_file)
        yml_configs = yaml_materializations(project_dir)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    paths = find_model_paths(project_dir)
    any_failed = False
    for name in args.model_names:
        matches = paths.get(name, [])
        if not matches:
            print(f"MODEL {name}\n  FAIL: SQL file not found")
            any_failed = True
            continue
        if len(matches) > 1:
            listed = ", ".join(path.relative_to(project_dir).as_posix() for path in matches)
            print(f"MODEL {name}\n  FAIL: multiple SQL files found: {listed}")
            any_failed = True
            continue
        try:
            state = inspect_model(project_dir, project, yml_configs, matches[0])
            lines, failed = format_state(state, project_dir)
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"MODEL {name}\n  FAIL: {exc}")
            any_failed = True
            continue
        print("\n".join(lines))
        any_failed = any_failed or failed

    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
