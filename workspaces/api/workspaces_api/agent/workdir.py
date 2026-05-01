"""Per-run working directory management for the Workspaces API.

Layout created by prepare_run_workdir:

    {root}/{run_id}/
        home/
            .claude/
                CLAUDE.md          ← per-run rendered instructions
                CLAUDE_static.md   ← verbatim copy of workspaces/agent/CLAUDE.md
            .signalpilot/
                resume/            ← approval resume-marker dir (mode 0o700)

Directory mode is 0o700 (owner-only). Cleanup is idempotent (safe for missing dir).
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_CLAUDE_DIR = Path(".claude")
_CLAUDE_MD_NAME = "CLAUDE.md"
_CLAUDE_STATIC_MD_NAME = "CLAUDE_static.md"
_RESUME_DIR = Path(".signalpilot") / "resume"
_DIR_MODE = 0o700


def prepare_resume_dir(run_root: Path) -> Path:
    """Create the resume-marker directory for a run.

    Creates {run_root}/home/.signalpilot/resume with mode 0o700.
    Called from prepare_run_workdir so the bind-mount target exists before spawn.

    Returns the created path.
    """
    resume_dir = run_root / "home" / _RESUME_DIR
    resume_dir.mkdir(parents=True, mode=_DIR_MODE, exist_ok=True)
    return resume_dir


def prepare_run_workdir(
    root: Path,
    run_id: uuid.UUID,
    claude_md_text: str,
    static_md_text: str,
) -> Path:
    """Create a per-run working directory with agent instruction files.

    Args:
        root: Root directory under which per-run dirs are created.
        run_id: UUID of the run — used as directory name.
        claude_md_text: Rendered per-run CLAUDE.md content.
        static_md_text: Verbatim content of workspaces/agent/CLAUDE.md.

    Returns:
        Path to the run root directory ({root}/{run_id}).

    Raises:
        OSError: If directory creation or file write fails.
    """
    run_dir = root / str(run_id)
    claude_dir = run_dir / "home" / _CLAUDE_DIR

    claude_dir.mkdir(parents=True, mode=_DIR_MODE, exist_ok=False)

    # Restrict permissions on all ancestor directories we just created
    for ancestor in (run_dir, run_dir / "home"):
        ancestor.chmod(_DIR_MODE)

    (claude_dir / _CLAUDE_MD_NAME).write_text(claude_md_text, encoding="utf-8")
    (claude_dir / _CLAUDE_STATIC_MD_NAME).write_text(static_md_text, encoding="utf-8")

    prepare_resume_dir(run_dir)

    logger.debug("workdir created run_id=%s path=%s", run_id, run_dir)
    return run_dir


def cleanup_run_workdir(path: Path) -> None:
    """Recursively remove a per-run working directory.

    Idempotent — silently succeeds if the path does not exist.
    """
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=False)
    logger.debug("workdir cleaned run_id=%s path=%s", path.name, path)
