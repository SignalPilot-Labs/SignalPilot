"""
Spider2-DBT benchmark setup — downloads data, installs deps, builds missing gold DBs.

Usage:
    python -m benchmark.setup_dbt
    python -m benchmark.setup_dbt --spider2-dir ~/spider2-repo
    python -m benchmark.setup_dbt --build-gold          # rebuild gold DBs for tasks missing them
    python -m benchmark.setup_dbt --build-gold chinook001  # rebuild gold for specific task
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def check_deps():
    """Check and install required Python packages."""
    required = {
        "duckdb": "duckdb",
        "pandas": "pandas",
        "dbt": "dbt-duckdb",
        "dotenv": "python-dotenv",
        "claude_agent_sdk": "claude-agent-sdk",
    }
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("Done.")
    else:
        print("All Python deps installed.")


def check_spider2(spider2_dir: Path):
    """Check if Spider2 repo exists with dbt data."""
    dbt_dir = spider2_dir / "spider2-dbt"
    examples = dbt_dir / "examples"
    eval_jsonl = dbt_dir / "evaluation_suite" / "gold" / "spider2_eval.jsonl"

    if not dbt_dir.exists():
        print(f"\nSpider2 dbt directory not found at: {dbt_dir}")
        print("Clone Spider2 and download data:")
        print(f"  git clone https://github.com/xlang-ai/Spider2.git {spider2_dir}")
        print(f"  cd {dbt_dir}")
        print("  pip install gdown")
        print("  gdown 'https://drive.google.com/uc?id=1N3f7BSWC4foj-V-1C9n8M2XmgV7FOcqL'")
        print("  gdown 'https://drive.google.com/uc?id=1s0USV_iQLo4oe05QqAMnhGGp5jeejCzp'")
        print("  python setup.py")
        return False

    # Check if DuckDB files are extracted
    duckdb_count = len(list(examples.rglob("*.duckdb")))
    if duckdb_count == 0:
        print(f"\nNo DuckDB files found in {examples}")
        print(f"Run: cd {dbt_dir} && python setup.py")
        return False

    if not eval_jsonl.exists():
        print(f"\nEval config not found: {eval_jsonl}")
        return False

    # Count tasks
    with open(eval_jsonl) as f:
        task_count = sum(1 for _ in f)

    print(f"Spider2-DBT: {duckdb_count} DuckDB files, {task_count} eval tasks")
    return True


def audit_gold(spider2_dir: Path) -> list[dict]:
    """Audit gold data — find tasks with missing or incomplete gold DBs."""
    import duckdb

    gold_dir = spider2_dir / "spider2-dbt" / "evaluation_suite" / "gold"
    eval_jsonl = gold_dir / "spider2_eval.jsonl"

    with open(eval_jsonl) as f:
        entries = [json.loads(l) for l in f]

    issues = []
    for e in entries:
        iid = e["instance_id"]
        tabs = e["evaluation"]["parameters"].get("condition_tabs", [])
        db_file = e["evaluation"]["parameters"]["gold"]
        db_path = gold_dir / iid / db_file

        if not db_path.exists():
            issues.append({"instance_id": iid, "issue": "no_gold_db", "missing": [], "db_file": db_file})
            continue

        try:
            con = duckdb.connect(str(db_path), read_only=True)
            existing = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
            con.close()
            missing = [t for t in tabs if t not in existing]
            if missing:
                issues.append({"instance_id": iid, "issue": "missing_tables", "missing": missing, "db_file": db_file, "existing": existing})
        except Exception as ex:
            issues.append({"instance_id": iid, "issue": "error", "missing": [], "error": str(ex)})

    return issues


def build_gold_for_task(instance_id: str, spider2_dir: Path) -> bool:
    """Build gold DB for a task by running dbt on the example project.

    This copies the task's example project to a temp dir, runs dbt deps + dbt run,
    and copies the resulting DuckDB back as the gold DB.

    Only works if ALL SQL models already exist in the example (i.e., the task
    is fully solved in the example dir). For tasks where SQL is missing,
    you need to run the benchmark agent first and use --adopt-result.
    """
    examples_dir = spider2_dir / "spider2-dbt" / "examples"
    gold_dir = spider2_dir / "spider2-dbt" / "evaluation_suite" / "gold"

    src = examples_dir / instance_id
    if not src.exists():
        print(f"  [ERROR] Example not found: {src}")
        return False

    # Find DuckDB file
    duckdb_files = list(src.glob("*.duckdb"))
    if not duckdb_files:
        print(f"  [ERROR] No DuckDB file in {src}")
        return False

    db_filename = duckdb_files[0].name

    # Copy to temp dir
    import tempfile
    with tempfile.TemporaryDirectory(prefix=f"gold_{instance_id}_") as tmp:
        tmp_path = Path(tmp)
        shutil.copytree(src, tmp_path / instance_id)
        project = tmp_path / instance_id

        # Run dbt
        print(f"  Running dbt deps...")
        deps = subprocess.run(
            [sys.executable, "-m", "dbt", "deps"],
            cwd=str(project), capture_output=True, text=True, timeout=120,
        )

        print(f"  Running dbt run...")
        result = subprocess.run(
            [sys.executable, "-m", "dbt", "run"],
            cwd=str(project), capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            # Show error
            for line in (result.stdout + result.stderr).split("\n"):
                if "ERROR" in line or "FAIL" in line:
                    print(f"    {line.strip()}")
            print(f"  [WARN] dbt run failed — gold DB may be incomplete")
            # Continue anyway — some models may have been built

        # Copy result DB to gold dir
        result_db = project / db_filename
        gold_task_dir = gold_dir / instance_id
        gold_task_dir.mkdir(parents=True, exist_ok=True)
        gold_db = gold_task_dir / db_filename

        shutil.copy2(result_db, gold_db)
        print(f"  [OK] Gold DB written: {gold_db}")

        # Verify
        import duckdb as ddb
        con = ddb.connect(str(gold_db), read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        print(f"  Tables: {tables}")

        return result.returncode == 0


def adopt_result_as_gold(instance_id: str, spider2_dir: Path, result_dir: Path):
    """Copy a benchmark result DB as the gold standard for a task."""
    gold_dir = spider2_dir / "spider2-dbt" / "evaluation_suite" / "gold"
    eval_jsonl = gold_dir / "spider2_eval.jsonl"

    # Find the expected DB filename from eval config
    with open(eval_jsonl) as f:
        for line in f:
            e = json.loads(line)
            if e["instance_id"] == instance_id:
                db_file = e["evaluation"]["parameters"]["gold"]
                break
        else:
            print(f"  [ERROR] Task {instance_id} not found in eval config")
            return

    result_db = result_dir / db_file
    if not result_db.exists():
        print(f"  [ERROR] Result DB not found: {result_db}")
        return

    gold_task_dir = gold_dir / instance_id
    gold_task_dir.mkdir(parents=True, exist_ok=True)
    gold_db = gold_task_dir / db_file

    shutil.copy2(result_db, gold_db)
    print(f"  [OK] Adopted result as gold: {gold_db}")

    import duckdb as ddb
    con = ddb.connect(str(gold_db), read_only=True)
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    con.close()
    print(f"  Tables: {tables}")


def main():
    parser = argparse.ArgumentParser(description="Setup Spider2-DBT benchmark")
    parser.add_argument("--spider2-dir", type=Path,
                        default=Path(os.environ.get("SPIDER2_REPO_DIR", str(Path(__file__).resolve().parent.parent))))
    parser.add_argument("--build-gold", nargs="?", const="all", default=None,
                        help="Build missing gold DBs. Optionally specify instance_id.")
    parser.add_argument("--adopt-result", nargs=2, metavar=("INSTANCE_ID", "RESULT_DIR"),
                        help="Adopt a benchmark result as gold for a task")
    parser.add_argument("--audit", action="store_true", help="Audit gold data and report issues")
    args = parser.parse_args()

    print("=" * 60)
    print("Spider2-DBT Benchmark Setup")
    print("=" * 60)

    # 1. Check Python deps
    print("\n--- Python Dependencies ---")
    check_deps()

    # 2. Check Spider2 data
    print("\n--- Spider2 Data ---")
    if not check_spider2(args.spider2_dir):
        sys.exit(1)

    # 3. Check Claude Code auth
    print("\n--- Claude Code Auth ---")
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token:
        print(f"CLAUDE_CODE_OAUTH_TOKEN: set ({token[:15]}...)")
    else:
        print("CLAUDE_CODE_OAUTH_TOKEN: NOT SET")
        print("Add to .env: CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...")
        print("Get from: ~/.claude/.credentials.json -> claudeAiOauth.accessToken")

    # 4. Audit gold data
    print("\n--- Gold Data Audit ---")
    issues = audit_gold(args.spider2_dir)
    if not issues:
        print("All 68 gold DBs present and complete.")
    else:
        print(f"{len(issues)} tasks with gold data issues:")
        for iss in issues:
            if iss["issue"] == "no_gold_db":
                print(f"  {iss['instance_id']:30s} NO GOLD DB FILE")
            elif iss["issue"] == "missing_tables":
                print(f"  {iss['instance_id']:30s} MISSING: {iss['missing']}")
            else:
                print(f"  {iss['instance_id']:30s} ERROR: {iss.get('error', '?')}")

        if args.build_gold:
            print(f"\n--- Building Gold DBs ---")
            targets = [iss["instance_id"] for iss in issues] if args.build_gold == "all" else [args.build_gold]
            for iid in targets:
                print(f"\nBuilding gold for {iid}...")
                build_gold_for_task(iid, args.spider2_dir)
        elif not args.audit:
            print("\nRun with --build-gold to attempt building missing gold DBs")
            print("Run with --audit for detailed report only")

    # 5. Adopt result as gold
    if args.adopt_result:
        iid, result_dir = args.adopt_result
        print(f"\n--- Adopting Result as Gold ---")
        adopt_result_as_gold(iid, args.spider2_dir, Path(result_dir))

    # 6. Check test-env dir
    test_env = Path(__file__).resolve().parent / "test-env"
    print(f"\n--- Test Environment ---")
    print(f"Local test dir: {test_env}")
    if test_env.exists():
        contents = list(test_env.iterdir())
        print(f"  {len(contents)} items (from previous runs)")
    else:
        print("  Will be created on first run")

    print(f"\n{'=' * 60}")
    print("Setup complete. Run a benchmark with:")
    print("  python -m benchmark.run_dbt_local chinook001")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
