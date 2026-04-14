"""Submission archive builder for Spider2 leaderboard submission.

Collects audit data from a completed benchmark run and packages it into
a compressed tar.gz archive for submission.

Usage:
    python -m benchmark.package_submission --run-id <run_id>
    python -m benchmark.package_submission --audit-dir /data/benchmark-audit --run-id <run_id>
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import tarfile
from pathlib import Path

from .core.audit import TaskResult
from .core.paths import AUDIT_BASE

_TASK_RESULT_FIELDS = {f.name for f in dataclasses.fields(TaskResult)}


def _load_run_metadata(run_dir: Path) -> dict:
    """Load and return run_metadata.json. Fails if not found."""
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"run_metadata.json not found at '{metadata_path}'. "
            "Ensure the run_id is correct and the run has been initialized."
        )
    return json.loads(metadata_path.read_text())


def _load_task_results(tasks_dir: Path) -> tuple[list[dict], list[str]]:
    """Load all task result JSON files. Returns (valid_results, skipped_ids).

    Validates each file against TaskResult fields. Warns and skips corrupt files.
    """
    valid: list[dict] = []
    skipped: list[str] = []

    for result_file in sorted(tasks_dir.glob("*.json")):
        try:
            data = json.loads(result_file.read_text())
        except json.JSONDecodeError as e:
            print(f"WARN: Skipping corrupt JSON in '{result_file.name}': {e}", file=sys.stderr)
            skipped.append(result_file.stem)
            continue

        missing_fields = _TASK_RESULT_FIELDS - set(data.keys())
        if missing_fields:
            print(
                f"WARN: Skipping '{result_file.name}' — missing fields: {sorted(missing_fields)}",
                file=sys.stderr,
            )
            skipped.append(result_file.stem)
            continue

        valid.append(data)

    return valid, skipped


def _validate_completeness(metadata: dict, valid_results: list[dict], skipped: list[str]) -> None:
    """Raise an error if any expected task_ids are missing results."""
    expected_ids = set(metadata.get("task_ids", []))
    result_ids = {r["instance_id"] for r in valid_results}
    missing = expected_ids - result_ids - set(skipped)
    if missing:
        raise RuntimeError(
            f"Incomplete run: {len(missing)} task(s) have no result file:\n"
            + "\n".join(f"  {t}" for t in sorted(missing))
        )


def _build_scores(valid_results: list[dict]) -> dict[str, dict]:
    """Build scores summary: {instance_id: {passed, elapsed}}."""
    return {
        r["instance_id"]: {"passed": r["passed"], "elapsed": r["elapsed_seconds"]}
        for r in valid_results
    }


def _build_archive(run_id: str, run_dir: Path, audit_base: Path) -> Path:
    """Assemble submission_{run_id}.tar.gz in audit_base/submissions/."""
    submissions_dir = audit_base / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)

    archive_path = submissions_dir / f"submission_{run_id}.tar.gz"
    archive_root = f"submission_{run_id}"

    metadata = _load_run_metadata(run_dir)
    tasks_dir = run_dir / "tasks"
    valid_results, skipped = _load_task_results(tasks_dir)
    _validate_completeness(metadata, valid_results, skipped)
    scores = _build_scores(valid_results)

    with tarfile.open(archive_path, "w:gz") as tar:
        # run_metadata.json
        _add_bytes_to_tar(
            tar,
            f"{archive_root}/run_metadata.json",
            json.dumps(metadata, indent=2).encode(),
        )

        # scores.json
        _add_bytes_to_tar(
            tar,
            f"{archive_root}/scores.json",
            json.dumps(scores, indent=2).encode(),
        )

        # results/{instance_id}.json
        for result in valid_results:
            _add_bytes_to_tar(
                tar,
                f"{archive_root}/results/{result['instance_id']}.json",
                json.dumps(result, indent=2).encode(),
            )

        # traces/{instance_id}.json
        traces_dir = run_dir / "traces"
        for trace_file in sorted(traces_dir.glob("*.json")):
            tar.add(trace_file, arcname=f"{archive_root}/traces/{trace_file.name}")

        # queries/{instance_id}.jsonl
        queries_dir = run_dir / "queries"
        for query_file in sorted(queries_dir.glob("*.jsonl")):
            tar.add(query_file, arcname=f"{archive_root}/queries/{query_file.name}")

        # projects/{instance_id}/ — agent-generated work products (SQL models, DuckDB, etc.)
        projects_dir = run_dir / "projects"
        if projects_dir.exists():
            for project_dir in sorted(projects_dir.iterdir()):
                if project_dir.is_dir():
                    tar.add(project_dir, arcname=f"{archive_root}/projects/{project_dir.name}")

        # logs/{instance_id}.log — per-task console logs
        logs_dir = run_dir / "logs"
        if logs_dir.exists():
            for log_file in sorted(logs_dir.glob("*.log")):
                tar.add(log_file, arcname=f"{archive_root}/logs/{log_file.name}")

    return archive_path


def _add_bytes_to_tar(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    """Add raw bytes to a tarfile under the given archive path."""
    import io
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a benchmark run for leaderboard submission")
    parser.add_argument("--run-id", required=True, help="The run ID to package")
    parser.add_argument(
        "--audit-dir",
        default=None,
        help=f"Override audit base directory (default: {AUDIT_BASE})",
    )
    args = parser.parse_args()

    audit_base = Path(args.audit_dir) if args.audit_dir else AUDIT_BASE
    run_id: str = args.run_id
    run_dir = audit_base / "runs" / run_id

    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Packaging run '{run_id}' from '{run_dir}'...")

    try:
        archive_path = _build_archive(run_id, run_dir, audit_base)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Load metadata for summary
    metadata = _load_run_metadata(run_dir)
    tasks_dir = run_dir / "tasks"
    valid_results, _ = _load_task_results(tasks_dir)
    total = len(valid_results)
    passed = sum(1 for r in valid_results if r["passed"])
    pass_rate = (100.0 * passed / total) if total else 0.0
    archive_size_mb = archive_path.stat().st_size / (1024 * 1024)

    print("\nSubmission package created:")
    print(f"  Total tasks:  {total}")
    print(f"  Pass rate:    {passed}/{total} ({pass_rate:.1f}%)")
    print(f"  Archive path: {archive_path}")
    print(f"  Archive size: {archive_size_mb:.2f} MB")
    print(f"  Suite:        {metadata.get('suite', 'unknown')}")
    print(f"  Model:        {metadata.get('model', 'unknown')}")


if __name__ == "__main__":
    main()
