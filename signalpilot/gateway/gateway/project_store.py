"""Project store: CRUD and scaffolding for dbt projects. Persists to projects.json.

DEPRECATED: This module-level file-backed singleton is NOT org-scoped and has no
remaining callers after round 3. All MCP project tools (create_project, list_projects,
get_project) now use Store.create_project / Store.list_projects / Store.get_project.
This module is retained to keep the round-3 diff small; delete in a follow-up round
once confirmed no remaining imports exist.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Callable

from .models import (
    ConnectionInfo,
    ProjectCreate,
    ProjectInfo,
    ProjectStorage,
    ProjectUpdate,
)

# ─── Templates ────────────────────────────────────────────────────────────────

_DBT_PROJECT_YML_TEMPLATE = """\
name: '{name}'
version: '1.0.0'
config-version: 2
profile: '{name}'

model-paths: ["models"]
analysis-paths: ["analyses"]
test-paths: ["tests"]
seed-paths: ["seeds"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

clean-targets:
  - "target"
  - "dbt_packages"
"""

_PACKAGES_YML_TEMPLATE = """\
packages: []
"""

_PROFILES_DUCKDB = """\
{name}:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: '{database}'
"""

_PROFILES_POSTGRES = """\
{name}:
  target: dev
  outputs:
    dev:
      type: postgres
      host: '{host}'
      port: {port}
      user: '{username}'
      dbname: '{database}'
      schema: public
"""

_PROFILES_SNOWFLAKE = """\
{name}:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: '{account}'
      user: '{username}'
      database: '{database}'
      warehouse: '{warehouse}'
      schema: public
      role: '{role}'
"""

_PROFILES_BIGQUERY = """\
{name}:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: service-account
      project: '{project}'
      dataset: '{dataset}'
      location: '{location}'
"""

_PROFILES_PLACEHOLDER = """\
# TODO: Configure profile for {db_type}
# See https://docs.getdbt.com/docs/core/connect-data-platform
{name}:
  target: dev
  outputs:
    dev:
      type: '{db_type}'
"""

_SCAFFOLD_DIRS = [
    "models/staging",
    "models/marts",
    "analyses",
    "tests",
    "seeds",
    "macros",
    "snapshots",
]

_GITKEEP_DIRS = [
    "models/staging",
    "models/marts",
]


# ─── Pure helpers ─────────────────────────────────────────────────────────────

def _generate_dbt_project_yml(project_name: str) -> str:
    """Return dbt_project.yml content for a new project."""
    return _DBT_PROJECT_YML_TEMPLATE.format(name=project_name)


def _generate_profiles_yml(project_name: str, connection: ConnectionInfo) -> str:
    """Return profiles.yml content based on the connection's db_type."""
    db = connection.db_type
    if db == "duckdb":
        return _PROFILES_DUCKDB.format(
            name=project_name,
            database=connection.database or ":memory:",
        )
    if db == "postgres":
        return _PROFILES_POSTGRES.format(
            name=project_name,
            host=connection.host or "localhost",
            port=connection.port or 5432,
            username=connection.username or "",
            database=connection.database or "",
        )
    if db == "snowflake":
        return _PROFILES_SNOWFLAKE.format(
            name=project_name,
            account=connection.account or "",
            username=connection.username or "",
            database=connection.database or "",
            warehouse=connection.warehouse or "",
            role=connection.role or "",
        )
    if db == "bigquery":
        return _PROFILES_BIGQUERY.format(
            name=project_name,
            project=connection.project or "",
            dataset=connection.dataset or "",
            location=connection.location or "US",
        )
    return _PROFILES_PLACEHOLDER.format(name=project_name, db_type=db)


# ─── ProjectStore ─────────────────────────────────────────────────────────────

class ProjectStore:
    """Manages dbt project lifecycle: create, read, update, delete.

    Public API:
        list_projects, get_project, create_project, update_project, delete_project

    Constructor args:
        projects_file: Path to projects.json
        data_dir: Base data directory (~/.signalpilot)
        connection_getter: Callable that resolves a connection name to ConnectionInfo
    """

    def __init__(
        self,
        projects_file: Path,
        data_dir: Path,
        connection_getter: Callable[[str], ConnectionInfo | None],
    ) -> None:
        self._projects_file = projects_file
        self._data_dir = data_dir
        self._get_connection = connection_getter

    def _load(self) -> dict:
        """Load projects.json via shared infra."""
        from .store import _load_json
        return _load_json(self._projects_file, {})

    def _save(self, data: dict) -> None:
        """Write projects.json via shared infra."""
        from .store import _save_json
        _save_json(self._projects_file, data)

    def _managed_dir(self, name: str) -> Path:
        """Return the managed project directory path."""
        return self._data_dir / "projects" / name

    def _persist(self, info: ProjectInfo, data: dict) -> ProjectInfo:
        """Save a ProjectInfo to the data dict and write to disk."""
        data[info.name] = info.model_dump()
        self._save(data)
        return info

    def _build_info(
        self,
        proj: ProjectCreate,
        connection: ConnectionInfo,
        project_dir: Path,
        storage: ProjectStorage,
        *,
        git_remote: str | None = None,
        git_branch: str | None = None,
        dbt_cloud_account_id: str | None = None,
        dbt_cloud_project_id: str | None = None,
    ) -> ProjectInfo:
        """Construct a ProjectInfo from common fields."""
        return ProjectInfo(
            id=str(uuid.uuid4()),
            name=proj.name,
            connection_name=proj.connection_name,
            project_dir=str(project_dir),
            storage=storage,
            source=proj.source,
            db_type=connection.db_type,
            git_remote=git_remote,
            git_branch=git_branch,
            dbt_cloud_account_id=dbt_cloud_account_id,
            dbt_cloud_project_id=dbt_cloud_project_id,
            description=proj.description,
            tags=proj.tags,
        )

    # ─── Public API ───────────────────────────────────────────────────────

    def list_projects(self) -> list[ProjectInfo]:
        """Return all registered dbt projects."""
        data = self._load()
        return [ProjectInfo(**v) for v in data.values()]

    def get_project(self, name: str) -> ProjectInfo | None:
        """Return a project by name, or None if not found."""
        data = self._load()
        raw = data.get(name)
        return ProjectInfo(**raw) if raw else None

    def create_project(self, proj: ProjectCreate) -> ProjectInfo:
        """Create and persist a new dbt project."""
        data = self._load()
        if proj.name in data:
            raise ValueError(f"Project '{proj.name}' already exists")

        connection = self._get_connection(proj.connection_name)
        if connection is None:
            raise ValueError(f"Connection '{proj.connection_name}' not found")

        creators = {
            "local": self._create_local,
            "github": self._create_github,
            "dbt-cloud": self._create_dbt_cloud,
        }
        creator = creators.get(proj.source.value, self._create_new)
        return creator(proj, connection, data)

    def update_project(self, name: str, update: ProjectUpdate) -> ProjectInfo | None:
        """Apply a partial update to an existing project."""
        data = self._load()
        if name not in data:
            return None
        existing = data[name]
        for key, value in update.model_dump(exclude_none=True).items():
            existing[key] = value
        data[name] = existing
        self._save(data)
        return ProjectInfo(**existing)

    def delete_project(self, name: str) -> bool:
        """Remove a project. If managed, also delete the project directory."""
        data = self._load()
        if name not in data:
            return False
        info = ProjectInfo(**data[name])
        if info.storage == ProjectStorage.managed:
            project_dir = Path(info.project_dir)
            if project_dir.exists():
                shutil.rmtree(project_dir)
        del data[name]
        self._save(data)
        return True

    # ─── Private creators ─────────────────────────────────────────────────

    def _create_new(
        self, proj: ProjectCreate, connection: ConnectionInfo, data: dict
    ) -> ProjectInfo:
        """Scaffold a fresh dbt project."""
        project_dir = self._managed_dir(proj.name)
        self._scaffold(project_dir, proj.name, connection)
        info = self._build_info(proj, connection, project_dir, ProjectStorage.managed)
        return self._persist(info, data)

    def _create_local(
        self, proj: ProjectCreate, connection: ConnectionInfo, data: dict
    ) -> ProjectInfo:
        """Link or copy an existing local dbt project."""
        local = Path(proj.local_path or "")
        if not local.exists() or not (local / "dbt_project.yml").exists():
            raise ValueError(f"Path '{local}' does not exist or lacks dbt_project.yml")

        if proj.link_mode == "copy":
            project_dir = self._managed_dir(proj.name)
            shutil.copytree(str(local), str(project_dir), dirs_exist_ok=True)
            storage = ProjectStorage.managed
        else:
            project_dir = local
            storage = ProjectStorage.linked

        info = self._build_info(proj, connection, project_dir, storage)
        return self._persist(info, data)

    def _create_github(
        self, proj: ProjectCreate, connection: ConnectionInfo, data: dict
    ) -> ProjectInfo:
        """Clone a GitHub repo into a managed project."""
        if not proj.git_url:
            raise ValueError("git_url is required for GitHub import")

        branch = proj.git_branch or "main"
        project_dir = self._managed_dir(proj.name)
        self._clone_and_wire(proj.git_url, branch, project_dir, proj.name, connection)

        info = self._build_info(
            proj, connection, project_dir, ProjectStorage.managed,
            git_remote=proj.git_url, git_branch=branch,
        )
        return self._persist(info, data)

    def _create_dbt_cloud(
        self, proj: ProjectCreate, connection: ConnectionInfo, data: dict
    ) -> ProjectInfo:
        """Clone the repo backing a dbt Cloud project."""
        if not proj.git_url:
            raise ValueError("git_url is required for dbt Cloud import (discovered via API)")

        branch = proj.git_branch or "main"
        project_dir = self._managed_dir(proj.name)
        self._clone_and_wire(proj.git_url, branch, project_dir, proj.name, connection)

        info = self._build_info(
            proj, connection, project_dir, ProjectStorage.managed,
            git_remote=proj.git_url, git_branch=branch,
            dbt_cloud_account_id=proj.dbt_cloud_account_id,
            dbt_cloud_project_id=proj.dbt_cloud_project_id,
        )
        return self._persist(info, data)

    # ─── Private helpers ──────────────────────────────────────────────────

    def _scaffold(self, project_dir: Path, project_name: str, connection: ConnectionInfo) -> None:
        """Create directory structure and config files for a new dbt project."""
        project_dir.mkdir(parents=True, exist_ok=True)
        for d in _SCAFFOLD_DIRS:
            (project_dir / d).mkdir(parents=True, exist_ok=True)
        for d in _GITKEEP_DIRS:
            (project_dir / d / ".gitkeep").touch()
        (project_dir / "dbt_project.yml").write_text(_generate_dbt_project_yml(project_name))
        (project_dir / "profiles.yml").write_text(_generate_profiles_yml(project_name, connection))
        (project_dir / "packages.yml").write_text(_PACKAGES_YML_TEMPLATE)

    def _clone_and_wire(
        self, git_url: str, branch: str, project_dir: Path, project_name: str, connection: ConnectionInfo
    ) -> None:
        """Clone a git repo, validate dbt_project.yml, and generate profiles.yml."""
        import subprocess

        result = subprocess.run(
            ["git", "clone", "--branch", branch, "--depth", "1", git_url, str(project_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise ValueError(f"git clone failed: {result.stderr.strip()}")

        if not (project_dir / "dbt_project.yml").exists():
            shutil.rmtree(project_dir)
            raise ValueError("Cloned repo does not contain dbt_project.yml")

        (project_dir / "profiles.yml").write_text(
            _generate_profiles_yml(project_name, connection)
        )


# ─── Module-level singleton ──────────────────────────────────────────────────

def _lazy_get_connection(name: str) -> ConnectionInfo | None:
    """Lazy import to avoid circular dependency with store.py."""
    from .store import get_connection
    return get_connection(name)


def _get_paths():
    """Import paths from store to avoid circular import at module level."""
    from .store import DATA_DIR, PROJECTS_FILE
    return PROJECTS_FILE, DATA_DIR


_projects_file, _data_dir = _get_paths()
_store = ProjectStore(_projects_file, _data_dir, _lazy_get_connection)

# Public API — module-level functions delegating to singleton
list_projects = _store.list_projects
get_project = _store.get_project
create_project = _store.create_project
update_project = _store.update_project
delete_project = _store.delete_project
