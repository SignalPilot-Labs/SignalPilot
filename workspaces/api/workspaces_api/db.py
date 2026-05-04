"""Async SQLAlchemy engine and session factory for the Workspaces API.

Schema is always "workspaces" in production Postgres. For SQLite unit tests,
create the engine with execution_options={"schema_translate_map": {"workspaces": None}}
so SQLAlchemy rewrites all workspaces.* qualified names to unqualified at
statement-prepare time. There is NO _schema_for_dialect() helper — the ORM
MetaData(schema="workspaces") is the single source of truth.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

WORKSPACES_SCHEMA = "workspaces"

# MetaData(schema="workspaces") — canonical schema declaration; test engine uses
# execution_options={"schema_translate_map": {"workspaces": None}} instead.
metadata = MetaData(schema=WORKSPACES_SCHEMA)


class Base(DeclarativeBase):
    metadata = metadata


def make_engine(
    url: str,
    *,
    schema_translate_map: dict[str | None, str | None] | None = None,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the given URL.

    Args:
        url: SQLAlchemy async database URL.
        schema_translate_map: Optional schema name translation map. Pass
            {"workspaces": None} for SQLite to strip the schema prefix.
    """
    kwargs: dict[str, Any] = {}
    if schema_translate_map is not None:
        kwargs["execution_options"] = {"schema_translate_map": schema_translate_map}
    return create_async_engine(url, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a database session and closes it after use."""
    async with session_factory() as session:
        yield session
