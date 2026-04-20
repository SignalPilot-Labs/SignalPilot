"""Validation script for benchmark suites.

Run as:
    python -m benchmark.validate_bench --suite spider2-lite
    python -m benchmark.validate_bench --suite spider2-snowflake
    python -m benchmark.validate_bench --suite spider2-dbt

Runs 6 checks and prints a colorized pass/fail summary.
Exits 0 if all checks pass (or skip), 1 if any check fails.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from .core.mcp import (
    delete_local_connection,
    load_mcp_servers,
    register_bigquery_connection,
    register_local_connection,
    register_snowflake_connection,
    register_sqlite_connection,
)
from .core.paths import (
    BIGQUERY_SA_FILE,
    GATEWAY_SRC,
    PROMPTS_DIR,
    SKILLS_SRC,
    SNOWFLAKE_ENV_FILE,
)
from .core.suite import BenchmarkSuite, get_suite_config
from .core.workdir import force_rmtree, prepare_sql_workdir, prepare_workdir

# ANSI color codes
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"

CheckResult = tuple[str, str, str]  # (name, status, detail)  status: PASS|FAIL|SKIP


def _get_gateway_connection(conn_id: str):
    """Look up a connection in the gateway store.

    gateway.store is not importable at module level because GATEWAY_SRC
    must be on sys.path first — added as a side effect by the register_*
    helpers in core/mcp.py. This helper defers the import until after
    registration has run.
    """
    sys.path.insert(0, str(GATEWAY_SRC))
    from gateway.store import get_connection  # noqa: PLC0415

    return get_connection(conn_id)


def _make_dbt_synthetic_task() -> dict:
    return {
        "instance_id": "validate_test_dbt",
        "instruction": "validation test — not a real task",
    }


def _make_sql_synthetic_task(suite: BenchmarkSuite) -> dict:
    if suite == BenchmarkSuite.SNOWFLAKE:
        return {
            "instance_id": "validate_test_sf",
            "instruction": "validation test — not a real task",
            "type": "snowflake",
            "db": "TEST_DB",
            "schema": "PUBLIC",
        }
    # LITE — use sqlite type (no file copy needed because db won't exist)
    return {
        "instance_id": "validate_test_lite",
        "instruction": "validation test — not a real task",
        "type": "sqlite",
        "db_id": "validate_test",
    }


def check_1_workdir(suite: BenchmarkSuite, config) -> CheckResult:
    """Check that workdir creation succeeds and has the expected structure."""
    name = "workdir_creation"
    work_dir: Path | None = None
    try:
        if suite == BenchmarkSuite.DBT:
            src_dir = config.data_dir / "examples"
            if not src_dir.exists():
                return (name, "SKIP", f"spider2-dbt examples dir not found: {src_dir}")
            # Use first available task
            task_dirs = [d for d in src_dir.iterdir() if d.is_dir()]
            if not task_dirs:
                return (name, "SKIP", "No task directories found in examples/")
            instance_id = task_dirs[0].name
            work_dir = prepare_workdir(instance_id)
        else:
            task = _make_sql_synthetic_task(suite)
            instance_id = task["instance_id"]
            work_dir = prepare_sql_workdir(instance_id, config, task)

        if not work_dir.exists():
            return (name, "FAIL", f"workdir not created: {work_dir}")

        mcp_json = work_dir / ".mcp.json"
        if not mcp_json.exists():
            return (name, "FAIL", f".mcp.json not found in workdir: {work_dir}")

        git_dir = work_dir / ".git"
        if not git_dir.exists():
            return (name, "FAIL", f"git repo not initialized in workdir: {work_dir}")

        return (name, "PASS", f"workdir OK: {work_dir}")

    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")
    finally:
        if work_dir is not None and work_dir.exists():
            try:
                force_rmtree(work_dir)
            except Exception:
                pass


def check_2_mcp_config() -> CheckResult:
    """Check that MCP config loads and has the signalpilot key."""
    name = "mcp_config"
    try:
        servers = load_mcp_servers()
        if "signalpilot" not in servers:
            return (name, "FAIL", f"'signalpilot' key missing from mcp config. Keys: {list(servers.keys())}")
        sp = servers["signalpilot"]
        if "command" not in sp:
            return (name, "FAIL", f"signalpilot config missing 'command' field: {sp}")
        if "args" not in sp:
            return (name, "FAIL", f"signalpilot config missing 'args' field: {sp}")
        return (name, "PASS", f"signalpilot command={sp['command']!r} args={sp['args']}")
    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")


def check_3_skills(suite: BenchmarkSuite, config) -> CheckResult:
    """Check that all suite skills exist as SKILL.md files in SKILLS_SRC."""
    name = "skills_discoverable"
    try:
        missing = []
        found = []
        for skill_name in config.skills:
            skill_md = SKILLS_SRC / skill_name / "SKILL.md"
            if skill_md.exists():
                found.append(skill_name)
            else:
                missing.append(skill_name)
        if missing:
            return (name, "FAIL", f"missing SKILL.md for: {missing}")
        return (name, "PASS", f"all {len(found)} skills present: {found}")
    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")


def check_4_system_prompt(suite: BenchmarkSuite) -> CheckResult:
    """Check that the appropriate system prompt exists and has correct content."""
    name = "system_prompt"
    try:
        if suite == BenchmarkSuite.DBT:
            prompt_file = PROMPTS_DIR / "dbt_local_system.md"
            if not prompt_file.exists():
                return (name, "FAIL", f"dbt system prompt not found: {prompt_file}")
            content = prompt_file.read_text()
            if "dbt" not in content.lower():
                return (name, "FAIL", "dbt_local_system.md does not mention 'dbt'")
            return (name, "PASS", f"dbt system prompt OK ({len(content)} chars)")
        else:
            prompt_file = PROMPTS_DIR / "system_general.md"
            if not prompt_file.exists():
                return (name, "FAIL", f"generalized system prompt not found: {prompt_file}")
            content = prompt_file.read_text()
            if not content.strip():
                return (name, "FAIL", "system_general.md is empty")
            # Check no hardcoded database names (template vars like ${connection_name} are OK)
            lower = content.lower()
            hardcoded = []
            # Look for standalone "dbt" not inside a template variable or mcp tool name
            # Allow "dbt" only in the "dbt tools" section header
            lines_with_dbt = [
                line.strip() for line in content.splitlines()
                if "dbt" in line.lower()
                and "${" not in line
                and "mcp__signalpilot__dbt" not in line.lower()
                and not line.strip().startswith("#")
                and not line.strip().startswith("-")
            ]
            if lines_with_dbt:
                hardcoded.append(f"dbt references outside tool names: {lines_with_dbt[:2]}")
            if "duckdb" in lower:
                hardcoded.append("contains hardcoded 'DuckDB'")
            if hardcoded:
                return (name, "FAIL", "; ".join(hardcoded))
            return (name, "PASS", f"system_general.md OK ({len(content)} chars)")
    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")


def check_5_connection(suite: BenchmarkSuite, config) -> CheckResult:
    """Check connection registration against the gateway store."""
    name = "connection_registration"
    registered_ids: list[str] = []
    try:
        if suite == BenchmarkSuite.DBT:
            conn_id = "validate_bench_dbt_test"
            with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
                tmp_path = f.name
            ok = register_local_connection(conn_id, tmp_path)
            if not ok:
                return (name, "FAIL", "DuckDB connection registration returned False")
            registered_ids.append(conn_id)
            conn = _get_gateway_connection(conn_id)
            if conn is None:
                return (name, "FAIL", f"connection '{conn_id}' not found in store after registration")
            return (name, "PASS", f"DuckDB connection registered and verified: {conn_id}")

        elif suite == BenchmarkSuite.SNOWFLAKE:
            if not SNOWFLAKE_ENV_FILE.exists():
                return (name, "SKIP", f"Snowflake credentials not found: {SNOWFLAKE_ENV_FILE}")
            conn_id = "validate_bench_sf_test"
            ok = register_snowflake_connection(conn_id, "TEST_DB", "PUBLIC")
            if not ok:
                return (name, "FAIL", "Snowflake connection registration returned False")
            registered_ids.append(conn_id)
            conn = _get_gateway_connection(conn_id)
            if conn is None:
                return (name, "FAIL", f"connection '{conn_id}' not found in store after registration")
            return (name, "PASS", f"Snowflake connection registered and verified: {conn_id}")

        else:  # LITE
            lite_results: list[str] = []
            skipped: list[str] = []

            # SQLite test (always run — no credential file needed)
            sqlite_id = "validate_bench_sqlite_test"
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
                tmp_sqlite = f.name
            ok = register_sqlite_connection(sqlite_id, tmp_sqlite)
            if not ok:
                return (name, "FAIL", "SQLite connection registration returned False")
            registered_ids.append(sqlite_id)
            conn = _get_gateway_connection(sqlite_id)
            if conn is None:
                return (name, "FAIL", f"SQLite connection '{sqlite_id}' not found in store")
            lite_results.append("sqlite OK")

            # Snowflake test (skip if no creds)
            if SNOWFLAKE_ENV_FILE.exists():
                sf_id = "validate_bench_sf_lite_test"
                ok = register_snowflake_connection(sf_id, "TEST_DB", "PUBLIC")
                if ok:
                    registered_ids.append(sf_id)
                    conn = _get_gateway_connection(sf_id)
                    if conn is None:
                        return (name, "FAIL", f"Snowflake connection '{sf_id}' not found in store")
                    lite_results.append("snowflake OK")
                else:
                    lite_results.append("snowflake FAIL (registration returned False)")
            else:
                skipped.append(f"snowflake SKIP (no {SNOWFLAKE_ENV_FILE.name})")

            # BigQuery test (skip if no service account)
            if BIGQUERY_SA_FILE.exists():
                bq_id = "validate_bench_bq_lite_test"
                ok = register_bigquery_connection(bq_id, "authacceptor", "")
                if ok:
                    registered_ids.append(bq_id)
                    conn = _get_gateway_connection(bq_id)
                    if conn is None:
                        return (name, "FAIL", f"BigQuery connection '{bq_id}' not found in store")
                    lite_results.append("bigquery OK")
                else:
                    lite_results.append("bigquery FAIL (registration returned False)")
            else:
                skipped.append(f"bigquery SKIP (no {BIGQUERY_SA_FILE.name})")

            detail = ", ".join(lite_results + skipped)
            has_failure = any("FAIL" in r for r in lite_results)
            if has_failure:
                return (name, "FAIL", detail)
            return (name, "PASS", detail)

    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")
    finally:
        for conn_id in registered_ids:
            delete_local_connection(conn_id)
        # Clean up temp files created for DuckDB/SQLite connection tests
        for var in ("tmp_path", "tmp_sqlite"):
            p = locals().get(var)
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def check_6_no_gold_leak(suite: BenchmarkSuite, config) -> CheckResult:
    """Check that no gold files appear in a freshly prepared workdir."""
    name = "no_gold_leak"
    work_dir: Path | None = None
    try:
        gold_dir: Path = config.gold_dir
        if not gold_dir.exists():
            return (name, "SKIP", f"gold dir not found (spider2 data not downloaded): {gold_dir}")

        # Collect gold filenames to look for
        gold_filenames: set[str] = set()
        for pattern in ("*.csv", "*.json", "*.sql"):
            for gf in gold_dir.glob(pattern):
                gold_filenames.add(gf.name)

        if not gold_filenames:
            return (name, "SKIP", "no gold files found to check against")

        # Prepare a fresh workdir
        if suite == BenchmarkSuite.DBT:
            src_dir = config.data_dir / "examples"
            if not src_dir.exists():
                return (name, "SKIP", f"spider2-dbt examples dir not found: {src_dir}")
            task_dirs = [d for d in src_dir.iterdir() if d.is_dir()]
            if not task_dirs:
                return (name, "SKIP", "no task directories found")
            work_dir = prepare_workdir(task_dirs[0].name)
        else:
            task = _make_sql_synthetic_task(suite)
            work_dir = prepare_sql_workdir(task["instance_id"], config, task)

        # Check if any gold filename exists in the workdir
        leaked: list[str] = []
        for fname in gold_filenames:
            if list(work_dir.rglob(fname)):
                leaked.append(fname)

        if leaked:
            return (name, "FAIL", f"gold files found in workdir: {leaked[:5]}")
        return (name, "PASS", f"no gold files leaked (checked {len(gold_filenames)} filenames)")

    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")
    finally:
        if work_dir is not None and work_dir.exists():
            try:
                force_rmtree(work_dir)
            except Exception:
                pass


def _print_summary(results: list[CheckResult]) -> None:
    print()
    print("=" * 60)
    print("  Benchmark Validation Summary")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for _, status, _ in results if status == "PASS")
    failed = sum(1 for _, status, _ in results if status == "FAIL")
    skipped = sum(1 for _, status, _ in results if status == "SKIP")

    for name, status, detail in results:
        if status == "PASS":
            color = _GREEN
            icon = "PASS"
        elif status == "FAIL":
            color = _RED
            icon = "FAIL"
        else:
            color = _YELLOW
            icon = "SKIP"
        print(f"  {color}[{icon}]{_RESET} {name}")
        print(f"         {detail}")

    print("-" * 60)
    print(
        f"  {_GREEN}{passed} passed{_RESET}  "
        f"{_RED}{failed} failed{_RESET}  "
        f"{_YELLOW}{skipped} skipped{_RESET}  "
        f"of {total} checks"
    )
    print("=" * 60)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate benchmark suite configuration without running the agent."
    )
    parser.add_argument(
        "--suite",
        required=True,
        choices=[s.value for s in BenchmarkSuite],
        help="Benchmark suite to validate",
    )
    args = parser.parse_args()

    suite = BenchmarkSuite(args.suite)
    config = get_suite_config(suite)

    print(f"\nValidating suite: {suite.value}")
    print(f"Data dir:         {config.data_dir}")
    print(f"Skills:           {config.skills}")

    results: list[CheckResult] = []

    for check_fn, check_args in [
        (check_1_workdir, (suite, config)),
        (check_2_mcp_config, ()),
        (check_3_skills, (suite, config)),
        (check_4_system_prompt, (suite,)),
        (check_5_connection, (suite, config)),
        (check_6_no_gold_leak, (suite, config)),
    ]:
        try:
            result = check_fn(*check_args)
        except Exception as exc:
            fn_name = getattr(check_fn, "__name__", "unknown")
            result = (fn_name, "FAIL", f"unexpected exception: {exc}")
        results.append(result)

    _print_summary(results)

    all_ok = all(status in ("PASS", "SKIP") for _, status, _ in results)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
