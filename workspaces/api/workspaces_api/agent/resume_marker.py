"""Atomic approval resume-marker writer.

This module writes a per-approval JSON marker file into a running agent's
workdir so the sandboxed agent can detect and act on an approval decision.

Design:
- The marker is a cooperative IPC channel, NOT an audit record.
  The DB approval row is the source of truth; the marker file is best-effort.
  Failures to write the marker MUST NOT block the API response.
- Caller decides correlation_id, error logging, and event emission.
  This module has no I/O besides the target filesystem.
- `decision` vocabulary: past-tense "approved" / "rejected" (matches
  Approval.decision on the DB row — both use the same vocabulary by design).
- Atomic write: NamedTemporaryFile in same dir → flush → fsync → os.replace.
  fsync ensures the file is fully populated before the rename is visible to
  the agent's filesystem watcher.

NOTE (R7): The API process currently runs as the same UID as the sandbox
subprocess. When gvisor isolation arrives (R7), an explicit chown will be
needed after os.replace so the sandbox user can read the marker file.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

_RESUME_DIR = Path(".signalpilot") / "resume"
_DIR_MODE = 0o700
_FILE_MODE = 0o600


def write_approval_marker(
    *,
    workdir_root: Path,
    run_id: uuid.UUID,
    approval_id: uuid.UUID,
    decision: Literal["approved", "rejected"],
    decided_at: datetime,
    comment: str | None,
) -> Path:
    """Atomically write {workdir_root}/{run_id}/home/.signalpilot/resume/{approval_id}.json.

    Creates the .signalpilot/resume directory with mode 0o700 if missing.
    Writes via NamedTemporaryFile in the same directory + os.replace().
    Returns the final path. Raises OSError on filesystem failure.

    `decision` MUST be the same past-tense vocabulary stored on Approval.decision
    ("approved" or "rejected") — DB column and on-disk marker agree by design.

    This is a cooperative IPC channel, NOT an audit record. The DB approval row
    is the source of truth. Callers MUST NOT raise on OSError from this function;
    they should emit a run.approval_marker_failed event instead.
    """
    resume_dir = workdir_root / str(run_id) / "home" / _RESUME_DIR
    resume_dir.mkdir(parents=True, mode=_DIR_MODE, exist_ok=True)

    final_path = resume_dir / f"{approval_id}.json"
    payload = {
        "approval_id": str(approval_id),
        "decision": decision,
        "decided_at": decided_at.isoformat(),
        "comment": comment,
    }
    payload_bytes = json.dumps(payload).encode()

    fd, tmp_path_str = tempfile.mkstemp(dir=resume_dir)
    try:
        os.write(fd, payload_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)

    os.replace(tmp_path_str, final_path)
    os.chmod(final_path, _FILE_MODE)

    return final_path
