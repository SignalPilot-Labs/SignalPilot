"""One-off migration for TLS material left in the plaintext ssl_config column.

Connections created before TLS certs/keys moved into the encrypted credential
extras still carry ca_cert/client_cert/client_key in gateway_connections.ssl_config.
New writes never do, and reads redact them, so those rows are inert — but the
plaintext copy is still on disk and should be swept.

Nothing here runs automatically. Call it from an admin shell against a live
session, dry-run first, and take a database backup before dry_run=False: the
plaintext column is rewritten in place once the material is in the encrypted
extras.

    from gateway.store.tls_migration import migrate_plaintext_tls_config
    report = await migrate_plaintext_tls_config(store)               # inspect
    report = await migrate_plaintext_tls_config(store, dry_run=False) # apply
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from gateway.db.models import SSL_SECRET_FIELDS, GatewayConnection
from gateway.models import ConnectionUpdate

logger = logging.getLogger(__name__)


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
