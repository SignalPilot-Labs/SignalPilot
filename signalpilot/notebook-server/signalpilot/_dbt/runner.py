"""Subprocess-based dbt command runner."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from signalpilot import _loggers

LOGGER = _loggers.sp_logger()

DBT_COMMANDS = [
    "run",
    "build",
    "compile",
    "test",
    "seed",
    "snapshot",
    "deps",
    "debug",
    "parse",
    "ls",
    "show",
    "clean",
    "docs generate",
    "docs serve",
    "source freshness",
    "retry",
    "init",
]


@dataclass
class DbtCommandResult:
    command: str
    args: list[str]
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    project_dir: str | None = None


@dataclass
class DbtProjectInfo:
    project_dir: str
    project_name: str | None = None
    profile: str | None = None
    model_paths: list[str] = field(default_factory=lambda: ["models"])
    seed_paths: list[str] = field(default_factory=lambda: ["seeds"])
    test_paths: list[str] = field(default_factory=lambda: ["tests"])
    macro_paths: list[str] = field(default_factory=lambda: ["macros"])
    snapshot_paths: list[str] = field(default_factory=lambda: ["snapshots"])
    has_manifest: bool = False
    has_profiles: bool = False
    dbt_version: str | None = None


def find_dbt_executable() -> str | None:
    return shutil.which("dbt")


def find_dbt_project(start_dir: str | None = None) -> str | None:
    if start_dir is None:
        start_dir = os.getcwd()

    current = Path(start_dir).resolve()
    for _ in range(10):
        if (current / "dbt_project.yml").exists():
            return str(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def parse_dbt_project_yml(project_dir: str) -> DbtProjectInfo:
    project_file = Path(project_dir) / "dbt_project.yml"
    info = DbtProjectInfo(project_dir=project_dir)

    if not project_file.exists():
        return info

    try:
        import yaml

        with open(project_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        info.project_name = data.get("name")
        info.profile = data.get("profile")
        info.model_paths = data.get("model-paths", ["models"])
        info.seed_paths = data.get("seed-paths", ["seeds"])
        info.test_paths = data.get("test-paths", ["tests"])
        info.macro_paths = data.get("macro-paths", ["macros"])
        info.snapshot_paths = data.get("snapshot-paths", ["snapshots"])
    except Exception as e:
        LOGGER.warning("Failed to parse dbt_project.yml: %s", e)

    info.has_manifest = (
        Path(project_dir) / "target" / "manifest.json"
    ).exists()

    profiles_path = Path(project_dir) / "profiles.yml"
    if not profiles_path.exists():
        home_profiles = Path.home() / ".dbt" / "profiles.yml"
        info.has_profiles = home_profiles.exists()
    else:
        info.has_profiles = True

    dbt_exe = find_dbt_executable()
    if dbt_exe:
        try:
            result = subprocess.run(
                [dbt_exe, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.splitlines():
                if "installed" in line.lower() or "core" in line.lower():
                    parts = line.strip().split()
                    for part in parts:
                        if part and part[0].isdigit():
                            info.dbt_version = part
                            break
                    if info.dbt_version:
                        break
        except Exception:
            pass

    return info


def run_dbt_command_sync(
    command: str,
    args: list[str] | None = None,
    project_dir: str | None = None,
    profiles_dir: str | None = None,
    target: str | None = None,
    env_vars: dict[str, str] | None = None,
    timeout: int = 300,
) -> DbtCommandResult:
    dbt_exe = find_dbt_executable()
    if not dbt_exe:
        return DbtCommandResult(
            command=command,
            args=args or [],
            success=False,
            exit_code=-1,
            stdout="",
            stderr="dbt executable not found. Install dbt-core: pip install dbt-core",
            duration_ms=0,
            project_dir=project_dir,
        )

    cmd_parts = [dbt_exe] + command.split()

    if project_dir:
        cmd_parts.extend(["--project-dir", project_dir])
    if profiles_dir:
        cmd_parts.extend(["--profiles-dir", profiles_dir])
    if target:
        cmd_parts.extend(["--target", target])

    if args:
        cmd_parts.extend(args)

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    LOGGER.info("Running dbt command: %s", " ".join(cmd_parts))
    start = time.monotonic()

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=project_dir or os.getcwd(),
        )
        duration_ms = (time.monotonic() - start) * 1000

        return DbtCommandResult(
            command=command,
            args=args or [],
            success=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
            project_dir=project_dir,
        )
    except subprocess.TimeoutExpired:
        duration_ms = (time.monotonic() - start) * 1000
        return DbtCommandResult(
            command=command,
            args=args or [],
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            duration_ms=duration_ms,
            project_dir=project_dir,
        )
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        return DbtCommandResult(
            command=command,
            args=args or [],
            success=False,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_ms=duration_ms,
            project_dir=project_dir,
        )


async def run_dbt_command_async(
    command: str,
    args: list[str] | None = None,
    project_dir: str | None = None,
    profiles_dir: str | None = None,
    target: str | None = None,
    env_vars: dict[str, str] | None = None,
    timeout: int = 300,
) -> DbtCommandResult:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_dbt_command_sync(
            command=command,
            args=args,
            project_dir=project_dir,
            profiles_dir=profiles_dir,
            target=target,
            env_vars=env_vars,
            timeout=timeout,
        ),
    )


SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "target", "dbt_packages", "dbt_modules", ".tox", ".mypy_cache",
}


def discover_dbt_projects(
    root_dir: str | None = None, max_depth: int = 3
) -> list[DbtProjectInfo]:
    if root_dir is None:
        root_dir = os.getcwd()

    root = Path(root_dir).resolve()
    projects: list[DbtProjectInfo] = []

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(current.iterdir())
        except PermissionError:
            return

        if (current / "dbt_project.yml").exists():
            projects.append(parse_dbt_project_yml(str(current)))
            return

        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS:
                _walk(entry, depth + 1)

    _walk(root, 0)
    projects.sort(
        key=lambda p: (Path(p.project_dir) / "dbt_project.yml").stat().st_mtime
        if (Path(p.project_dir) / "dbt_project.yml").exists()
        else 0,
        reverse=True,
    )
    return projects


def scaffold_dbt_project(
    project_name: str,
    parent_dir: str | None = None,
    adapter: str = "duckdb",
) -> tuple[str, list[str]]:
    if parent_dir is None:
        parent_dir = os.getcwd()

    if project_name == ".":
        project_dir = Path(parent_dir)
        safe_name = Path(parent_dir).name.replace("-", "_").replace(" ", "_")
    else:
        project_dir = Path(parent_dir) / project_name
        safe_name = project_name.replace("-", "_").replace(" ", "_")
    project_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []

    dbt_project = {
        "name": safe_name,
        "version": "1.0.0",
        "config-version": 2,
        "profile": safe_name,
        "model-paths": ["models"],
        "analysis-paths": ["analyses"],
        "test-paths": ["tests"],
        "seed-paths": ["seeds"],
        "macro-paths": ["macros"],
        "snapshot-paths": ["snapshots"],
        "clean-targets": ["target", "dbt_packages"],
    }

    adapter_profiles = {
        "duckdb": {
            "type": "duckdb",
            "path": f"{safe_name}.duckdb",
            "threads": 4,
        },
        "postgres": {
            "type": "postgres",
            "host": "localhost",
            "port": 5432,
            "user": "your_user",
            "password": "your_password",
            "dbname": safe_name,
            "schema": "public",
            "threads": 4,
        },
        "snowflake": {
            "type": "snowflake",
            "account": "your_account",
            "user": "your_user",
            "password": "your_password",
            "role": "your_role",
            "database": safe_name.upper(),
            "warehouse": "your_warehouse",
            "schema": "public",
            "threads": 4,
        },
        "bigquery": {
            "type": "bigquery",
            "method": "oauth",
            "project": "your-gcp-project",
            "dataset": safe_name,
            "threads": 4,
        },
        "redshift": {
            "type": "redshift",
            "host": "your-cluster.redshift.amazonaws.com",
            "port": 5439,
            "user": "your_user",
            "password": "your_password",
            "dbname": safe_name,
            "schema": "public",
            "threads": 4,
        },
    }

    profile_name = safe_name
    profiles = {
        profile_name: {
            "target": "dev",
            "outputs": {
                "dev": adapter_profiles.get(adapter, adapter_profiles["duckdb"]),
            },
        }
    }

    import yaml

    # dbt_project.yml
    f = project_dir / "dbt_project.yml"
    f.write_text(yaml.dump(dbt_project, sort_keys=False, default_flow_style=False), encoding="utf-8")
    created.append(str(f))

    # profiles.yml
    f = project_dir / "profiles.yml"
    f.write_text(yaml.dump(profiles, sort_keys=False, default_flow_style=False), encoding="utf-8")
    created.append(str(f))

    # directories with README descriptions so git tracks them
    dir_descriptions = {
        "models/example": "Example dbt models. Add your SQL models here.",
        "analyses": "Ad-hoc analytical queries that compile but are not materialized.",
        "seeds": "CSV files that dbt loads into your warehouse as tables.",
        "tests": "Custom data tests written in SQL.",
        "macros": "Reusable Jinja macros and SQL helpers.",
        "snapshots": "Slowly changing dimension (SCD) snapshot definitions.",
        "notebooks": "SignalPilot notebooks for data exploration and analysis.",
    }
    for d, desc in dir_descriptions.items():
        (project_dir / d).mkdir(parents=True, exist_ok=True)
        readme = project_dir / d / "README.md"
        if not readme.exists():
            readme.write_text(f"# {d.split('/')[-1].title()}\n\n{desc}\n", encoding="utf-8")
            created.append(str(readme))

    # starter model
    f = project_dir / "models" / "example" / "my_first_model.sql"
    f.write_text("select 1 as id, 'hello' as greeting\n", encoding="utf-8")
    created.append(str(f))

    # schema.yml
    f = project_dir / "models" / "schema.yml"
    schema = {
        "version": 2,
        "models": [
            {
                "name": "my_first_model",
                "description": "A starter model",
                "columns": [
                    {"name": "id", "description": "The primary key"},
                    {"name": "greeting", "description": "A greeting message"},
                ],
            }
        ],
    }
    f.write_text(yaml.dump(schema, sort_keys=False, default_flow_style=False), encoding="utf-8")
    created.append(str(f))

    # packages.yml
    f = project_dir / "packages.yml"
    f.write_text("packages: []\n", encoding="utf-8")
    created.append(str(f))

    # .gitignore
    f = project_dir / ".gitignore"
    f.write_text("target/\ndbt_packages/\nlogs/\n*.duckdb\n*.duckdb.wal\n", encoding="utf-8")
    created.append(str(f))

    # intro notebook
    f = project_dir / "notebooks" / "intro.py"
    f.write_text(
        _INTRO_NOTEBOOK.format(name=safe_name),
        encoding="utf-8",
    )
    created.append(str(f))

    # charting demo notebook
    f = project_dir / "notebooks" / "charting.py"
    f.write_text(_CHARTING_NOTEBOOK, encoding="utf-8")
    created.append(str(f))

    return str(project_dir), created


# ── Notebook templates ─────────────────────────────────────────────

_INTRO_NOTEBOOK = '''\
import signalpilot

__generated_with = "0.1.0"
app = signalpilot.App()


@app.cell
def _():
    import signalpilot as sp
    return (sp,)


@app.cell
def _(sp):
    sp.md("""
    # Welcome to {name}

    This is your project notebook. Use it to explore data, run queries,
    and build analyses alongside your dbt models.

    ## Getting started

    1. Connect to your data warehouse using the connections panel
    2. Run SQL queries with `db.query()`
    3. Build dbt models in the `models/` directory
    4. Check out **charting.py** for a demo of all visualization types
    """)


@app.cell
def _(sp):
    sp.vstack([
        sp.md("## Your connections"),
        sp.callout("Run this cell to see available data connections.", kind="info"),
    ])


@app.cell
def _(sp):
    sp.init()
    conns = sp.connections()
    conns
    return (conns,)


@app.cell
def _(sp):
    sp.md("""
    ## Next steps

    ```python
    db = sp.connect("your_connection")
    db.tables()
    df = db.query("SELECT * FROM your_table LIMIT 100")
    sp.ui.table(df)
    ```
    """)


if __name__ == "__main__":
    app.run()
'''

_CHARTING_NOTEBOOK = '''\
import signalpilot

__generated_with = "0.1.0"
app = signalpilot.App()


@app.cell
def _():
    import signalpilot as sp
    import pandas as pd
    import numpy as np
    import altair as alt
    return (sp, pd, np, alt)


@app.cell
def _(sp):
    sp.md("""
    # Charting & Visualization Demo

    Every chart type, widget, and layout element available in SignalPilot.
    All data is generated — no database connection required.
    """)


@app.cell
def _(pd, np):
    np.random.seed(42)
    _n = 60
    sample_df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=_n, freq="D"),
        "revenue": np.cumsum(np.random.uniform(800, 3000, _n)).round(2),
        "orders": np.random.randint(10, 200, _n),
        "category": np.random.choice(["Electronics", "Clothing", "Food", "Books"], _n),
        "region": np.random.choice(["North", "South", "East", "West"], _n),
        "score": np.random.normal(75, 15, _n).round(1),
    })
    return (sample_df,)


@app.cell
def _(sp):
    sp.md("## Stat Cards")


@app.cell
def _(sp):
    sp.hstack([
        sp.stat(value="1,234", label="Users", caption="+12%", direction="increase"),
        sp.stat(value="$56K", label="Revenue", caption="+8%", direction="increase"),
        sp.stat(value="98.5%", label="Uptime", caption="-0.2%", direction="decrease"),
        sp.stat(value="42ms", label="Latency", caption="-5ms", direction="decrease", target_direction="decrease"),
    ])


@app.cell
def _(sp):
    sp.md("## Callouts")


@app.cell
def _(sp):
    sp.vstack([
        sp.callout("This is an **info** callout — use for tips and context.", kind="info"),
        sp.callout("This is a **warn** callout — use for important notices.", kind="warn"),
        sp.callout("This is a **danger** callout — use for errors and warnings.", kind="danger"),
        sp.callout("This is a **success** callout — use for confirmations.", kind="success"),
    ])


@app.cell
def _(sp):
    sp.md("## Altair Charts")


@app.cell
def _(sp, sample_df, alt):
    _chart = alt.Chart(sample_df).mark_bar().encode(
        x=alt.X("category:N", title="Category"),
        y=alt.Y("sum(revenue):Q", title="Total Revenue"),
        color="category:N",
    ).properties(width=500, height=300, title="Revenue by Category")
    sp.vstack([sp.md("### Bar Chart"), _chart])


@app.cell
def _(sp, sample_df, alt):
    _line = alt.Chart(sample_df).mark_line(point=True).encode(
        x="date:T",
        y="revenue:Q",
        tooltip=["date:T", "revenue:Q", "category:N"],
    ).properties(width=600, height=300, title="Cumulative Revenue Over Time")
    sp.vstack([sp.md("### Line Chart"), _line])


@app.cell
def _(sp, sample_df, alt):
    _scatter = alt.Chart(sample_df).mark_circle(size=60).encode(
        x="orders:Q",
        y="revenue:Q",
        color="category:N",
        tooltip=["date:T", "orders:Q", "revenue:Q", "category:N"],
    ).properties(width=500, height=300, title="Orders vs Revenue")
    sp.vstack([sp.md("### Scatter Plot"), _scatter])


@app.cell
def _(sp, sample_df, alt):
    _heatmap = alt.Chart(sample_df).mark_rect().encode(
        x=alt.X("region:N"),
        y=alt.Y("category:N"),
        color=alt.Color("mean(score):Q", scale=alt.Scale(scheme="blues")),
        tooltip=["region:N", "category:N", "mean(score):Q"],
    ).properties(width=400, height=250, title="Avg Score by Region × Category")
    sp.vstack([sp.md("### Heatmap"), _heatmap])


@app.cell
def _(sp):
    sp.md("## Data Tables")


@app.cell
def _(sp, sample_df):
    sp.vstack([
        sp.md("### Interactive Table (`sp.ui.table`)"),
        sp.ui.table(sample_df.head(10)),
    ])


@app.cell
def _(sp, sample_df):
    sp.vstack([
        sp.md("### Data Explorer (`sp.ui.dataframe`)"),
        sp.md("Filter, sort, search, and transform data interactively."),
        sp.ui.dataframe(sample_df),
    ])


@app.cell
def _(sp):
    sp.md("## Layout Elements")


@app.cell
def _(sp):
    sp.accordion({
        "What is SignalPilot?": sp.md("An open-source platform for governed AI database access and notebook-driven analytics."),
        "How do I connect?": sp.md("Use `sp.connect('name')` with a connection configured in the connections panel."),
        "Where are my models?": sp.md("dbt models live in the `models/` directory. Run them with the build button."),
    })


@app.cell
def _(sp, sample_df):
    sp.tabs({
        "Summary": sp.vstack([
            sp.md(f"**{len(sample_df)}** rows, **{len(sample_df.columns)}** columns"),
            sample_df.describe(),
        ]),
        "By Category": sp.ui.table(
            sample_df.groupby("category").agg({"revenue": "sum", "orders": "sum"}).reset_index()
        ),
        "By Region": sp.ui.table(
            sample_df.groupby("region").agg({"revenue": "sum", "orders": "sum"}).reset_index()
        ),
    })


@app.cell
def _(sp):
    sp.tree({
        "project/": {
            "models/": {"staging/": ["stg_orders.sql"], "marts/": ["fct_revenue.sql"]},
            "notebooks/": ["intro.py", "charting.py"],
            "dbt_project.yml": None,
        }
    })


@app.cell
def _(sp):
    sp.md("## Interactive Widgets")


@app.cell
def _(sp):
    chart_type = sp.ui.dropdown(
        options=["Bar", "Line", "Scatter", "Heatmap"],
        value="Bar",
        label="Chart type",
    )
    chart_type
    return (chart_type,)


@app.cell
def _(sp, sample_df, alt, chart_type):
    _type = chart_type.value
    if _type == "Bar":
        _c = alt.Chart(sample_df).mark_bar().encode(x="category:N", y="sum(orders):Q", color="category:N")
    elif _type == "Line":
        _c = alt.Chart(sample_df).mark_line().encode(x="date:T", y="orders:Q")
    elif _type == "Scatter":
        _c = alt.Chart(sample_df).mark_circle().encode(x="orders:Q", y="score:Q", color="region:N")
    else:
        _c = alt.Chart(sample_df).mark_rect().encode(x="region:N", y="category:N", color="count():Q")
    sp.vstack([
        sp.md(f"### Reactive {_type} Chart"),
        _c.properties(width=500, height=280),
    ])


@app.cell
def _(sp):
    vis_slider = sp.ui.slider(start=1, stop=60, value=30, label="Days to show")
    vis_slider
    return (vis_slider,)


@app.cell
def _(sp, sample_df, vis_slider):
    _subset = sample_df.head(vis_slider.value)
    sp.vstack([
        sp.md(f"Showing **{vis_slider.value}** of {len(sample_df)} days"),
        sp.ui.table(_subset),
    ])


@app.cell
def _(sp):
    sp.md("## Mermaid Diagrams")


@app.cell
def _(sp):
    sp.mermaid("""
    graph LR
        A[Frontend] -->|WebSocket| B[Gateway]
        B -->|Proxy| C[Notebook Pod]
        C -->|kernel-ready| A
        B -->|SQL| D[(Database)]
        D -->|Results| B
    """)


if __name__ == "__main__":
    app.run()
'''


def clone_git_repo(
    git_url: str,
    target_dir: str | None = None,
    branch: str | None = None,
    timeout: int = 120,
) -> tuple[bool, str, str]:
    git_exe = shutil.which("git")
    if not git_exe:
        return False, "", "git executable not found. Install git first."

    repo_name = git_url.rstrip("/").split("/")[-1].replace(".git", "")
    if target_dir is None:
        target_dir = os.path.join(os.getcwd(), repo_name)

    cmd = [git_exe, "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([git_url, target_dir])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, target_dir, ""
        return False, "", result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Clone timed out after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def get_manifest(project_dir: str) -> dict[str, Any] | None:
    manifest_path = Path(project_dir) / "target" / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        LOGGER.warning("Failed to read manifest.json: %s", e)
        return None


def get_run_results(project_dir: str) -> dict[str, Any] | None:
    results_path = Path(project_dir) / "target" / "run_results.json"
    if not results_path.exists():
        return None
    try:
        with open(results_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        LOGGER.warning("Failed to read run_results.json: %s", e)
        return None


def get_graph_summary(project_dir: str) -> dict[str, Any] | None:
    graph_path = Path(project_dir) / "target" / "graph_summary.json"
    if not graph_path.exists():
        return None
    try:
        with open(graph_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        LOGGER.warning("Failed to read graph_summary.json: %s", e)
        return None


def list_models(project_dir: str) -> list[dict[str, Any]]:
    manifest = get_manifest(project_dir)
    if not manifest:
        return []

    models = []
    for unique_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") == "model":
            models.append(
                {
                    "unique_id": unique_id,
                    "name": node.get("name"),
                    "path": node.get("original_file_path"),
                    "materialized": node.get("config", {}).get(
                        "materialized", "view"
                    ),
                    "schema": node.get("schema"),
                    "database": node.get("database"),
                    "description": node.get("description", ""),
                    "depends_on": node.get("depends_on", {}).get("nodes", []),
                    "tags": node.get("tags", []),
                }
            )
    return models


def get_model_name_from_path(file_path: str, project_dir: str | None = None) -> str | None:
    """Extract dbt model name from a file path.

    Example: /path/to/models/staging/stg_users.sql -> stg_users
    """
    p = Path(file_path)
    if p.suffix != ".sql":
        return None
    return p.stem


def is_dbt_model_file(file_path: str, project_dir: str | None = None) -> bool:
    """Check if a file is a dbt model (SQL file in a models/ directory)."""
    normalized = file_path.replace("\\", "/")
    return ".sql" in normalized and "/models/" in normalized


def compile_model(
    model_name: str,
    project_dir: str | None = None,
) -> tuple[bool, str, str]:
    """Compile a single dbt model and return the compiled SQL.

    Returns: (success, compiled_sql, error)
    """
    result = run_dbt_command_sync(
        command="compile",
        args=["--select", model_name],
        project_dir=project_dir,
    )

    if not result.success:
        return False, "", result.stderr or result.stdout

    # Try to read compiled SQL from target/compiled/
    if project_dir:
        compiled_dir = Path(project_dir) / "target" / "compiled"
        if compiled_dir.exists():
            # Search for the compiled file
            for compiled_file in compiled_dir.rglob(f"{model_name}.sql"):
                try:
                    return True, compiled_file.read_text(encoding="utf-8"), ""
                except Exception:
                    pass

    # Fallback: return stdout which may contain the compiled SQL
    return True, result.stdout, ""


def preview_model(
    model_name: str,
    project_dir: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Run dbt show for a model and parse results into structured data.

    Returns: { success, columns: [{name, type}], rows: [[...]], rowCount, error }
    """
    result = run_dbt_command_sync(
        command="show",
        args=["--select", model_name, "--limit", str(limit), "--output", "json"],
        project_dir=project_dir,
    )

    if not result.success:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "rowCount": 0,
            "error": result.stderr or result.stdout,
        }

    # Parse JSON output from dbt show --output json
    columns, rows = _parse_dbt_show_json(result.stdout)
    if not columns:
        # Fallback to text parsing
        columns, rows = _parse_dbt_show_output(result.stdout)

    return {
        "success": True,
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "error": None,
    }


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def _parse_dbt_show_json(
    stdout: str,
) -> tuple[list[dict[str, str]], list[list[str]]]:
    """Parse dbt show --output json into columns and rows."""
    stdout = _strip_ansi(stdout)
    # Extract JSON array from stdout (skip log lines)
    json_start = stdout.find("[")
    json_obj_start = stdout.find('{"node"')

    if json_obj_start >= 0:
        # Format: {"node": "model_name", "show": [...]}
        try:
            obj_str = stdout[json_obj_start:]
            # Find matching closing brace
            brace_count = 0
            end = 0
            for i, c in enumerate(obj_str):
                if c == "{":
                    brace_count += 1
                elif c == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            data = json.loads(obj_str[:end])
            records = data.get("show", [])
            if not records:
                return [], []
            columns = [{"name": k, "type": _infer_type(v)} for k, v in records[0].items()]
            rows = [[str(v) for v in record.values()] for record in records]
            return columns, rows
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    if json_start >= 0:
        # Format: plain JSON array [...]
        try:
            bracket_count = 0
            end = 0
            for i, c in enumerate(stdout[json_start:]):
                if c == "[":
                    bracket_count += 1
                elif c == "]":
                    bracket_count -= 1
                    if bracket_count == 0:
                        end = json_start + i + 1
                        break
            records = json.loads(stdout[json_start:end])
            if not records:
                return [], []
            columns = [{"name": k, "type": _infer_type(v)} for k, v in records[0].items()]
            rows = [[str(v) for v in record.values()] for record in records]
            return columns, rows
        except (json.JSONDecodeError, IndexError):
            pass

    return [], []


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _parse_dbt_show_output(
    stdout: str,
) -> tuple[list[dict[str, str]], list[list[str]]]:
    """Parse dbt show's tabular output into columns and rows."""
    lines = stdout.strip().splitlines()

    # Find the header separator line (looks like "| --- | --- |" or similar)
    header_idx = -1
    separator_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and "---" in stripped:
            separator_idx = i
            header_idx = i - 1
            break

    if header_idx < 0 or separator_idx < 0:
        # Try alternative: find lines with | delimiters
        data_lines = [l for l in lines if "|" in l and "---" not in l]
        if len(data_lines) >= 2:
            header_line = data_lines[0]
            col_names = [c.strip() for c in header_line.split("|") if c.strip()]
            columns = [{"name": n, "type": "string"} for n in col_names]
            rows = []
            for dl in data_lines[1:]:
                vals = [c.strip() for c in dl.split("|") if c.strip()]
                if vals:
                    rows.append(vals)
            return columns, rows
        return [], []

    # Parse header
    header_line = lines[header_idx]
    col_names = [c.strip() for c in header_line.split("|") if c.strip()]
    columns = [{"name": n, "type": "string"} for n in col_names]

    # Parse data rows (everything after the separator)
    rows = []
    for line in lines[separator_idx + 1:]:
        stripped = line.strip()
        if not stripped or not stripped.startswith("|"):
            continue
        vals = [c.strip() for c in stripped.split("|") if c.strip()]
        if vals:
            rows.append(vals)

    return columns, rows
