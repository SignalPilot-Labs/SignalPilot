"""Alembic migration chain must be 1-1 with the legacy startup schema.

The gateway historically built its schema at startup via SQLAlchemy
create_all plus a chain of idempotent "ensure" ALTERs (now frozen in
gateway/db/legacy_bootstrap.py). The Alembic migration chain in
gateway/db/migrations/versions/ replaces that mechanism and must produce a
byte-identical schema: same tables, columns (type, nullability, default),
indexes, and constraints.

This test builds both schemas into scratch databases on a live Postgres and
diffs them via the catalogs. It needs an admin DSN with CREATEDB rights:

    SP_TEST_MIGRATION_PG_ADMIN_DSN=postgresql://user:pass@127.0.0.1:5601/postgres

Skipped cleanly when the variable is unset (e.g. in CI without Postgres).
"""

from __future__ import annotations

import os

import pytest

ADMIN_DSN = os.environ.get("SP_TEST_MIGRATION_PG_ADMIN_DSN", "")

pytestmark = pytest.mark.skipif(
    not ADMIN_DSN,
    reason="SP_TEST_MIGRATION_PG_ADMIN_DSN not set — needs a live Postgres with CREATEDB",
)

LEGACY_DB = "sp_test_migration_parity_legacy"
ALEMBIC_DB = "sp_test_migration_parity_alembic"

# The Alembic version table exists only on the Alembic side by design.
_EXCLUDED_TABLES = ("gateway_alembic_version",)


def _replace_dbname(dsn: str, dbname: str) -> str:
    base, _, _ = dsn.rpartition("/")
    query = ""
    if "?" in dsn:
        query = "?" + dsn.split("?", 1)[1]
    return f"{base}/{dbname}{query}"


@pytest.fixture(scope="module")
def scratch_databases():
    psycopg2 = pytest.importorskip("psycopg2")
    conn = psycopg2.connect(ADMIN_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    for db in (LEGACY_DB, ALEMBIC_DB):
        cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
        cur.execute(f'CREATE DATABASE "{db}"')
    yield {
        "legacy": _replace_dbname(ADMIN_DSN, LEGACY_DB),
        "alembic": _replace_dbname(ADMIN_DSN, ALEMBIC_DB),
    }
    for db in (LEGACY_DB, ALEMBIC_DB):
        cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
    conn.close()


def _snapshot(dsn: str) -> dict[str, dict]:
    """Snapshot columns, indexes, and constraints of the public schema."""
    import psycopg2

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    excluded = ", ".join(f"'{t}'" for t in _EXCLUDED_TABLES)
    cur.execute(
        "SELECT table_name, column_name, data_type,"
        "       coalesce(character_maximum_length, -1),"
        "       is_nullable, coalesce(column_default, ''),"
        "       coalesce(numeric_precision, -1), coalesce(datetime_precision, -1) "
        "FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name NOT IN ({excluded}) "
        "ORDER BY table_name, column_name"
    )
    columns = {(r[0], r[1]): tuple(r[2:]) for r in cur.fetchall()}
    cur.execute(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        f"WHERE schemaname = 'public' AND tablename NOT IN ({excluded}) "
        "ORDER BY 1, 2"
    )
    indexes = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    cur.execute(
        "SELECT rel.relname, con.conname, pg_get_constraintdef(con.oid) "
        "FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid = con.conrelid "
        "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
        f"WHERE ns.nspname = 'public' AND rel.relname NOT IN ({excluded}) "
        "ORDER BY 1, 2"
    )
    constraints = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    conn.close()
    return {"columns": columns, "indexes": indexes, "constraints": constraints}


def _diff(kind: str, legacy: dict, alembic: dict) -> list[str]:
    problems = []
    for key in sorted(set(legacy) | set(alembic)):
        if key not in alembic:
            problems.append(f"{kind} missing from alembic schema: {key} = {legacy[key]}")
        elif key not in legacy:
            problems.append(f"{kind} only in alembic schema: {key} = {alembic[key]}")
        elif legacy[key] != alembic[key]:
            problems.append(
                f"{kind} differs: {key}\n  legacy:  {legacy[key]}\n  alembic: {alembic[key]}"
            )
    return problems


async def _build_legacy(dsn: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from gateway.db.legacy_bootstrap import run_legacy_bootstrap

    url = dsn.replace("postgresql://", "postgresql+asyncpg://", 1).split("?")[0]
    engine = create_async_engine(url)
    try:
        await run_legacy_bootstrap(engine)
    finally:
        await engine.dispose()


class TestAlembicSchemaParity:
    async def test_alembic_schema_is_identical_to_legacy(self, scratch_databases) -> None:
        """Fresh alembic upgrade head == legacy create_all + ensure chain."""
        import asyncio

        from gateway.db.migrate import upgrade_to_head

        await _build_legacy(scratch_databases["legacy"])
        await asyncio.to_thread(upgrade_to_head, scratch_databases["alembic"])

        legacy = _snapshot(scratch_databases["legacy"])
        alembic = _snapshot(scratch_databases["alembic"])

        problems = (
            _diff("column", legacy["columns"], alembic["columns"])
            + _diff("index", legacy["indexes"], alembic["indexes"])
            + _diff("constraint", legacy["constraints"], alembic["constraints"])
        )
        assert not problems, "schemas are not 1-1:\n" + "\n".join(problems)

    async def test_pre_alembic_database_can_be_stamped_and_upgraded(self, scratch_databases) -> None:
        """A legacy-built database stamps at head and then upgrades as a no-op."""
        import asyncio

        import psycopg2

        from gateway.db.migrate import VERSION_TABLE, stamp_head, upgrade_to_head

        await asyncio.to_thread(stamp_head, scratch_databases["legacy"])
        await asyncio.to_thread(upgrade_to_head, scratch_databases["legacy"])

        conn = psycopg2.connect(scratch_databases["legacy"])
        cur = conn.cursor()
        cur.execute(f"SELECT version_num FROM {VERSION_TABLE}")
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 1

    async def test_upgrade_is_idempotent_on_managed_database(self, scratch_databases) -> None:
        """Running upgrade head twice leaves the alembic database unchanged."""
        import asyncio

        from gateway.db.migrate import upgrade_to_head

        before = _snapshot(scratch_databases["alembic"])
        await asyncio.to_thread(upgrade_to_head, scratch_databases["alembic"])
        after = _snapshot(scratch_databases["alembic"])
        assert before == after
