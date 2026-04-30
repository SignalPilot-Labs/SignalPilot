"""Local database path validation."""

from __future__ import annotations

from pathlib import Path

import gateway.store._constants as _constants


def _validate_local_db_path(path: str) -> str:
    """Validate that a DuckDB/SQLite path is within DATA_DIR.

    Allowed special values:
      - ":memory:"       — in-memory database
      - paths starting with "md:" — MotherDuck cloud connection

    All other paths are resolved to an absolute canonical form and must fall
    within DATA_DIR. Using Path.resolve() canonicalizes ".." traversal and
    symlinks.

    Note: TOCTOU risk — a symlink could be created after validation but before
    DuckDB opens the file. Accepted risk: the attacker would need write access
    within DATA_DIR to exploit this.

    Raises:
        ValueError: if the resolved path is not within DATA_DIR.
    """
    if path == ":memory:" or path.startswith("md:"):
        return path

    resolved = Path(path).resolve()
    allowed_base = _constants.DATA_DIR.resolve()

    try:
        resolved.relative_to(allowed_base)
        return path
    except ValueError:
        raise ValueError(f"Database path not allowed: must be within the data directory ({_constants.DATA_DIR})")
