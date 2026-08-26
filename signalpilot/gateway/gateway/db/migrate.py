"""Programmatic Alembic entry points for the gateway schema.

The gateway migrates its schema at startup (init_db). Alembic's command API
is synchronous, so callers run these helpers in a worker thread. The
migration environment (gateway/db/migrations/env.py) normalizes the URL to
the synchronous psycopg2 driver and uses a gateway-specific version table
(gateway_alembic_version) because the backend shares the same database.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

VERSION_TABLE = "gateway_alembic_version"

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def build_alembic_config(database_url: str) -> Config:
    """Build an Alembic config bound to the packaged migration scripts."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["sqlalchemy_url"] = database_url
    return cfg


def upgrade_to_head(database_url: str) -> None:
    """Apply all pending gateway migrations (synchronous; run in a thread)."""
    command.upgrade(build_alembic_config(database_url), "head")
    logger.info("Gateway schema migrated to Alembic head")


def stamp_head(database_url: str) -> None:
    """Mark an existing schema as current without running migrations.

    Used exactly once per pre-Alembic database, after the legacy bootstrap
    has brought it to the shape the migration chain produces.
    """
    command.stamp(build_alembic_config(database_url), "head")
    logger.info("Gateway schema stamped at Alembic head")
