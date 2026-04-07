"""
Single-task Spider2-DBT benchmark runner.

Builds a Docker image with dbt-duckdb + Claude Code CLI, starts a container
with the task files + skills, runs the Claude Agent SDK inside it, then
evaluates the result against gold.

Usage:
    python -m benchmark.run_dbt_single chinook001
    python -m benchmark.run_dbt_single chinook001 --model claude-opus-4-6
    python -m benchmark.run_dbt_single chinook001 --skip-agent  # Just eval
"""

from __future__ import annotations

import io
import sys

# Fix Windows console encoding before any output
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Paths
SPIDER2_DBT_DIR = Path("C:/Users/kiwi0/Desktop/what/spider2-repo/spider2-dbt")
EXAMPLES_DIR = SPIDER2_DBT_DIR / "examples"
GOLD_DIR = SPIDER2_DBT_DIR / "evaluation_suite" / "gold"
EVAL_JSONL = GOLD_DIR / "spider2_eval.jsonl"
WORK_DIR = Path("C:/Users/kiwi0/Desktop/what/SignalPilot/benchmark/_dbt_workdir")
BENCHMARK_DIR = Path("C:/Users/kiwi0/Desktop/what/SignalPilot/benchmark")
SKILLS_SRC = Path("C:/Users/kiwi0/Desktop/what/SignalPilot/benchmark/skills")
GATEWAY_SRC = Path("C:/Users/kiwi0/Desktop/what/SignalPilot/signalpilot/gateway")

IMAGE_NAME = "sp-dbt-benchmark-agent"
CONTAINER_NAME = "sp-dbt-benchmark"


def load_task(instance_id: str) -> dict:
    """Load task definition from the JSONL."""
    with open(EXAMPLES_DIR / "spider2-dbt.jsonl") as f:
        for line in f:
            task = json.loads(line.strip())
            if task["instance_id"] == instance_id:
                return task
    raise ValueError(f"Task {instance_id} not found")


def load_eval_config(instance_id: str) -> dict | None:
    """Load evaluation config for this task."""
    with open(EVAL_JSONL) as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry["instance_id"] == instance_id:
                return entry
    return None


def _force_rmtree(path: Path):
    """Remove directory tree, handling Windows permission errors."""
    import stat
    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    shutil.rmtree(path, onerror=on_error)


