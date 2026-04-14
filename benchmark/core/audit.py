"""Audit log management for benchmark runs.

Each run gets its own directory under AUDIT_LOG_BASE containing:
  run.log          — tee'd copy of all log() output
  audit.json       — structured metadata record
  agent_output.json — copy of agent transcript (if produced)
  result.csv        — copy of result CSV (if produced)
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .logging import log, set_log_file

AUDIT_LOG_BASE = Path("/tmp/benchmark-audit-logs")


def create_audit_dir(instance_id: str) -> Path:
    """Create and return the per-run audit directory."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    audit_dir = AUDIT_LOG_BASE / f"{instance_id}_{timestamp}"
    audit_dir.mkdir(parents=True, exist_ok=True)
    log(f"Audit dir: {audit_dir}")
    return audit_dir


def setup_file_logger(audit_dir: Path) -> Path:
    """Open run.log in audit_dir and wire it into the log() tee. Returns log path."""
    log_path = audit_dir / "run.log"
    fh = log_path.open("w", encoding="utf-8")
    set_log_file(fh)
    return log_path


def save_audit_record(audit_dir: Path, record: dict) -> None:
    """Write the structured metadata dict to audit.json."""
    audit_path = audit_dir / "audit.json"
    audit_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")


def copy_agent_transcript(audit_dir: Path, work_dir: Path) -> None:
    """Copy agent_output.json from work_dir into audit_dir if it exists."""
    src = work_dir / "agent_output.json"
    if src.exists():
        shutil.copy2(src, audit_dir / "agent_output.json")


def copy_result_csv(audit_dir: Path, work_dir: Path) -> None:
    """Copy result.csv from work_dir into audit_dir if it exists."""
    src = work_dir / "result.csv"
    if src.exists():
        shutil.copy2(src, audit_dir / "result.csv")
