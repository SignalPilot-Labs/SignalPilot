"""
Skills A/B test — identical benchmark environment to run_dbt_local.py, but with
a system prompt that pre-loads all SignalPilot skills and MCP tools before
handing off to the task.

This lets you measure what the skills + MCP contribute by comparing:
  A) run_dbt_local.py  (agent figures everything out itself)
  B) skills_test.py    (skills + MCP pre-loaded, agent starts with full context)

Usage:
    python -m benchmark.skills_test chinook001
    python -m benchmark.skills_test chinook001 --model claude-sonnet-4-6
    python -m benchmark.skills_test chinook001 --skip-agent   # just eval
"""

from __future__ import annotations

import io
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse
import asyncio
import json
import os
import shutil
import stat
import string
import subprocess
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Paths (same as run_dbt_local.py) ─────────────────────────
SPIDER2_DBT_DIR = Path(os.environ.get(
    "SPIDER2_DBT_DIR",
    "C:/Users/kiwi0/Desktop/what/spider2-repo/spider2-dbt",
))
EXAMPLES_DIR = SPIDER2_DBT_DIR / "examples"
GOLD_DIR = SPIDER2_DBT_DIR / "evaluation_suite" / "gold"
EVAL_JSONL = GOLD_DIR / "spider2_eval.jsonl"
TEST_ENV = BENCHMARK_DIR / "test-env"
SKILLS_SRC = BENCHMARK_DIR / "skills"
PROMPTS_DIR = BENCHMARK_DIR / "prompts"
GATEWAY_SRC = PROJECT_ROOT / "signalpilot" / "gateway"
GATEWAY_URL = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
DBT_BIN = shutil.which("dbt") or str(Path.home() / ".local" / "bin" / "dbt")

SKILL_NAMES = ["dbt-workflow", "dbt-verification", "dbt-debugging", "duckdb-sql"]


# ── Helpers (identical to run_dbt_local.py) ───────────────────
def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def _force_rmtree(path: Path):
    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    shutil.rmtree(path, onerror=on_error)


