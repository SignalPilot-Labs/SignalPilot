"""Projects persistence: CRUD operations for dbt projects, scoped by org_id."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import gateway.store._constants as _constants
import gateway.store.dbt_templates as dbt_templates
from gateway.db.models import GatewayProject
from gateway.models import ConnectionInfo, ProjectCreate, ProjectInfo, ProjectStorage, ProjectUpdate


async def list_projects(session: AsyncSession, *, org_id: str) -> list[ProjectInfo]:
    result = await session.execute(select(GatewayProject).where(GatewayProject.org_id == org_id))
    rows = result.scalars().all()
    return [ProjectInfo(**{c.key: getattr(r, c.key) for c in GatewayProject.__table__.columns}) for r in rows]


async def get_project(session: AsyncSession, *, org_id: str, name: str) -> ProjectInfo | None:
    result = await session.execute(
        select(GatewayProject).where(GatewayProject.org_id == org_id, GatewayProject.name == name)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    return ProjectInfo(**{c.key: getattr(row, c.key) for c in GatewayProject.__table__.columns})


async def create_project(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    proj: ProjectCreate,
    get_connection: Callable[[str], Awaitable[ConnectionInfo | None]],
    get_existing_project: Callable[[str], Awaitable[ProjectInfo | None]],
) -> ProjectInfo:
    existing = await get_existing_project(proj.name)
    if existing:
        raise ValueError(f"Project '{proj.name}' already exists")

    connection = await get_connection(proj.connection_name)
    if connection is None:
        raise ValueError(f"Connection '{proj.connection_name}' not found")

    if proj.source.value == "local":
        info = create_local_project(proj, connection)
    else:
        info = create_new_project(proj, connection)

    db_proj = GatewayProject(
        id=info.id,
        org_id=org_id,
        user_id=user_id,
        name=info.name,
        connection_name=info.connection_name,
        project_dir=info.project_dir,
        storage=info.storage.value if hasattr(info.storage, "value") else info.storage,
        source=info.source.value if hasattr(info.source, "value") else info.source,
        db_type=info.db_type,
        description=info.description,
        tags=info.tags,
    )
    session.add(db_proj)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        orig = str(e.orig) if e.orig is not None else str(e)
        if "uq_gw_proj_org_name" in orig:
            raise ValueError(f"Project '{proj.name}' already exists") from e
        raise
    return info


def create_new_project(proj: ProjectCreate, connection: ConnectionInfo) -> ProjectInfo:
    project_dir = _constants.DATA_DIR / "projects" / proj.name
    project_dir.mkdir(parents=True, exist_ok=True)
    for d in dbt_templates._SCAFFOLD_DIRS:
        (project_dir / d).mkdir(parents=True, exist_ok=True)
    for d in ("models/staging", "models/marts"):
        (project_dir / d / ".gitkeep").touch()
    (project_dir / "dbt_project.yml").write_text(dbt_templates._DBT_PROJECT_YML_TEMPLATE.format(name=proj.name))
    profiles_path = project_dir / "profiles.yml"
    profiles_path.write_text(generate_profiles_yml(proj.name, connection))
    os.chmod(str(profiles_path), 0o600)
    os.chmod(str(project_dir), 0o700)
    (project_dir / "packages.yml").write_text(dbt_templates._PACKAGES_YML_TEMPLATE)
    return ProjectInfo(
        id=str(uuid.uuid4()),
        name=proj.name,
        connection_name=proj.connection_name,
        project_dir=str(project_dir),
        storage=ProjectStorage.managed,
        source=proj.source,
        db_type=connection.db_type,
        description=proj.description,
        tags=proj.tags,
    )


def create_local_project(proj: ProjectCreate, connection: ConnectionInfo) -> ProjectInfo:
    local = Path(proj.local_path or "")
    if not local.exists() or not (local / "dbt_project.yml").exists():
        raise ValueError(f"Path '{local}' does not exist or lacks dbt_project.yml")
    if proj.link_mode == "copy":
        project_dir = _constants.DATA_DIR / "projects" / proj.name
        shutil.copytree(str(local), str(project_dir), dirs_exist_ok=True)
        storage = ProjectStorage.managed
    else:
        project_dir = local
        storage = ProjectStorage.linked
    return ProjectInfo(
        id=str(uuid.uuid4()),
        name=proj.name,
        connection_name=proj.connection_name,
        project_dir=str(project_dir),
        storage=storage,
        source=proj.source,
        db_type=connection.db_type,
        description=proj.description,
        tags=proj.tags,
    )


def generate_profiles_yml(project_name: str, connection: ConnectionInfo) -> str:
    db = connection.db_type
    if db == "duckdb":
        return dbt_templates._PROFILES_DUCKDB.format(name=project_name, database=connection.database or ":memory:")
    if db == "postgres":
        return dbt_templates._PROFILES_POSTGRES.format(
            name=project_name,
            host=connection.host or "localhost",
            port=connection.port or 5432,
            username=connection.username or "",
            database=connection.database or "",
        )
    if db == "snowflake":
        return dbt_templates._PROFILES_SNOWFLAKE.format(
            name=project_name,
            account=connection.account or "",
            username=connection.username or "",
            database=connection.database or "",
            warehouse=connection.warehouse or "",
            role=connection.role or "",
        )
    if db == "bigquery":
        return dbt_templates._PROFILES_BIGQUERY.format(
            name=project_name,
            project=connection.project or "",
            dataset=connection.dataset or "",
            location=getattr(connection, "location", "US") or "US",
        )
    return dbt_templates._PROFILES_PLACEHOLDER.format(name=project_name, db_type=db)


async def update_project(
    session: AsyncSession, *, org_id: str, name: str, update_data: ProjectUpdate
) -> ProjectInfo | None:
    result = await session.execute(
        select(GatewayProject).where(GatewayProject.org_id == org_id, GatewayProject.name == name)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    for key, value in update_data.model_dump(exclude_none=True).items():
        if hasattr(row, key):
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return ProjectInfo(**{c.key: getattr(row, c.key) for c in GatewayProject.__table__.columns})


async def delete_project(session: AsyncSession, *, org_id: str, name: str) -> bool:
    result = await session.execute(
        select(GatewayProject).where(GatewayProject.org_id == org_id, GatewayProject.name == name)
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    if row.storage == "managed" and row.project_dir:
        project_dir = Path(row.project_dir)
        if project_dir.exists():
            shutil.rmtree(project_dir)
    await session.delete(row)
    await session.commit()
    return True
