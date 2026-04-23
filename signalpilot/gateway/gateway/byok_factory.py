"""BYOK provider factory.

Translates a provider_type string and provider_config dict into the appropriate
BYOKProvider implementation. Used at application startup (main.py lifespan) to
select the provider from environment variables.

Dependency direction:
  byok_factory.py -> byok.py (LocalBYOKProvider, BYOKProvider protocol)
  byok_factory.py -> byok_aws.py (AWSKMSProvider)
  byok_factory.py -> db.models (GatewayBYOKKey — for make_provider_for_key)
"""

from __future__ import annotations

from .byok import BYOKProvider, LocalBYOKProvider
from .byok_aws import AWSKMSProvider
from .db.models import GatewayBYOKKey

# ─── Constants ────────────────────────────────────────────────────────────────

PROVIDER_TYPE_LOCAL = "local"
PROVIDER_TYPE_AWS_KMS = "aws_kms"
PROVIDER_TYPE_GCP_KMS = "gcp_kms"
PROVIDER_TYPE_AZURE_KV = "azure_kv"

_UNSUPPORTED_PROVIDERS = {PROVIDER_TYPE_GCP_KMS, PROVIDER_TYPE_AZURE_KV}


# ─── Factory ──────────────────────────────────────────────────────────────────

def make_provider(provider_type: str, provider_config: dict | None = None) -> BYOKProvider:
    """Create a BYOKProvider from a type string and optional config dict.

    Args:
        provider_type: One of "local", "aws_kms", "gcp_kms", "azure_kv".
        provider_config: Provider-specific configuration. Required for "aws_kms"
            (must include "kms_key_arn"). Ignored for "local".

    Returns:
        A BYOKProvider implementation.

    Raises:
        ValueError: If provider_type is "aws_kms" and provider_config is missing
            or lacks the required "kms_key_arn" key.
        NotImplementedError: If provider_type is "gcp_kms" or "azure_kv".
        ValueError: If provider_type is an unknown string.
    """
    if provider_type == PROVIDER_TYPE_LOCAL:
        from .deployment import is_cloud_mode
        if is_cloud_mode():
            raise ValueError("Local BYOK provider is not available in cloud mode. Use aws_kms, gcp_kms, or azure_kv.")
        return LocalBYOKProvider()

    if provider_type == PROVIDER_TYPE_AWS_KMS:
        config = provider_config or {}
        if not config.get("kms_key_arn"):
            raise ValueError(
                "provider_config must include 'kms_key_arn' for aws_kms provider"
            )
        return AWSKMSProvider(config)

    if provider_type in _UNSUPPORTED_PROVIDERS:
        raise NotImplementedError(f"Provider '{provider_type}' is not yet supported")

    raise ValueError(
        f"Unknown provider_type: {provider_type!r}. "
        f"Supported values: local, aws_kms"
    )


def make_provider_for_key(byok_key: GatewayBYOKKey) -> BYOKProvider:
    """Create a BYOKProvider from a GatewayBYOKKey ORM row.

    Convenience wrapper around make_provider() that reads provider_type and
    provider_config directly from the DB model.
    """
    return make_provider(byok_key.provider_type, byok_key.provider_config)
