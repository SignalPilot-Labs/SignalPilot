"""The dashboard dataset snapshot convention, shared by the sandbox SDK
(the only writer) and the dashboard check tools (the readers).

A dashboard dataset is defined by its SQL. The snapshot is the cached
result of that SQL at ``artifacts/datasets/<name>.csv`` in the chat scratch
directory. A sidecar at ``<scratch>/.dashboard-datasets/<name>.json``
records which connection and SQL produced the snapshot, so a check tool can
tell when the dashboard file and the snapshot no longer agree. The dot
directory keeps the sidecar out of the artifact sweep.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

DATASET_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
SNAPSHOT_DIRECTORY = "artifacts/datasets"
SIDECAR_DIRECTORY = ".dashboard-datasets"

_DATASET_NAME_RE = re.compile(DATASET_NAME_PATTERN)
_WHITESPACE_RE = re.compile(r"\s+")


def is_dataset_name(name: object) -> bool:
    return isinstance(name, str) and _DATASET_NAME_RE.match(name) is not None


def normalized_sql(sql: str) -> str:
    """Strip surrounding whitespace and collapse internal runs to one space."""
    return _WHITESPACE_RE.sub(" ", str(sql or "").strip())


def normalized_sql_hash(sql: str) -> str:
    """SHA-256 hex digest of the normalized SQL text."""
    return hashlib.sha256(normalized_sql(sql).encode("utf-8")).hexdigest()


def snapshot_path(name: str) -> str:
    """Scratch-relative POSIX path of a dataset snapshot."""
    return f"{SNAPSHOT_DIRECTORY}/{name}.csv"


def sidecar_path(scratch_directory: Path, name: str) -> Path:
    """Absolute path of the sidecar that records a snapshot's origin."""
    return scratch_directory / SIDECAR_DIRECTORY / f"{name}.json"