def prepare_workdir(instance_id: str) -> Path:
    """Copy the task's dbt project to a working directory."""
    src = EXAMPLES_DIR / instance_id
    dst = WORK_DIR / instance_id
    if dst.exists():
        _force_rmtree(dst)
    shutil.copytree(src, dst)

    # Copy benchmark skills into .claude/skills/ so Claude Code loads them natively
    skills_dst = dst / ".claude" / "skills"
    if SKILLS_SRC.exists():
        shutil.copytree(SKILLS_SRC, skills_dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.json", "__pycache__"))
        skill_count = len(list(skills_dst.rglob("SKILL.md")))
        print(f"  [setup] Copied {skill_count} skills to {skills_dst}")

    return dst


def setup_signalpilot_connection(instance_id: str, project_dir: Path, gateway_url: str):
    """Clear all existing connections, register only the task's DuckDB."""
    import urllib.request
    import urllib.error

    print(f"\n{'='*60}")
    print(f"Setting up SignalPilot — clean slate for {instance_id}")
    print(f"  Gateway: {gateway_url}")
    print(f"{'='*60}")

    # List and delete all existing connections
    try:
        req = urllib.request.Request(f"{gateway_url}/api/connections")
        with urllib.request.urlopen(req, timeout=5) as resp:
            connections = json.loads(resp.read())
        for conn in connections:
            name = conn.get("name", "")
            print(f"  Removing existing connection: {name}")
            try:
                del_req = urllib.request.Request(
                    f"{gateway_url}/api/connections/{name}",
                    method="DELETE",
                )
                urllib.request.urlopen(del_req, timeout=5)
            except Exception as e:
                print(f"    [WARN] Could not remove {name}: {e}")
    except Exception as e:
        print(f"  [WARN] Could not list connections: {e}")
        print(f"  (Is SignalPilot gateway running at {gateway_url}?)")
        return

    # Register the task's DuckDB
    # The DuckDB path inside the container will be /workspace/<filename>.duckdb
    duckdb_files = list(project_dir.glob("*.duckdb"))
    if not duckdb_files:
        print(f"  [WARN] No .duckdb files found in {project_dir}")
        return

    db_filename = duckdb_files[0].name
    container_db_path = f"/workspace/{db_filename}"

    payload = json.dumps({
        "name": instance_id,
        "db_type": "duckdb",
        "database": container_db_path,
        "description": f"Spider2-DBT benchmark: {instance_id}",
    }).encode()

    try:
        req = urllib.request.Request(
            f"{gateway_url}/api/connections",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"  Registered: {instance_id} -> {container_db_path}")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  [WARN] Registration failed: {e.code} {body}")
    except Exception as e:
        print(f"  [WARN] Registration failed: {e}")

    # Verify — should be exactly 1 connection
    try:
        req = urllib.request.Request(f"{gateway_url}/api/connections")
        with urllib.request.urlopen(req, timeout=5) as resp:
            connections = json.loads(resp.read())
        print(f"  Active connections: {[c.get('name') for c in connections]}")
    except Exception:
        pass


def build_docker_image() -> bool:
    """Build the dbt benchmark agent Docker image."""
    print(f"\n{'='*60}")
    print(f"Building Docker image: {IMAGE_NAME}")
    print(f"{'='*60}")

    cmd = [
        "docker", "build",
        "-t", IMAGE_NAME,
        "-f", str(BENCHMARK_DIR / "Dockerfile.dbt-agent"),
        str(BENCHMARK_DIR),
    ]
    print(f"  $ {' '.join(cmd)}")

    result = subprocess.run(cmd, timeout=600)
    if result.returncode != 0:
        print(f"  [ERROR] Docker build failed!")
        return False
    print(f"  [OK] Image {IMAGE_NAME} built successfully")
    return True


def run_container(instance_id: str, instruction: str, project_dir: Path,
                  model: str, max_turns: int, budget: float) -> bool:
    """Start the benchmark agent container, copy files in/out (no volume mount for DuckDB compat)."""
    print(f"\n{'='*60}")
    print(f"Starting benchmark container: {CONTAINER_NAME}")
    print(f"  Instance: {instance_id}")
    print(f"  Model: {model}")
    print(f"  Max turns: {max_turns}")
    print(f"  Budget: ${budget}")
    print(f"  Workspace: {project_dir}")
    print(f"{'='*60}")

    # Get the OAuth token
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not oauth_token:
        print("  [ERROR] CLAUDE_CODE_OAUTH_TOKEN not set!")
        print("  Set it with: export CLAUDE_CODE_OAUTH_TOKEN=<your-token>")
        return False

    # Remove existing container if any
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)

    # Create container (don't start yet) — no volume mount to avoid DuckDB mmap issues on Windows
    # Mount gateway source as volume (avoids docker cp staleness issues with Python packages)
    gateway_vol = str(GATEWAY_SRC.resolve()).replace("\\", "/")

    create_cmd = [
        "docker", "create",
        "--name", CONTAINER_NAME,
        "-e", f"CLAUDE_CODE_OAUTH_TOKEN={oauth_token}",
        "-e", f"SP_GATEWAY_URL={os.environ.get('SP_GATEWAY_URL', 'http://host.docker.internal:3300')}",
        "-e", "SIGNALPILOT_MCP_CWD=/signalpilot",
        "-v", f"{gateway_vol}:/signalpilot",
        "--add-host=host.docker.internal:host-gateway",
        IMAGE_NAME,
        "--instance-id", instance_id,
        "--instruction", instruction,
        "--model", model,
        "--max-turns", str(max_turns),
        "--budget", str(budget),
    ]
    result = subprocess.run(create_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] docker create failed: {result.stderr}")
        return False
    print(f"  [OK] Container created")

    # Copy workspace files INTO the container
    workspace_path = str(project_dir.resolve()).replace("\\", "/")
    print(f"  Copying workspace into container...")
    cp_in = subprocess.run(
        ["docker", "cp", f"{workspace_path}/.", f"{CONTAINER_NAME}:/workspace/"],
        capture_output=True, text=True,
    )
    if cp_in.returncode != 0:
        print(f"  [ERROR] docker cp in failed: {cp_in.stderr}")
        return False
    print(f"  [OK] Workspace copied")

    print(f"  [OK] Gateway source mounted at /signalpilot (read-only volume)")

    # Start the container and stream output
    # (entrypoint runs as root first to fix permissions, then drops to agentuser)
    print(f"\n  Streaming agent output...\n")
    start_time = time.monotonic()

    start_cmd = ["docker", "start", "-a", CONTAINER_NAME]
    proc = subprocess.Popen(
        start_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    try:
        for line in proc.stdout:
            sys.stdout.write(f"  [container] {line}")
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n  [INTERRUPTED] Stopping container...")
        subprocess.run(["docker", "stop", CONTAINER_NAME], capture_output=True)
        return False

    proc.wait()
    elapsed = time.monotonic() - start_time
    print(f"\n  Container exited with code {proc.returncode} in {elapsed:.1f}s")

    # Copy workspace files BACK from the container (to get the modified DuckDB + new SQL files)
    print(f"  Copying results back from container...")
    cp_out = subprocess.run(
        ["docker", "cp", f"{CONTAINER_NAME}:/workspace/.", f"{workspace_path}/"],
        capture_output=True, text=True,
    )
    if cp_out.returncode != 0:
        print(f"  [WARN] docker cp out failed: {cp_out.stderr}")
    else:
        print(f"  [OK] Results copied back")

    # Clean up container
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)

    return proc.returncode == 0


