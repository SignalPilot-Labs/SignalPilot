"""ADE-bench workdir preparation: copy project, database, apply setup, inject tests."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from ..core.logging import log


def _ade_bench_dir() -> Path:
    env_path = os.environ.get("ADE_BENCH_DIR")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent.parent.parent / "ade-bench"


def _force_rmtree(path: Path) -> None:
    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    shutil.rmtree(path, onerror=on_error)


def prepare_ade_workdir(task: dict, work_base: Path) -> Path:
    """Prepare a working directory for an ADE-bench task.

    Steps:
    1. Copy shared project into work_base/<task_id>/
    2. Copy DuckDB database into project dir
    3. Apply setup patch (if setup.sh exists)
    4. Copy task-specific seeds + macros into project (NOT tests — injected at eval time)
    5. Merge seed column type overrides from _no-op.txt
    6. Run dbt deps + setup dbt commands
    7. Init git repo

    Note: Tests are NOT copied during workdir prep. They are injected fresh
    at evaluation time (matching official ADE-bench behavior where the test
    directory is wiped and replaced before dbt test).
    """
    ade_dir = _ade_bench_dir()
    task_id = task["task_id"]
    project_name = task["project_name"]
    db_name = task["db_name"]

    # Source paths
    project_src = ade_dir / "shared" / "projects" / "dbt" / project_name
    db_src = ade_dir / "shared" / "databases" / "duckdb" / f"{db_name}.duckdb"

    if not project_src.exists():
        raise FileNotFoundError(f"Shared project not found: {project_src}")
    if not db_src.exists():
        raise FileNotFoundError(f"DuckDB database not found: {db_src}")

    # Destination
    dst = work_base / task_id
    if dst.exists():
        _force_rmtree(dst)

    # Step 1: Copy project
    shutil.copytree(project_src, dst)
    log(f"Copied project: {project_src} -> {dst}")

    # Remove stale partial_parse
    stale = dst / "target" / "partial_parse.msgpack"
    if stale.exists():
        stale.unlink()

    # Step 2: Copy DuckDB database
    db_dst = dst / f"{db_name}.duckdb"
    shutil.copy2(db_src, db_dst)
    log(f"Copied database: {db_src} -> {db_dst}")

    # Step 3: Copy macros (NOT seeds or tests — injected at eval time)
    if task.get("macros_dir") and task["macros_dir"].exists():
        macros_dst = dst / "macros"
        macros_dst.mkdir(exist_ok=True)
        for f in task["macros_dir"].iterdir():
            shutil.copy2(f, macros_dst / f.name)
        log(f"Copied {len(list(task['macros_dir'].iterdir()))} macro files")

    # Step 4: dbt deps (before setup.sh which may need packages)
    dbt_bin = shutil.which("dbt") or "dbt"
    if (dst / "packages.yml").exists():
        result = subprocess.run(
            [dbt_bin, "deps"],
            cwd=str(dst), capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            log("dbt deps completed")
        else:
            log(f"dbt deps failed: {result.stderr[-200:]}", "WARN")

    # Step 5: Run setup.sh as a full bash script
    # This handles ALL setup commands: patches, dbt commands, raw SQL heredocs,
    # python scripts, etc. We adapt Docker paths to local paths and run it whole.
    if task.get("setup_script"):
        # Copy setup files into the project so patches and SETUP_DIR references work
        if task.get("setup_dir"):
            setup_tmp = dst / "_ade_setup"
            shutil.copytree(task["setup_dir"], setup_tmp)
            # Also copy to setup/ for scripts using SETUP_DIR="$(dirname ...)/setup"
            setup_alt = dst / "setup"
            if not setup_alt.exists():
                shutil.copytree(task["setup_dir"], setup_alt)
            # Adapt /app/<name>.duckdb in copied Python scripts
            for setup_dir_path in (setup_tmp, setup_alt):
                for py_file in setup_dir_path.glob("*.py"):
                    content = py_file.read_text(errors="replace")
                    for db_file in dst.glob("*.duckdb"):
                        content = content.replace(f"/app/{db_file.name}", str(db_file))
                    py_file.write_text(content)

        # Strip CRLF from SQL files and patch files (Linux patch tool fails with CRLF)
        for ext_pat in ("*.sql", "*.patch"):
            for f in dst.rglob(ext_pat):
                if any(skip in str(f) for skip in ("dbt_packages", "target", "_ade_setup")):
                    continue
                try:
                    content = f.read_bytes()
                    if b"\r\n" in content:
                        f.write_bytes(content.replace(b"\r\n", b"\n"))
                except Exception:
                    pass
        # Also strip CRLF in setup directories
        for setup_dir_path in (dst / "_ade_setup", dst / "setup"):
            if setup_dir_path.exists():
                for f in setup_dir_path.rglob("*"):
                    if f.is_file() and f.suffix in (".sql", ".patch", ".sh", ".py"):
                        try:
                            content = f.read_bytes()
                            if b"\r\n" in content:
                                f.write_bytes(content.replace(b"\r\n", b"\n"))
                        except Exception:
                            pass

        setup_text = task["setup_script"].read_text()
        # Adapt Docker container paths to local paths
        adapted = setup_text.replace("/app/setup/", "_ade_setup/")
        adapted = adapted.replace("/sage/solutions/", "_ade_setup/")
        adapted = adapted.replace("/app/profiles.yml", str(dst / "profiles.yml"))
        # Replace /app/<name>.duckdb with local path (for Python heredocs in setup.sh)
        for db_file in dst.glob("*.duckdb"):
            adapted = adapted.replace(f"/app/{db_file.name}", str(db_file))
        # Add fuzz to patch commands to handle minor line-number drift
        adapted = adapted.replace("patch -p1", "patch --fuzz=3 -p1")

        # Create /scripts/run_sql.sh shim that executes SQL via DuckDB Python
        scripts_dir = dst / "_scripts"
        if "/scripts/run_sql" in adapted:
            scripts_dir.mkdir(exist_ok=True)
            db_files = list(dst.glob("*.duckdb"))
            db_path_abs = str(db_files[0]) if db_files else str(dst / "database.duckdb")

            # Write a Python helper script (avoids nested quoting issues)
            run_sql_py = scripts_dir / "run_sql_shim.py"
            run_sql_py.write_text(
                "import duckdb, sys, re\n"
                f"conn = duckdb.connect('{db_path_abs}')\n"
                "sql = sys.stdin.read()\n"
                "# Strip SQL comments before splitting\n"
                "sql = re.sub(r'--[^\\n]*', '', sql)\n"
                "for stmt in sql.split(';'):\n"
                "    stmt = stmt.strip()\n"
                "    if stmt:\n"
                "        try:\n"
                "            conn.execute(stmt)\n"
                "        except Exception as e:\n"
                "            print(f'SQL error: {e}', file=sys.stderr)\n"
                "conn.close()\n"
            )

            # Write shell wrapper that pipes stdin to the Python helper
            shim = scripts_dir / "run_sql.sh"
            shim.write_text(
                "#!/bin/bash\n"
                "# run_sql.sh shim: reads SQL from stdin, executes against DuckDB\n"
                f"python3 '{run_sql_py}'\n"
            )
            shim.chmod(0o755)

            adapted = adapted.replace("/scripts/", str(scripts_dir) + "/")
            log(f"Created run_sql.sh shim -> {db_path_abs}")

        # Write adapted script and run it
        adapted_script = dst / "_run_setup.sh"
        adapted_script.write_text(adapted)
        log(f"Running setup.sh (full script)")
        result = subprocess.run(
            ["bash", str(adapted_script), "--db-type=duckdb", "--project-type=dbt"],
            cwd=str(dst), capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            log(f"Setup warning (non-fatal): {result.stderr[-300:]}", "WARN")
        else:
            log("Setup completed successfully")
        if result.stderr:
            log(f"Setup stderr: {result.stderr[-500:]}")
        # Clean up
        adapted_script.unlink(missing_ok=True)
        if scripts_dir.exists():
            _force_rmtree(scripts_dir)
        if task.get("setup_dir") and (dst / "_ade_setup").exists():
            _force_rmtree(dst / "_ade_setup")
        if (dst / "setup").exists():
            _force_rmtree(dst / "setup")

    # Step 7: Write .mcp.json
    import json as _json
    from ..core.mcp import load_mcp_servers
    try:
        mcp_cfg = {"mcpServers": load_mcp_servers()}
        (dst / ".mcp.json").write_text(_json.dumps(mcp_cfg, indent=2))
        log("Wrote .mcp.json")
    except Exception as e:
        log(f"Failed to write .mcp.json: {e}", "WARN")

    # Step 8: Init git repo AFTER setup — baseline is post-setup state.
    # The agent sees only what exists after setup.sh ran. The verifier's
    # CHECK 5/6 use `git show HEAD:<path>` to detect what the AGENT changed,
    # not what setup.sh changed.
    gitignore = dst / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*.duckdb\n*.duckdb.wal\ntarget/\ndbt_packages/\nlogs/\n")
    subprocess.run(["git", "init"], cwd=str(dst), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(dst), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "post-setup baseline"],
        cwd=str(dst), capture_output=True,
    )
    log("Git: initialized repo with post-setup baseline")

    return dst
