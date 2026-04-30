"""
Persistent store backed by PostgreSQL.

All operations are scoped to a user_id. In local mode user_id is always "local".
Credentials are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256).
"""

from __future__ import annotations

from gateway.store._constants import (
    CURRENT_KEY_VERSION,
    KEY_FILE_NAME,
    PBKDF2_ITERATIONS,
    PBKDF2_KEY_LENGTH,
    SALT_FILE_NAME,
)
from gateway.store.byok_state import (
    _resolve_byok_key,
    configure_byok,
)
from gateway.store.connection_strings import (
    _build_connection_string,
    _extract_credential_extras,
)
from gateway.store.crypto import (
    CredentialEncryptionError,
    _decrypt,
    _decrypt_with_migration,
    _derive_key_legacy_cloud_salt,
    _derive_key_legacy_sha256,
    _derive_key_pbkdf2,
    _encrypt,
    _get_encryption_key,
    _load_or_create_salt,
)
from gateway.store.local_api_key import get_local_api_key
from gateway.store.paths import _validate_local_db_path
from gateway.store.sandboxes import (
    delete_sandbox,
    get_sandbox,
    list_sandboxes,
    upsert_sandbox,
)
from gateway.store.store import Store

__all__ = [
    # Class
    "Store",
    # Custom exception
    "CredentialEncryptionError",
    # Constants
    "CURRENT_KEY_VERSION",
    "KEY_FILE_NAME",
    "PBKDF2_ITERATIONS",
    "PBKDF2_KEY_LENGTH",
    "SALT_FILE_NAME",
    # BYOK configuration entry point + read-only resolver
    "configure_byok",
    "_resolve_byok_key",
    # Crypto primitives (read-only callables; module-level state stays in submodules)
    "_decrypt",
    "_decrypt_with_migration",
    "_derive_key_legacy_cloud_salt",
    "_derive_key_legacy_sha256",
    "_derive_key_pbkdf2",
    "_encrypt",
    "_get_encryption_key",
    "_load_or_create_salt",
    # Path validation
    "_validate_local_db_path",
    # Connection-string builders
    "_build_connection_string",
    "_extract_credential_extras",
    # Sandboxes
    "delete_sandbox",
    "get_sandbox",
    "list_sandboxes",
    "upsert_sandbox",
    # Local API key
    "get_local_api_key",
]