def evaluate(project_dir: Path, instance_id: str) -> tuple[bool, str]:
    """Evaluate the result against gold standard using duckdb_match."""
    import duckdb

    eval_config = load_eval_config(instance_id)
    if not eval_config:
        return False, "No evaluation config found"

    eval_params = eval_config["evaluation"]["parameters"]
    gold_db_path = str(GOLD_DIR / instance_id / eval_params["gold"])
    result_db_path = str(project_dir / eval_params["gold"])

    condition_tabs = eval_params.get("condition_tabs")
    condition_cols = eval_params.get("condition_cols")
    ignore_orders = eval_params.get("ignore_orders")

    print(f"\n  [eval] Gold DB: {gold_db_path}")
    print(f"  [eval] Result DB: {result_db_path}")

    if not Path(result_db_path).exists():
        return False, f"Result DB not found: {result_db_path}"
    if not Path(gold_db_path).exists():
        return False, f"Gold DB not found: {gold_db_path}"

    def get_tables(db_path):
        con = duckdb.connect(database=db_path, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return tables

    def get_table(db_path, table_name):
        con = duckdb.connect(database=db_path, read_only=True)
        df = con.execute(f"SELECT * FROM {table_name}").fetchdf()
        con.close()
        return df

    # Log what tables exist
    result_tables = get_tables(result_db_path)
    gold_tables = get_tables(gold_db_path)
    print(f"  [eval] Gold tables: {gold_tables}")
    print(f"  [eval] Result tables: {result_tables}")

    if condition_tabs is None:
        condition_tabs = gold_tables

    if ignore_orders is None:
        ignore_orders = [False] * len(condition_tabs)

    if condition_cols is None:
        condition_cols = [[]] * len(condition_tabs)

    all_match = True
    details = []

    for i, tab in enumerate(condition_tabs):
        print(f"  [eval] Checking table: {tab}")

        if tab not in result_tables:
            details.append(f"  {tab}: FAIL - table not found in result DB")
            print(f"  [eval]   FAIL - table '{tab}' not in result DB (have: {result_tables})")
            all_match = False
            continue

        try:
            gold_df = get_table(gold_db_path, tab)
            pred_df = get_table(result_db_path, tab)
        except Exception as e:
            details.append(f"  {tab}: ERROR - {e}")
            print(f"  [eval]   ERROR reading table: {e}")
            all_match = False
            continue

        print(f"  [eval]   Gold shape: {gold_df.shape}, Result shape: {pred_df.shape}")

        # Select condition columns
        cols = condition_cols[i] if condition_cols[i] else list(range(len(gold_df.columns)))

        try:
            gold_sub = gold_df.iloc[:, cols]
            pred_sub = pred_df.iloc[:, cols]
        except IndexError as e:
            details.append(f"  {tab}: FAIL - column index error: {e}")
            print(f"  [eval]   FAIL - column indexing: {e}")
            all_match = False
            continue

        print(f"  [eval]   Comparing {len(cols)} columns, gold={gold_sub.shape}, pred={pred_sub.shape}")

        # Compare shapes
        if gold_sub.shape != pred_sub.shape:
            details.append(f"  {tab}: FAIL - shape mismatch gold={gold_sub.shape} pred={pred_sub.shape}")
            print(f"  [eval]   FAIL - shape mismatch")
            # Show first few rows for debugging
            print(f"  [eval]   Gold columns: {list(gold_sub.columns)}")
            print(f"  [eval]   Pred columns: {list(pred_sub.columns)}")
            print(f"  [eval]   Gold head:\n{gold_sub.head(3)}")
            print(f"  [eval]   Pred head:\n{pred_sub.head(3)}")
            all_match = False
            continue

        # Sort if ignoring order
        if ignore_orders[i]:
            gold_sub = gold_sub.sort_values(by=list(gold_sub.columns)).reset_index(drop=True)
            pred_sub = pred_sub.sort_values(by=list(pred_sub.columns)).reset_index(drop=True)

        # Compare values with tolerance
        try:
            match = True
            mismatch_col = None
            for col in gold_sub.columns:
                g = gold_sub[col]
                p = pred_sub[col]
                if g.dtype in ("float64", "float32", "int64", "int32"):
                    if not all(abs(a - b) < 0.01 for a, b in zip(g.fillna(0), p.fillna(0))):
                        match = False
                        mismatch_col = col
                        break
                else:
                    if not all(str(a).strip().lower() == str(b).strip().lower() for a, b in zip(g.fillna(""), p.fillna(""))):
                        match = False
                        mismatch_col = col
                        break

            if match:
                details.append(f"  {tab}: PASS ({gold_sub.shape[0]} rows, {len(cols)} cols)")
                print(f"  [eval]   PASS - {gold_sub.shape[0]} rows, {len(cols)} cols match")
            else:
                details.append(f"  {tab}: FAIL - values don't match (column: {mismatch_col})")
                print(f"  [eval]   FAIL - mismatch in column '{mismatch_col}'")
                # Show mismatched values for debugging
                if mismatch_col:
                    g_col = gold_sub[mismatch_col].head(5)
                    p_col = pred_sub[mismatch_col].head(5)
                    print(f"  [eval]   Gold values: {list(g_col)}")
                    print(f"  [eval]   Pred values: {list(p_col)}")
                all_match = False
        except Exception as e:
            details.append(f"  {tab}: FAIL - comparison error: {e}")
            print(f"  [eval]   FAIL - comparison error: {e}")
            all_match = False

    return all_match, "\n".join(details)


def main():
    parser = argparse.ArgumentParser(description="Run a single Spider2-DBT benchmark task")
    parser.add_argument("instance_id", default="chinook001", nargs="?")
    parser.add_argument("--model", default="claude-opus-4-6")
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--skip-agent", action="store_true", help="Skip agent, just run eval")
    parser.add_argument("--skip-build", action="store_true", help="Skip Docker build")
    args = parser.parse_args()

    instance_id = args.instance_id
    print(f"{'='*60}")
    print(f"Spider2-DBT E2E Benchmark - {instance_id}")
    print(f"{'='*60}")

    # Load task
    task = load_task(instance_id)
    print(f"Task: {task['instruction']}")

    # Prepare working directory (skip if just evaluating existing results)
    project_dir = WORK_DIR / instance_id
    if not args.skip_agent:
        project_dir = prepare_workdir(instance_id)
    print(f"Work dir: {project_dir}")

    if not args.skip_agent:
        # Build Docker image
        if not args.skip_build:
            if not build_docker_image():
                print("\nFailed to build Docker image!")
                sys.exit(1)

        # Clear all SignalPilot connections and register only this task's DuckDB
        gateway_url = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
        setup_signalpilot_connection(instance_id, project_dir, gateway_url)

        # Run agent in container
        success = run_container(
            instance_id=instance_id,
            instruction=task["instruction"],
            project_dir=project_dir,
            model=args.model,
            max_turns=args.max_turns,
            budget=args.budget,
        )

        # Read agent result
        result_path = project_dir / "agent_result.json"
        if result_path.exists():
            agent_result = json.loads(result_path.read_text())
            print(f"\n  Agent result: success={agent_result.get('success')}")
            print(f"  Agent elapsed: {agent_result.get('agent_elapsed', 0):.1f}s")
        else:
            print(f"\n  [WARNING] No agent_result.json found")

        if not success:
            print(f"\nContainer run failed!")
            # Continue to eval anyway — agent may have created some files

    # Evaluate
    print(f"\n{'='*60}")
    print(f"Evaluating against gold standard...")
    print(f"{'='*60}")

    try:
        passed, details = evaluate(project_dir, instance_id)
        print(details)
        print(f"\n{'='*60}")
        print(f"RESULT: {'PASS' if passed else 'FAIL'}")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\n  Evaluation error: {e}")
        import traceback
        traceback.print_exc()
        print(f"\n{'='*60}")
        print(f"RESULT: ERROR")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
