"""Alembic migration environment for the gateway schema.

The gateway runs migrations programmatically at startup (see
gateway.db.migrate); this env also supports the plain alembic CLI. The
database URL is resolved, in order, from:

1. config.attributes["sqlalchemy_url"] — set by programmatic callers
2. the DATABASE_URL environment variable
3. sqlalchemy.url in alembic.ini

Migrations always run over a synchronous psycopg2 connection, even though
the gateway itself uses asyncpg: DDL is sequential and short-lived, and a
sync engine keeps env.py trivial.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from gateway.db.models import GatewayBase

target_metadata = GatewayBase.metadata

config = context.config


def _sync_database_url() -> str:
    """Resolve the database URL and normalize it to the psycopg2 driver."""
    url = config.attributes.get("sqlalchemy_url") or os.environ.get("DATABASE_URL") or ""
    if not url:
        url = config.get_main_option("sqlalchemy.url") or ""
    if not url:
        raise RuntimeError("No database URL: set DATABASE_URL or pass sqlalchemy_url")
    for prefix in ("postgres://", "postgresql://", "postgresql+asyncpg://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg2://" + url[len(prefix) :]
            break
    return url


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without a live connection."""
    context.configure(
        url=_sync_database_url(),
        target_metadata=target_metadata,
        version_table="gateway_alembic_version",
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database."""
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            version_table="gateway_alembic_version",
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(_sync_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table="gateway_alembic_version",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
