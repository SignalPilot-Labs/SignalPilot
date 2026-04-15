"""Audit data model and storage layer for Spider2 benchmark runs.

Manages run-level metadata, per-task result records, and immutable storage
to the audit directory. Designed for leaderboard submission compliance.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import AUDIT_BASE

_log = logging.getLogger(__name__)


class ResultAlreadyExistsError(Exception):
    """Raised when attempting to overwrite an existing task result (immutability gate)."""


@dataclasses.dataclass
class RunMetadata:
    run_id: str
    suite: str
    model: str
    model_version: str
    started_at: str
    finished_at: str | None
    concurrency: int
    total_tasks: int
    passed_tasks: int
    task_ids: list[str]


@dataclasses.dataclass
class TaskResult:
    instance_id: str
    run_id: str
    suite: str
    passed: bool
    elapsed_seconds: float
    turns: int
    tool_call_count: int
    cost_usd: float | None
    usage: dict[str, Any] | None
    model: str
    error: str | None
    timestamps: dict[str, float]
    agent_transcript_path: str


def _run_dir(run_id: str) -> Path:
    return AUDIT_BASE / "runs" / run_id


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_run(
    suite: str,
    model: str,
    concurrency: int,
    task_ids: list[str],
) -> RunMetadata:
    """Create the audit directory tree and write initial run_metadata.json.

    Fails fast with a clear error if the directory is not writable.
    """
    run_id = str(uuid.uuid4())
    run_dir = _run_dir(run_id)

    try:
        for subdir in ("tasks", "traces", "queries", "projects"):
            (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"Cannot create audit directory '{run_dir}': {e}. "
            "Ensure BENCHMARK_AUDIT_DIR is writable or mount the sp-benchmark-audit volume."
        ) from e

    metadata = RunMetadata(
        run_id=run_id,
        suite=suite,
        model=model,
        model_version=model,
        started_at=_iso_now(),
        finished_at=None,
        concurrency=concurrency,
        total_tasks=len(task_ids),
        passed_tasks=0,
        task_ids=task_ids,
    )
    _write_run_metadata(run_dir, metadata)
    return metadata


def _write_run_metadata(run_dir: Path, metadata: RunMetadata) -> None:
    data = dataclasses.asdict(metadata)
    (run_dir / "run_metadata.json").write_text(json.dumps(data, indent=2))


def save_task_result(result: TaskResult) -> None:
    """Write a TaskResult to disk. Raises ResultAlreadyExistsError if file exists."""
    result_path = _run_dir(result.run_id) / "tasks" / f"{result.instance_id}.json"
    if result_path.exists():
        raise ResultAlreadyExistsError(
            f"Task result already exists for '{result.instance_id}' in run '{result.run_id}'. "
            "Use a new run_id or skip this task (resume mode)."
        )
    result_path.write_text(json.dumps(dataclasses.asdict(result), indent=2))


def save_task_transcript(run_id: str, instance_id: str, transcript: dict[str, Any]) -> None:
    """Write the full conversation transcript (messages, tool calls, timestamps)."""
    trace_path = _run_dir(run_id) / "traces" / f"{instance_id}.json"
    trace_path.write_text(json.dumps(transcript, indent=2))


def finalize_run(run_id: str, passed_count: int) -> None:
    """Update run_metadata.json with finished_at and passed_tasks."""
    run_dir = _run_dir(run_id)
    metadata_path = run_dir / "run_metadata.json"
    data = json.loads(metadata_path.read_text())
    data["finished_at"] = _iso_now()
    data["passed_tasks"] = passed_count
    metadata_path.write_text(json.dumps(data, indent=2))


def copy_gateway_audit(run_id: str, instance_id: str, connection_name: str) -> None:
    """Copy gateway audit entries for a specific connection to the run's queries dir.

    Reads ~/.signalpilot/audit.jsonl and filters by connection_name (NOT instance_id
    — in parallel mode these differ due to the run_id prefix). Writes filtered
    entries to AUDIT_BASE/runs/{run_id}/queries/{instance_id}.jsonl.
    """
    audit_source = Path.home() / ".signalpilot" / "audit.jsonl"
    if not audit_source.exists():
        return

    dest_path = _run_dir(run_id) / "queries" / f"{instance_id}.jsonl"
    matching_lines: list[str] = []

    with open(audit_source) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("connection_name") == connection_name:
                    matching_lines.append(line)
            except json.JSONDecodeError:
                continue

    dest_path.write_text("\n".join(matching_lines) + ("\n" if matching_lines else ""))


def archive_workdir(run_id: str, instance_id: str, work_dir: Path) -> Path | None:
    """Copy the agent's workdir to the audit volume for post-run evaluation.

    Copies the full project (SQL models, DuckDB output, dbt_project.yml, etc.)
    to AUDIT_BASE/runs/{run_id}/projects/{instance_id}/. Without this, the
    work products are lost when Docker containers stop.

    Skips files that are unlikely to matter for submission/re-evaluation:
    - dbt_packages/ (large, deterministic from packages.yml)
    - .dbt/ (internal dbt state)
    - __pycache__/

    Returns the destination path, or None if the copy failed.
    """
    if not work_dir.exists():
        return None

    dest = _run_dir(run_id) / "projects" / instance_id
    skip_dirs = {"dbt_packages", ".dbt", "__pycache__", "node_modules", "target"}

    def _ignore(directory: str, contents: list[str]) -> set[str]:
        return {c for c in contents if c in skip_dirs}

    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(work_dir, dest, ignore=_ignore)
        return dest
    except Exception:
        return None


def save_single_task_run(
    instance_id: str,
    suite: str,
    model: str,
    passed: bool,
    elapsed_seconds: float,
    work_dir: Path,
    agent_output: dict[str, Any] | None = None,
) -> str:
    """All-in-one audit saver for individual task runs (not run_batch).

    Creates a single-task run directory with all audit artifacts:
    run_metadata, task result, transcript, gateway queries, and project archive.

    Returns the run_id so callers can log it.
    """
    run_id = f"single-{instance_id}-{int(time.time())}"
    run_dir = _run_dir(run_id)

    try:
        for subdir in ("tasks", "traces", "queries", "projects"):
            (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _log.warning("Cannot create audit dir '%s': %s", run_dir, e)
        return run_id

    now = _iso_now()

    if agent_output is None:
        # Try loading from workdir
        ao_path = work_dir / "agent_output.json"
        if ao_path.exists():
            try:
                agent_output = json.loads(ao_path.read_text())
            except Exception:
                agent_output = {}
        else:
            agent_output = {}

    # run_metadata.json
    metadata = RunMetadata(
        run_id=run_id,
        suite=suite,
        model=model,
        model_version=model,
        started_at=agent_output.get("started_at", now),
        finished_at=now,
        concurrency=0,
        total_tasks=1,
        passed_tasks=1 if passed else 0,
        task_ids=[instance_id],
    )
    _write_run_metadata(run_dir, metadata)

    # tasks/{id}.json
    result = TaskResult(
        instance_id=instance_id,
        run_id=run_id,
        suite=suite,
        passed=passed,
        elapsed_seconds=elapsed_seconds,
        turns=agent_output.get("turns", 0),
        tool_call_count=len(agent_output.get("tool_calls", [])),
        cost_usd=agent_output.get("cost_usd"),
        usage=agent_output.get("usage"),
        model=model,
        error=None,
        timestamps={"total": elapsed_seconds},
        agent_transcript_path=f"traces/{instance_id}.json",
    )
    try:
        save_task_result(result)
    except ResultAlreadyExistsError:
        pass

    # traces/{id}.json
    try:
        save_task_transcript(run_id, instance_id, {
            "transcript": agent_output.get("transcript", []),
            "tool_calls": agent_output.get("tool_calls", []),
            "messages": agent_output.get("messages", []),
            "turns": agent_output.get("turns", 0),
            "started_at": agent_output.get("started_at", ""),
        })
    except Exception as e:
        _log.warning("Failed to save transcript: %s", e)

    # queries/{id}.jsonl
    try:
        copy_gateway_audit(run_id, instance_id, connection_name=instance_id)
    except Exception as e:
        _log.warning("Failed to copy gateway audit: %s", e)

    # projects/{id}/
    try:
        archive_workdir(run_id, instance_id, work_dir)
    except Exception as e:
        _log.warning("Failed to archive workdir: %s", e)

    return run_id
