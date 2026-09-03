"""Read-only dbt project discovery and profile preparation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _resolve_dbt_project_dir(root: Path) -> Path | None:
    """Return the dbt project directory under the checkout root.

    The checkout root is not always the dbt project. Some repos keep the dbt
    project in a nested folder, for example ``dumpsters_dbt/``. Return the root
    when it holds ``dbt_project.yml``. If not, walk down up to 3 levels and
    return the first folder that holds ``dbt_project.yml`` (shallowest wins).
    Return ``None`` when no dbt project is found.
    """
    from pathlib import Path as _Path

    root = _Path(root)
    if (root / "dbt_project.yml").is_file():
        return root
    skip = {
        "target", "logs", "dbt_packages", "__pycache__", ".git",
        "node_modules", ".venv", ".ruff_cache", ".pytest_cache",
    }
    frontier: list[tuple[Path, int]] = [(root, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= 3:
            continue
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name in skip or entry.name.startswith("."):
                continue
            if (entry / "dbt_project.yml").is_file():
                return entry
            frontier.append((entry, depth + 1))
    return None


def _write_stub_dbt_profiles(dbt_project_dir: Path, scratch_directory: Path) -> Path:
    """Write a throwaway profiles.yml so read-only dbt commands can run.

    ``dbt ls``, ``dbt parse`` and ``dbt compile`` need a profile to resolve the
    adapter, but they never open the warehouse connection. The agent has no
    warehouse credentials, so point every output at a local duckdb file. The
    duckdb adapter is baked into the notebook image. Return the directory that
    holds the written profiles.yml (pass it to dbt as ``--profiles-dir``).
    """
    import yaml

    # dbt_project.yml names the profile the project expects. Match it so dbt
    # does not fail with "Could not find profile named ...".
    profile_name = "default"
    try:
        project_yml = yaml.safe_load(
            (dbt_project_dir / "dbt_project.yml").read_text(encoding="utf-8")
        )
        if isinstance(project_yml, dict) and project_yml.get("profile"):
            profile_name = str(project_yml["profile"])
    except (OSError, yaml.YAMLError):
        pass

    profiles_dir = scratch_directory / "dbt-profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    stub = {
        profile_name: {
            "target": "stub",
            "outputs": {
                "stub": {
                    "type": "duckdb",
                    "path": str(scratch_directory / "dbt-stub.duckdb"),
                    "threads": 1,
                }
            },
        }
    }
    (profiles_dir / "profiles.yml").write_text(
        yaml.safe_dump(stub), encoding="utf-8"
    )
    return profiles_dir


async def _run_dbt_command(argv: list[str], cwd: Path, label: str) -> bytes:
    """Run one dbt subprocess with a bounded timeout; return its output."""
    import asyncio

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ValueError(f"{label} timed out") from None
    if process.returncode != 0:
        raise ValueError(
            f"{label} failed: " + output.decode(errors="replace")[-2_000:]
        )
    return output


async def run_inspect_dbt(
    *,
    project_directory: Path,
    scratch_directory: Path,
    arguments: dict,
) -> dict:
    """Run a read-only dbt inspection command for the chat agent."""
    # The checkout root is not always the dbt project. Some repos keep it
    # nested (for example dumpsters_dbt/). Resolve the real project dir so
    # dbt does not fail with "Missing dbt_project.yml".
    dbt_project_dir = _resolve_dbt_project_dir(project_directory)
    if dbt_project_dir is None:
        raise ValueError(
            "No dbt_project.yml was found in this project. "
            "This project has no dbt project to inspect."
        )
    command = str(arguments.get("command") or "")
    if command not in {"parse", "ls", "compile"}:
        raise ValueError("Only dbt parse, ls, and compile are allowed")
    target_path = scratch_directory / "dbt-target"
    target_path.mkdir(parents=True, exist_ok=True)
    # The agent has no warehouse credentials. Write a stub duckdb profile so
    # read-only dbt commands can resolve the adapter without connecting.
    # Without this dbt falls back to ~/.dbt and fails with
    # "profiles-dir ... does not exist".
    profiles_dir = _write_stub_dbt_profiles(dbt_project_dir, scratch_directory)
    log_path = scratch_directory / "dbt-logs"
    # The frozen checkout does not include dbt_packages (it is a build
    # artifact). If the project declares packages, install them first, or
    # dbt ls/parse/compile fail with
    # "Run dbt deps to install package dependencies".
    declares_packages = (dbt_project_dir / "packages.yml").is_file() or (
        dbt_project_dir / "dependencies.yml"
    ).is_file()
    packages_installed = (dbt_project_dir / "dbt_packages").is_dir() and any(
        (dbt_project_dir / "dbt_packages").iterdir()
    )
    if declares_packages and not packages_installed:
        await _run_dbt_command(
            [
                "dbt",
                "--no-use-colors",
                "--log-path",
                str(log_path),
                "deps",
                "--project-dir",
                str(dbt_project_dir),
                "--profiles-dir",
                str(profiles_dir),
            ],
            dbt_project_dir,
            "dbt deps",
        )
    argv = [
        "dbt",
        "--no-use-colors",
        "--log-path",
        str(log_path),
        command,
        "--project-dir",
        str(dbt_project_dir),
        "--profiles-dir",
        str(profiles_dir),
        "--target-path",
        str(target_path),
    ]
    selection = str(arguments.get("select") or "").strip()
    if selection:
        argv.extend(["--select", selection])
    import asyncio

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=project_directory,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ValueError("dbt inspection timed out") from None
    text_output = output.decode(errors="replace")[-50_000:]
    if process.returncode != 0:
        raise ValueError(f"dbt {command} failed: {text_output[-2_000:]}")
    return {"command": command, "output": text_output}
