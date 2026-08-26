"""One-off migration for TLS material left in the plaintext ssl_config column.

Connections created before TLS certs/keys moved into the encrypted credential
extras still carry ca_cert/client_cert/client_key in gateway_connections.ssl_config.
New writes never do, and reads redact them, so those rows are inert — but the
plaintext copy is still on disk and must be swept.

The migration never runs by itself: rewriting credential storage in place is
riskier than refusing to serve, so in cloud mode the gateway fails readiness
while any legacy row remains (see check_plaintext_tls_readiness) and an operator
runs the migration deliberately. Take a database backup first.

    python -m gateway.store.tls_migration            # dry run, all orgs
    python -m gateway.store.tls_migration --apply    # rewrite

or, per org, against a live session:

    from gateway.store.tls_migration import migrate_plaintext_tls_config
    report = await migrate_plaintext_tls_config(store)               # inspect
    report = await migrate_plaintext_tls_config(store, dry_run=False) # apply
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import SSL_SECRET_FIELDS, GatewayConnection
from gateway.models import ConnectionUpdate

logger = logging.getLogger(__name__)

MIGRATION_COMMAND = "python -m gateway.store.tls_migration --apply"

_READINESS_MESSAGE = (
    "Legacy plaintext TLS material is present in gateway_connections.ssl_config "
    "({count} connection(s)). The gateway refuses to serve in cloud mode until it "
    f"is migrated into the encrypted credential extras. Back up the database, then run: {MIGRATION_COMMAND}"
)

# Re-probe while legacy rows remain so readiness recovers as soon as the
# migration lands, without a restart. A clean result is cached for the process
# lifetime: new writes never produce plaintext, so "clean" cannot regress.
_DIRTY_RECHECK_S = 60.0
_readiness_cache: tuple[float, str | None] | None = None


def _plaintext_secret_fields(ssl_config: dict | None) -> list[str]:
    if not ssl_config:
        return []
    return [field for field in SSL_SECRET_FIELDS if ssl_config.get(field)]


async def migrate_plaintext_tls_config(store, dry_run: bool = True) -> dict:
    """Move plaintext TLS material for the store's org into the encrypted extras.

    Returns a report: {"scanned", "affected", "migrated", "failed", "dry_run"}
    where "affected" maps connection name -> the secret field names found.
    """
    result = await store.session.execute(
        select(GatewayConnection).where(GatewayConnection.org_id == store._require_org_id())
    )
    rows = list(result.scalars())

    affected: dict[str, list[str]] = {}
    for row in rows:
        fields = _plaintext_secret_fields(row.ssl_config)
        if fields:
            affected[row.name] = fields

    report: dict = {
        "scanned": len(rows),
        "affected": affected,
        "migrated": [],
        "failed": {},
        "dry_run": dry_run,
    }
    if dry_run:
        return report

    for row in rows:
        if row.name not in affected:
            continue
        full_ssl_config = dict(row.ssl_config or {})
        try:
            # update_connection re-encrypts the extras from the full config and
            # persists only the non-secret fields to the column.
            await store.update_connection(row.name, ConnectionUpdate(ssl_config=full_ssl_config))
            report["migrated"].append(row.name)
        except Exception as exc:
            logger.error("TLS migration failed for connection '%s': %s", row.name, exc)
            report["failed"][row.name] = "migration error"

    return report


# ---------------------------------------------------------------------------
# Readiness gate
# ---------------------------------------------------------------------------


async def count_plaintext_tls_connections(session: AsyncSession) -> int:
    """Count connections in any org that still carry TLS material in ssl_config.

    Deliberately cross-org: this answers a deployment-wide readiness question,
    not a tenant one. The text match on the JSON column is an index-free but
    single-pass filter; the truthiness check that decides what the migration
    would actually rewrite runs only over the (normally zero) rows it returns.
    """
    probe = or_(*[cast(GatewayConnection.ssl_config, Text).like(f'%"{field}"%') for field in SSL_SECRET_FIELDS])
    result = await session.execute(
        select(GatewayConnection.ssl_config).where(GatewayConnection.ssl_config.is_not(None), probe)
    )
    return sum(1 for ssl_config in result.scalars() if _plaintext_secret_fields(ssl_config))


async def check_plaintext_tls_readiness(*, force: bool = False) -> str | None:
    """Return the operator message when legacy plaintext TLS rows remain, else None.

    Cached, so /health does not pay for a query per request.
    """
    global _readiness_cache

    if not force and _readiness_cache is not None:
        checked_at, message = _readiness_cache
        if message is None or time.monotonic() - checked_at < _DIRTY_RECHECK_S:
            return message

    from gateway.db.engine import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as session:
            count = await count_plaintext_tls_connections(session)
    except Exception as exc:
        # Only a confirmed finding blocks readiness — a database blip must not
        # flap the probe. Keep whatever verdict we last established.
        logger.warning("Plaintext TLS readiness probe failed: %s", exc)
        return _readiness_cache[1] if _readiness_cache else None

    message = _READINESS_MESSAGE.format(count=count) if count else None
    _readiness_cache = (time.monotonic(), message)
    return message


def reset_readiness_cache() -> None:
    global _readiness_cache
    _readiness_cache = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def _run_cli(apply: bool) -> int:
    from gateway.db.engine import close_db, get_session_factory
    from gateway.store import Store

    factory = get_session_factory()
    total_affected = 0
    async with factory() as session:
        orgs = list((await session.execute(select(GatewayConnection.org_id).distinct())).scalars())
        for org_id in orgs:
            store = Store(session, org_id=org_id)
            report = await migrate_plaintext_tls_config(store, dry_run=not apply)
            if report["affected"]:
                total_affected += len(report["affected"])
                print(f"org {org_id}: affected={sorted(report['affected'])} migrated={report['migrated']} failed={report['failed']}")
        if apply:
            await session.commit()
    await close_db()
    if not apply:
        print(f"Dry run: {total_affected} connection(s) carry plaintext TLS material. Re-run with --apply to rewrite.")
    else:
        print(f"Applied: {total_affected} connection(s) processed.")
    return 0


def main() -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="rewrite rows (default: dry run)")
    args = parser.parse_args()
    return asyncio.run(_run_cli(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
