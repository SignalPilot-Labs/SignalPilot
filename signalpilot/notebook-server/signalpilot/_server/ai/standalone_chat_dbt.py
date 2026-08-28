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
