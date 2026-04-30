"""
Mtime-based cache for ProjectMap scans.

Scanning a small project is ~10ms and scanning synthea001 is ~50ms, so
caching isn't strictly needed — but within an agent session the same tool
may be called many times, and re-running PyYAML + regex on unchanged files
is pointless. We cache the rendered markdown keyed by (project_dir, focus,
max_models_per_section, include_columns, fingerprint), and invalidate on
fingerprint change.

Fingerprint = (max yml mtime, max sql mtime, max dbt_project.yml mtime,
count of yml files, count of sql files). Cheap to compute and sufficient:
any file add/remove/edit bumps at least one of these.
"""

from __future__ import annotations

import os
from pathlib import Path

_CACHE: dict[tuple, tuple[str, str]] = {}
_MAX_ENTRIES = 32


def fingerprint(project_dir: Path) -> str:
    """Return a cheap fingerprint of the project's tracked files.

    We walk the same file set the scanner does (yml, sql, dbt_project.yml,
    packages.yml, profiles.yml) and produce a string of max mtimes + counts.
    This is weaker than a content hash but 100x cheaper and adequate for
    invalidation within an agent session.
    """
    yml_max = 0.0
    yml_count = 0
    sql_max = 0.0
    sql_count = 0
    config_max = 0.0

    # Root config files
    for name in ("dbt_project.yml", "packages.yml", "profiles.yml"):
        p = project_dir / name
        if p.exists():
            try:
                config_max = max(config_max, p.stat().st_mtime)
            except OSError:
                pass

    # Models and macros trees
    models_dir = project_dir / "models"
    macros_dir = project_dir / "macros"

    for root_dir in (models_dir, macros_dir):
        if not root_dir.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Prune skip dirs in-place (same logic as scanner).
            dirnames[:] = [
                d for d in dirnames if d not in ("dbt_packages", "target", "logs", ".claude", "__pycache__", ".git")
            ]
            for fname in filenames:
                suffix = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                try:
                    mtime = os.stat(os.path.join(dirpath, fname)).st_mtime
                except OSError:
                    continue
                if suffix in ("yml", "yaml"):
                    yml_count += 1
                    if mtime > yml_max:
                        yml_max = mtime
                elif suffix == "sql":
                    sql_count += 1
                    if mtime > sql_max:
                        sql_max = mtime

    return f"y{yml_count}@{yml_max:.3f}|s{sql_count}@{sql_max:.3f}|c@{config_max:.3f}"


def cache_get(key: tuple) -> str | None:
    """Return a cached rendered string if the fingerprint still matches."""
    entry = _CACHE.get(key[:-1])
    if entry is None:
        return None
    stored_fp, payload = entry
    if stored_fp != key[-1]:
        return None
    return payload


def cache_put(key: tuple, payload: str) -> None:
    """Store a rendered string under the given key, evicting oldest entries."""
    _CACHE[key[:-1]] = (key[-1], payload)
    if len(_CACHE) > _MAX_ENTRIES:
        # Drop half the oldest — simple FIFO is fine at this size.
        oldest_keys = list(_CACHE.keys())[: len(_CACHE) // 2]
        for k in oldest_keys:
            _CACHE.pop(k, None)


def cache_clear() -> None:
    """Wipe the entire cache. Used by tests."""
    _CACHE.clear()
