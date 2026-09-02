"""Shared helpers for the connector store: time and encrypted-JSON columns."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from gateway.store.crypto import CredentialEncryptionError, _decrypt_with_migration, _encrypt

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_aware_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; treat them as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    aware = as_aware_utc(value)
    return aware.isoformat() if aware else None


def encrypt_json(value: Any) -> bytes:
    return _encrypt(json.dumps(value, separators=(",", ":"), sort_keys=True))


def decrypt_json(row: Any, attr: str) -> Any:
    """Decrypt a ``*_enc`` JSON column, re-encrypting in place after a key rotation.

    Returns None when the column is empty or the ciphertext is unreadable. The
    caller owns the commit; a migrated row is dirty on the session after this.
    """
    ciphertext = getattr(row, attr, None)
    if not ciphertext:
        return None
    try:
        plaintext, needs_migration = _decrypt_with_migration(ciphertext)
    except CredentialEncryptionError:
        logger.warning("Connector secret in %s.%s is unreadable; treating as unset", type(row).__name__, attr)
        return None
    if needs_migration:
        setattr(row, attr, _encrypt(plaintext))
    try:
        return json.loads(plaintext)
    except ValueError:
        return None


def decrypt_dict(row: Any, attr: str) -> dict[str, str]:
    value = decrypt_json(row, attr)
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}
