"""Alembic async migration environment for the Workspaces API.

Uses WORKSPACES_DATABASE_URL from the environment. The workspaces schema is
pre-created before run_migrations() so that Alembic can create the
workspaces.alembic_version table on a fresh database (Alembic creates the
version table BEFORE the migration body runs, so the schema must exist first).
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import workspaces_api.models  # noqa: F401 — registers ORM classes on Base.metadata
from workspaces_api.db import Base

config = context.config

target_metadata = Base.metadata


def _get_database_url() -> str:
    url = os.environ.get("WORKSPACES_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "WORKSPACES_DATABASE_URL environment variable is required for Alembic."
        )
    return url


def do_run_migrations(connection) -> None:  # type: ignore[type-arg]
    """Execute migrations on a synchronous connection.

    Creates the workspaces schema BEFORE run_migrations() so that
    workspaces.alembic_version can be created on a fresh database.
    """
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS workspaces"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="workspaces",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = _get_database_url()
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


def run_migrations_offline() -> None:
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="workspaces",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
