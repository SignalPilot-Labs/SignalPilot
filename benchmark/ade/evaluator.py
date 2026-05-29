"""ADE-bench evaluation: inject tests, run dbt seed + dbt test, parse results.

Matches the official ADE-bench evaluation methodology:
1. Wipe project's tests/ directory and replace with harness tests
2. Copy solution seeds and equality macro
3. Run test_setup commands (e.g., dbt run --full-refresh)
4. Run dbt seed (loads solution CSVs with correct column types)
5. Run dbt test --select "test_type:singular"
6. All tests must pass for the task to pass
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import yaml

from ..core.logging import log


def _force_rmtree(path: Path) -> None:
    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    if path.exists():
        shutil.rmtree(path, onerror=on_error)


def _inject_seeds(work_dir: Path, task: dict) -> None:
    """Inject solution seed CSVs and merge column type schema at eval time.

    Seeds are injected AFTER the agent finishes, matching official ADE-bench flow.
    The agent never sees solution data during its work.
    """
    if not task.get("seeds_dir") or not task["seeds_dir"].exists():
        return

    seeds_dst = work_dir / "seeds"
    seeds_dst.mkdir(exist_ok=True)

    no_op_path = None
    seed_count = 0
    for f in task["seeds_dir"].iterdir():
        if f.name == "_no-op.txt":
            no_op_path = f
            continue
        if f.is_file():
            shutil.copy2(f, seeds_dst / f.name)
            seed_count += 1

    if seed_count:
        log(f"[eval] Injected {seed_count} seed files")

    # Merge column type overrides from _no-op.txt into dbt_project.yml
    if no_op_path:
        try:
            seed_schema = yaml.safe_load(no_op_path.read_text())
            if seed_schema and "seeds" in seed_schema:
                dbt_project_path = work_dir / "dbt_project.yml"
                if dbt_project_path.exists():
                    project_config = yaml.safe_load(dbt_project_path.read_text()) or {}
                    if "seeds" not in project_config:
                        project_config["seeds"] = {}
                    for proj_name, seed_configs in seed_schema["seeds"].items():
                        if proj_name not in project_config["seeds"]:
                            project_config["seeds"][proj_name] = {}
                        for seed_name, settings in seed_configs.items():
                            project_config["seeds"][proj_name][seed_name] = settings
                    dbt_project_path.write_text(
                        yaml.dump(project_config, default_flow_style=False, sort_keys=False)
                    )
                    log("[eval] Merged seed schema from _no-op.txt")
        except Exception as e:
            log(f"[eval] Failed to merge seed schema: {e}", "WARN")


def _should_include_test(test_path: Path, db_type: str = "duckdb") -> bool:
    """Check if a test file should be included based on its db annotation.

    Official ADE-bench filters tests by '-- db: <type>' annotation in the first line.
    Tests with no annotation are always included.
    Tests annotated for a different db_type are excluded.
    """
    try:
        first_line = test_path.read_text().split("\n", 1)[0].strip()
        if first_line.startswith("-- db:"):
            test_db = first_line.replace("-- db:", "").strip().lower()
            return test_db == db_type.lower()
    except Exception:
        pass
    return True  # No annotation = always include


def _inject_tests(work_dir: Path, task: dict) -> int:
    """Wipe tests/ and replace with harness evaluation tests.

    This matches the official ADE-bench behavior (run-dbt-test.sh lines 12-13):
    rm -rf tests && mkdir tests — only evaluation tests run, not project tests.

    Tests annotated with '-- db: snowflake' are excluded for DuckDB runs (and vice versa).

    Returns the expected test count.
    """
    tests_dir = work_dir / "tests"
    _force_rmtree(tests_dir)
    tests_dir.mkdir(exist_ok=True)

    test_count = 0
    skipped = 0

    # Copy task test files, filtering by db_type
    if task.get("tests_dir") and task["tests_dir"].exists():
        for f in task["tests_dir"].iterdir():
            if f.is_file():
                if _should_include_test(f, db_type="duckdb"):
                    shutil.copy2(f, tests_dir / f.name)
                    test_count += 1
                else:
                    skipped += 1

    msg = f"[eval] Injected {test_count} test files"
    if skipped:
        msg += f" (skipped {skipped} non-duckdb tests)"
    log(msg)
    return test_count


def evaluate_ade_task(work_dir: Path, task: dict) -> tuple[bool, str]:
    """Evaluate an ADE-bench task using the official methodology.

    Returns (passed: bool, details: str).
    """
    dbt_bin = shutil.which("dbt") or "dbt"
    task_id = task["task_id"]
    test_setup = task.get("test_setup", "")


    # Step 1: Inject seeds, seed schema, and harness tests
    _inject_seeds(work_dir, task)
    expected_tests = _inject_tests(work_dir, task)

    # Step 2: Copy task setup files to /tmp/ (for test_setup scripts that reference them)
    # Adapt /app/<name>.duckdb paths in Python scripts to the actual local path
    db_files = list(work_dir.glob("*.duckdb"))
    db_path_str = str(db_files[0]) if db_files else ""

    work_dir_str = str(work_dir)

    if task.get("setup_dir") and task["setup_dir"].exists():
        for f in task["setup_dir"].iterdir():
            if f.is_file():
                dst_file = Path("/tmp") / f.name
                if f.suffix in (".py", ".sh", ".sql"):
                    content = f.read_text(errors="replace")
                    # Replace /app/<name>.duckdb with local DB path
                    for db_file in db_files:
                        content = content.replace(f"/app/{db_file.name}", db_path_str)
                    # Replace /app (Docker workdir) with actual work_dir
                    # Use quoted path first to catch '/app' strings, then bare path
                    content = content.replace('"/app"', f'"{work_dir_str}"')
                    content = content.replace("'/app'", f"'{work_dir_str}'")
                    content = content.replace('"/app/', f'"{work_dir_str}/')
                    content = content.replace("'/app/", f"'{work_dir_str}/")
                    dst_file.write_text(content)
                else:
                    shutil.copy2(f, dst_file)
        # Also copy subdirectories (e.g., broken/)
        for d in task["setup_dir"].iterdir():
            if d.is_dir():
                dst_dir = Path("/tmp") / d.name
                if dst_dir.exists():
                    _force_rmtree(dst_dir)
                shutil.copytree(d, dst_dir)
        log(f"[eval] Copied setup files to /tmp/ (paths adapted)")

    # Step 3: Run test_setup as a single bash script (not line-by-line)
    # This handles multi-line Python heredocs, compound commands, etc.
    if test_setup:
        # Adapt Docker container paths to local paths (same as workdir.py setup.sh)
        adapted_setup = test_setup
        if db_path_str:
            for db_file in db_files:
                adapted_setup = adapted_setup.replace(f"/app/{db_file.name}", db_path_str)
        adapted_setup = adapted_setup.replace("/app/setup/", "_ade_setup/")
        adapted_setup = adapted_setup.replace("/sage/solutions/", "_ade_setup/")
        # Replace /app Docker workdir with actual work_dir in inline Python
        adapted_setup = adapted_setup.replace("'/app'", f"'{work_dir_str}'")
        adapted_setup = adapted_setup.replace("'/app/", f"'{work_dir_str}/")

        test_setup_script = work_dir / "_test_setup.sh"
        test_setup_script.write_text(f"#!/bin/bash\nset -e\n{adapted_setup}\n")
        log(f"[eval] Running test_setup script")
        result = subprocess.run(
            ["bash", str(test_setup_script)],
            cwd=str(work_dir), capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            log(f"[eval] test_setup warning: {result.stderr[-300:]}", "WARN")
        test_setup_script.unlink(missing_ok=True)

    # Step 4: Run dbt seed (loads solution CSVs into DuckDB)
    log(f"[eval] Running dbt seed for {task_id}")
    seed_result = subprocess.run(
        [dbt_bin, "seed"],
        cwd=str(work_dir), capture_output=True, text=True, timeout=120,
    )
    if seed_result.returncode != 0:
        detail = f"dbt seed FAILED: {seed_result.stderr[-500:]}"
        log(f"[eval] {detail}", "ERROR")
        return False, detail

    # Step 5: Run dbt test --select "test_type:singular"
    # This matches official behavior: only run singular tests, not schema/generic tests
    log(f"[eval] Running dbt test for {task_id}")
    test_result = subprocess.run(
        [dbt_bin, "test", "--select", "test_type:singular"],
        cwd=str(work_dir), capture_output=True, text=True, timeout=120,
    )

    output = test_result.stdout + test_result.stderr
    passed = test_result.returncode == 0

    # Parse run_results.json for detailed info
    run_results_path = work_dir / "target" / "run_results.json"
    test_summary = ""
    tests_ran = 0
    if run_results_path.exists():
        try:
            results = json.loads(run_results_path.read_text())
            total = len(results.get("results", []))
            tests_ran = total
            passes = sum(
                1 for r in results.get("results", [])
                if r.get("status") == "pass"
            )
            failures = [
                r.get("unique_id", "unknown").split(".")[-1]
                for r in results.get("results", [])
                if r.get("status") != "pass"
            ]
            test_summary = f"Tests: {passes}/{total} passed"
            if failures:
                test_summary += f" | Failed: {', '.join(failures)}"
        except Exception:
            test_summary = "Could not parse run_results.json"
    else:
        test_summary = _parse_dbt_test_output(output)

    # Fail if no tests ran when tests were expected
    if expected_tests > 0 and tests_ran == 0:
        log(f"[eval] FAIL: Expected {expected_tests} tests but 0 ran", "ERROR")
        passed = False
        test_summary = f"Tests: 0/{expected_tests} — no tests executed"
    elif expected_tests > 0 and tests_ran < expected_tests:
        log(f"[eval] WARNING: Expected {expected_tests} tests but only {tests_ran} ran", "WARN")

    detail = f"{'PASS' if passed else 'FAIL'} - {test_summary}"
    log(f"[eval] {task_id}: {detail}")

    return passed, detail


def _parse_dbt_test_output(output: str) -> str:
    """Parse dbt test stdout for pass/fail summary."""
    lines = output.splitlines()
    for line in reversed(lines):
        if "Pass" in line and "Fail" in line:
            return line.strip()
        if "Done." in line:
            return line.strip()
    return "dbt test completed"
