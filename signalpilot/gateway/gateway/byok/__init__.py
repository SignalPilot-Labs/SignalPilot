"""BYOK (Bring Your Own Key) subpackage.

Re-exports the full public surface of provider and factory modules so that
existing callers using ``from gateway.byok import ...`` continue to work.
"""

from .factory import (
    PROVIDER_TYPE_AWS_KMS,
    PROVIDER_TYPE_AZURE_KV,
    PROVIDER_TYPE_GCP_KMS,
    PROVIDER_TYPE_LOCAL,
    make_provider,
    make_provider_for_key,
)
from .provider import (
    DEK_CACHE_KEY_SEP,
    ENCRYPTION_MODE_MANAGED,
    BYOKKeyError,
    BYOKProvider,
    DEKCache,
    LocalBYOKProvider,
    decrypt_envelope,
    dek_cache_key,
    encrypt_envelope,
    encrypt_fields_envelope,
    migrate_to_byok,
    provider_key_identifier,
    revert_to_managed,
    rotate_byok_key,
)

__all__ = [
    "BYOKKeyError",
    "DEK_CACHE_KEY_SEP",
    "BYOKProvider",
    "DEKCache",
    "ENCRYPTION_MODE_MANAGED",
    "LocalBYOKProvider",
    "PROVIDER_TYPE_AWS_KMS",
    "PROVIDER_TYPE_AZURE_KV",
    "PROVIDER_TYPE_GCP_KMS",
    "PROVIDER_TYPE_LOCAL",
    "decrypt_envelope",
    "dek_cache_key",
    "encrypt_envelope",
    "encrypt_fields_envelope",
    "make_provider",
    "make_provider_for_key",
    "migrate_to_byok",
    "provider_key_identifier",
    "revert_to_managed",
    "rotate_byok_key",
]