def _load_prompt(name: str, **values: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    template = string.Template(path.read_text(encoding="utf-8"))
    return template.safe_substitute(**values)


def load_task(instance_id: str) -> dict:
    with open(EXAMPLES_DIR / "spider2-dbt.jsonl") as f:
        for line in f:
            task = json.loads(line.strip())
            if task["instance_id"] == instance_id:
                return task
    raise ValueError(f"Task {instance_id} not found")


def load_eval_config(instance_id: str) -> dict | None:
    if not EVAL_JSONL.exists():
        return None
    with open(EVAL_JSONL) as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry["instance_id"] == instance_id:
                return entry
    return None


# ── Setup (identical to run_dbt_local.py) ─────────────────────
def prepare_test_env(instance_id: str) -> Path:
    project_dir = TEST_ENV / instance_id
    if project_dir.exists():
        log(f"Cleaning previous test-env/{instance_id}")
        _force_rmtree(project_dir)

    src = EXAMPLES_DIR / instance_id
    if not src.exists():
        raise FileNotFoundError(f"Task example not found: {src}")
    shutil.copytree(src, project_dir)

    skills_dst = project_dir / ".claude" / "skills"
    if SKILLS_SRC.exists():
        shutil.copytree(SKILLS_SRC, skills_dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.json", "__pycache__"))
        skill_count = len(list(skills_dst.rglob("SKILL.md")))
        log(f"Copied {skill_count} skills to .claude/skills/")

    return project_dir


def setup_signalpilot(instance_id: str, project_dir: Path):
    log(f"Setting up SignalPilot ({GATEWAY_URL})")
    try:
        req = urllib.request.Request(f"{GATEWAY_URL}/api/connections")
        with urllib.request.urlopen(req, timeout=3) as resp:
            connections = json.loads(resp.read())
    except Exception:
        log("SignalPilot gateway not reachable — skipping MCP setup", "WARN")
        return False

    for conn in connections:
        name = conn.get("name", "")
        try:
            del_req = urllib.request.Request(f"{GATEWAY_URL}/api/connections/{name}", method="DELETE")
            urllib.request.urlopen(del_req, timeout=5)
            log(f"  Removed connection: {name}")
        except Exception:
            pass

    duckdb_files = list(project_dir.glob("*.duckdb"))
    if not duckdb_files:
        log("No DuckDB file found in project", "WARN")
        return False

    db_path = str(duckdb_files[0].resolve())
    payload = json.dumps({
        "name": instance_id,
        "db_type": "duckdb",
        "database": db_path,
        "description": f"Spider2-DBT benchmark: {instance_id}",
    }).encode()

    try:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/api/connections",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log(f"  Registered: {instance_id} -> {db_path}")
        return True
    except Exception as e:
        log(f"  Registration failed: {e}", "WARN")
        return False


# ── Skills-test system prompt ─────────────────────────────────
def build_skills_system_prompt(instruction: str, instance_id: str, dbt_bin: str) -> str:
    """Build system prompt that pre-loads all skills and MCP tools.

    Uses the same dbt_local_system.md base prompt (identical environment),
    but prepends a bootstrap block that forces the agent to load all skills
    and verify MCP connectivity before starting work.
    """
    work_dir = TEST_ENV / instance_id

    # Load the exact same base prompt as run_dbt_local.py
    base_prompt = _load_prompt(
        "dbt_local_system",
        work_dir=str(work_dir),
        instruction=instruction,
        instance_id=instance_id,
        dbt_bin=dbt_bin,
    )

    bootstrap = f"""\
## BOOTSTRAP — Execute these steps FIRST, before any task work

You have 4 skills and a SignalPilot MCP server available. Load them all now.

### Step 1: Load all skills (call the Skill tool 4 times)
- `Skill({{"skill": "dbt-workflow"}})`
- `Skill({{"skill": "dbt-verification"}})`
- `Skill({{"skill": "dbt-debugging"}})`
- `Skill({{"skill": "duckdb-sql"}})`

### Step 2: Verify SignalPilot MCP connectivity
- Call `ToolSearch({{"query": "select:mcp__signalpilot__dbt_project_map,mcp__signalpilot__dbt_project_validate,mcp__signalpilot__schema_link,mcp__signalpilot__query_database", "max_results": 5}})` to fetch the MCP tool schemas.
- Call `mcp__signalpilot__dbt_project_map` with `project_dir="{work_dir}"` and `focus="work_order"` to get the project map.
- Call `mcp__signalpilot__dbt_project_validate` with `project_dir="{work_dir}"` to get validation results.

### Step 3: Proceed with the task
Once all skills are loaded and MCP tools are verified, proceed with the dbt workflow using the full context you now have.

---

"""

    return bootstrap + base_prompt


# ── Agent (same SDK flow as run_dbt_local.py) ─────────────────
async def run_agent(instance_id: str, instruction: str, project_dir: Path,
                    model: str, max_turns: int,
                    use_mcp: bool) -> dict:
    from claude_agent_sdk import (
        AssistantMessage, ClaudeAgentOptions, ResultMessage,
        TextBlock, ToolResultBlock, ToolUseBlock, query,
    )

    system_prompt = build_skills_system_prompt(instruction, instance_id, dbt_bin=DBT_BIN)
    user_prompt = _load_prompt("dbt_local_user", instruction=instruction)

    log(f"System prompt: {len(system_prompt)} chars (skills-test: bootstrap + base)")

    system_prompt_path = project_dir / "_system_prompt.md"
    system_prompt_path.write_text(system_prompt, encoding="utf-8")
    system_prompt_arg: dict = {"type": "file", "path": str(system_prompt_path)}

    # MCP config — identical to run_dbt_local.py
    mcp_config = None
    if use_mcp and GATEWAY_SRC.exists():
        child_env = {
            **os.environ,
            "SP_GATEWAY_URL": GATEWAY_URL,
            "PYTHONPATH": (
                str(GATEWAY_SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")
            ).rstrip(os.pathsep),
        }
        mcp_config = {
            "signalpilot": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "gateway.mcp_server"],
                "env": child_env,
            }
        }
        log(f"MCP configured: signalpilot at {GATEWAY_SRC} (PYTHONPATH injected)")

    options = ClaudeAgentOptions(
        system_prompt=system_prompt_arg,
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        cwd=str(project_dir),
        **({"mcp_servers": mcp_config} if mcp_config else {}),
    )

    messages = []
    tool_calls = []
    skill_loads = []
    mcp_calls = []
    turn_count = 0
    start_time = time.monotonic()

    log(f"Agent starting (skills-test): model={model}, max_turns={max_turns}")

    try:
        async for message in query(prompt=user_prompt, options=options):
            elapsed = time.monotonic() - start_time

            if isinstance(message, AssistantMessage):
                turn_count += 1
                log(f"--- Turn {turn_count} ({elapsed:.1f}s) ---")
                for block in message.content:
                    if isinstance(block, TextBlock):
                        for line in block.text.split("\n"):
                            log(f"  AGENT: {line}")
                        messages.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_input = json.dumps(block.input, ensure_ascii=False)
                        log(f"  TOOL: {block.name} -> {tool_input[:200]}")
                        tool_calls.append({"name": block.name, "turn": turn_count})

                        # Track skill loads and MCP calls for reporting
                        if block.name == "Skill":
                            skill_name = block.input.get("skill", "unknown")
                            skill_loads.append({"skill": skill_name, "turn": turn_count})
                        elif block.name.startswith("mcp__signalpilot__"):
                            mcp_calls.append({"tool": block.name, "turn": turn_count})

                    elif isinstance(block, ToolResultBlock):
                        result_str = str(getattr(block, "content", block))
                        log(f"  RESULT: {result_str[:300]}")

            elif isinstance(message, ResultMessage):
                log(f"Agent finished: {turn_count} turns, {elapsed:.1f}s")

    except Exception as e:
        log(f"Agent error: {e}", "ERROR")
        traceback.print_exc()
        return {"error": str(e), "messages": messages, "tool_calls": tool_calls,
                "skill_loads": skill_loads, "mcp_calls": mcp_calls}

    elapsed = time.monotonic() - start_time
    log(f"Agent complete: turns={turn_count}, tools={len(tool_calls)}, elapsed={elapsed:.1f}s")
    log(f"  Skills loaded: {[s['skill'] for s in skill_loads]}")
    log(f"  MCP calls: {len(mcp_calls)} ({', '.join(set(c['tool'] for c in mcp_calls))})")

    return {
        "messages": messages, "tool_calls": tool_calls,
        "elapsed": elapsed, "turns": turn_count,
        "skill_loads": skill_loads, "mcp_calls": mcp_calls,
    }


# ── dbt run (identical to run_dbt_local.py) ───────────────────
def run_dbt(project_dir: Path) -> tuple[bool, str]:
    log("Running dbt deps + dbt run (final validation)...")

    if not Path(DBT_BIN).exists():
        log(f"dbt binary not found at {DBT_BIN}", "WARN")
        return False, f"dbt binary not found at {DBT_BIN}"

    deps = subprocess.run(
        [DBT_BIN, "deps"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=120,
    )
    for line in (deps.stdout + deps.stderr).strip().split("\n"):
        if line.strip():
            log(f"  dbt deps: {line.strip()}")

    result = subprocess.run(
        [DBT_BIN, "run"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + "\n" + result.stderr
    for line in output.strip().split("\n"):
        if line.strip():
            log(f"  dbt run: {line.strip()}")

    log(f"dbt run exit code: {result.returncode}")

    try:
        import duckdb as _duckdb
        for db_file in project_dir.glob("*.duckdb"):
            con = _duckdb.connect(str(db_file))
            con.execute("CHECKPOINT")
            con.close()
            log(f"DuckDB CHECKPOINT: {db_file.name}")
    except Exception as e:
        log(f"DuckDB CHECKPOINT failed (non-fatal): {e}", "WARN")

    return result.returncode == 0, output


# ── Evaluate ──────────────────────────────────────────────────
from .evaluation.local_comparator import evaluate  # noqa: E402


# ── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Skills A/B test — identical benchmark env with pre-loaded skills + MCP"
    )
    parser.add_argument("instance_id", default="chinook001", nargs="?")
    parser.add_argument("--model", default="claude-opus-4-6")
    parser.add_argument("--max-turns", type=int, default=200,
                        help="Safety cap on agent turns (default 200)")
    parser.add_argument("--skip-agent", action="store_true",
                        help="Skip agent, just eval existing results")
    parser.add_argument("--no-mcp", action="store_true",
                        help="Disable SignalPilot MCP")
    args = parser.parse_args()

    instance_id = args.instance_id
    print(f"{'=' * 60}")
    print(f"Spider2-DBT Skills Test - {instance_id}")
    print(f"{'=' * 60}")

    task = load_task(instance_id)
    log(f"Task: {task['instruction']}")

    if args.skip_agent:
        project_dir = TEST_ENV / instance_id
        if not project_dir.exists():
            print(f"No previous results at {project_dir}")
            sys.exit(1)
    else:
        project_dir = prepare_test_env(instance_id)

    log(f"Work dir: {project_dir}")

    if not args.skip_agent:
        use_mcp = not args.no_mcp
        if use_mcp:
            use_mcp = setup_signalpilot(instance_id, project_dir)

        result = asyncio.run(run_agent(
            instance_id=instance_id,
            instruction=task["instruction"],
            project_dir=project_dir,
            model=args.model,
            max_turns=args.max_turns,
            use_mcp=use_mcp,
        ))

        if "error" in result:
            log(f"Agent failed: {result['error']}", "ERROR")

        dbt_ok, dbt_output = run_dbt(project_dir)

        try:
            import duckdb
            for db in project_dir.glob("*.duckdb"):
                con = duckdb.connect(str(db), read_only=True)
                tables = con.execute("SHOW TABLES").fetchall()
                log(f"{db.name}: {len(tables)} tables")
                for t in tables:
                    count = con.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
                    log(f"  {t[0]}: {count} rows")
                con.close()
        except Exception as e:
            log(f"DuckDB inspection error: {e}", "WARN")

        # Save result with skills-test metadata
        result_data = {
            "test_variant": "skills-test",
            "success": dbt_ok,
            "agent_elapsed": result.get("elapsed", 0),
            "agent_turns": result.get("turns", 0),
            "tool_calls": result.get("tool_calls", []),
            "skill_loads": result.get("skill_loads", []),
            "mcp_calls": result.get("mcp_calls", []),
        }
        (project_dir / "agent_result.json").write_text(json.dumps(result_data, indent=2))

    # Evaluate
    print(f"\n{'=' * 60}")
    print(f"Evaluating against gold standard...")
    print(f"{'=' * 60}")

    try:
        passed, details = evaluate(project_dir, instance_id)
        print(details)

        print(f"\n{'=' * 60}")
        print(f"RESULT: {'PASS' if passed else 'FAIL'}")
        print(f"{'=' * 60}")
    except Exception as e:
        print(f"\n  Evaluation error: {e}")
        traceback.print_exc()
        print(f"\n{'=' * 60}")
        print(f"RESULT: ERROR")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
