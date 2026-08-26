"""Locate the dbt project directory inside a workspace project.

Detection works on MANIFEST PATHS (the S3 workspace store is the file truth) —
never on a filesystem. A directory "contains a dbt project" when the manifest
carries `<dir>/dbt_project.yml`; the project root is represented as "".

Resolution order:
1. An explicit `settings["dbt_project_dir"]` wins, provided the directory
   actually exists in the manifest. A stale setting logs a warning and falls
   back to detection — it never errors.
2. Otherwise the first detected candidate (shallowest, ties broken
   alphabetically).
3. Otherwise None.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)

DBT_PROJECT_FILE = "dbt_project.yml"
DBT_PROJECT_DIR_SETTING = "dbt_project_dir"


def _manifest_paths(manifest) -> list[str]:
    """Accept a workspace-store Manifest (duck-typed on .paths()) or any
    iterable of project-relative path strings."""
    if manifest is None:
        return []
    paths = getattr(manifest, "paths", None)
    if callable(paths):
        return list(paths())
    if isinstance(manifest, Iterable):
        return [str(p) for p in manifest]
    raise TypeError(f"Unsupported manifest type: {type(manifest)!r}")


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip().strip("/")


def _normalize_dir(value: str) -> str:
    cleaned = _norm(value)
    return "" if cleaned == "." else cleaned


def _depth(directory: str) -> int:
    return 0 if directory == "" else directory.count("/") + 1


def detect_dbt_project_dirs(manifest) -> list[str]:
    """All directories (project-relative, "" for the root) whose manifest
    entry set contains dbt_project.yml, shallowest first, then alphabetical."""
    dirs: set[str] = set()
    for raw in _manifest_paths(manifest):
        path = _norm(raw)
        if path == DBT_PROJECT_FILE:
            dirs.add("")
        elif path.endswith("/" + DBT_PROJECT_FILE):
            dirs.add(path[: -(len(DBT_PROJECT_FILE) + 1)])
    return sorted(dirs, key=lambda d: (_depth(d), d))


def _dir_exists(directory: str, paths: list[str]) -> bool:
    if directory == "":
        return bool(paths)
    prefix = directory + "/"
    return any(_norm(p).startswith(prefix) for p in paths)


def resolve_dbt_project_dir_detailed(
    settings: dict | None, manifest
) -> tuple[str | None, str, list[str]]:
    """Resolve with provenance: (dbt_project_dir, source, detected) where
    source is "setting", "detected", or "none"."""
    paths = _manifest_paths(manifest)
    detected = detect_dbt_project_dirs(paths)

    explicit = (settings or {}).get(DBT_PROJECT_DIR_SETTING)
    if isinstance(explicit, str):
        directory = _normalize_dir(explicit)
        if _dir_exists(directory, paths):
            return directory, "setting", detected
        logger.warning(
            "Configured dbt_project_dir %r is not present in the workspace "
            "manifest; falling back to auto-detection",
            explicit,
        )
    elif explicit is not None:
        logger.warning(
            "Ignoring non-string dbt_project_dir setting %r; falling back to "
            "auto-detection",
            explicit,
        )

    if detected:
        return detected[0], "detected", detected
    return None, "none", detected


def resolve_dbt_project_dir(settings: dict | None, manifest) -> str | None:
    """Explicit setting wins (when valid), else first detection hit, else None."""
    value, _source, _detected = resolve_dbt_project_dir_detailed(settings, manifest)
    return value
