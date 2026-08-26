"""BYOK (Bring Your Own Key) API models."""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from ..runtime.mode import byok_custom_endpoint_allowed, is_cloud_mode

_KMS_KEY_ARN_PATTERN = re.compile(
    r"^arn:aws:kms:[a-z0-9-]+:\d{12}:key/[a-zA-Z0-9-]+$"
)
_MAX_PROVIDER_CONFIG_KEYS = 8
_ENDPOINT_URL_MAX_LENGTH = 2048
_REGION_MAX_LENGTH = 32

_AWS_KMS_ALLOWED_KEYS: frozenset[str] = frozenset({
    "kms_key_arn",
    "region",
    "endpoint_url",
})


class BYOKKeyCreate(BaseModel):
    key_alias: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")
    provider_type: str = Field(..., pattern=r"^(local|aws_kms|gcp_kms|azure_kv)$")
    provider_config: dict[str, Any] | None = None

    @field_validator("provider_config", mode="after")
    @classmethod
    def validate_provider_config(
        cls, v: dict[str, Any] | None, info: ValidationInfo
    ) -> dict[str, Any] | None:
        provider_type: str | None = (info.data or {}).get("provider_type")

        if provider_type == "aws_kms":
            if v is None:
                raise ValueError("provider_config is required for provider_type 'aws_kms'")

            if len(v) > _MAX_PROVIDER_CONFIG_KEYS:
                raise ValueError(
                    f"provider_config must not contain more than {_MAX_PROVIDER_CONFIG_KEYS} keys"
                )

            unknown_keys = set(v.keys()) - _AWS_KMS_ALLOWED_KEYS
            if unknown_keys:
                raise ValueError(
                    f"provider_config contains unrecognised keys: {sorted(unknown_keys)}"
                )

            kms_key_arn = v.get("kms_key_arn")
            if not kms_key_arn:
                raise ValueError("provider_config.kms_key_arn is required")
            if not isinstance(kms_key_arn, str) or not _KMS_KEY_ARN_PATTERN.match(kms_key_arn):
                raise ValueError(
                    "provider_config.kms_key_arn must match "
                    r"^arn:aws:kms:[a-z0-9-]+:\d{12}:key/[a-zA-Z0-9-]+$"
                )

            region = v.get("region")
            if region is not None:
                if not isinstance(region, str) or len(region) > _REGION_MAX_LENGTH:
                    raise ValueError(
                        f"provider_config.region must be a string of at most {_REGION_MAX_LENGTH} characters"
                    )

            endpoint_url = v.get("endpoint_url")
            if endpoint_url is not None:
                if not byok_custom_endpoint_allowed():
                    raise ValueError(
                        "provider_config.endpoint_url is not permitted; set "
                        "SP_BYOK_ALLOW_CUSTOM_ENDPOINT=1 to enable for testing"
                    )
                if not isinstance(endpoint_url, str) or len(endpoint_url) > _ENDPOINT_URL_MAX_LENGTH:
                    raise ValueError(
                        f"provider_config.endpoint_url must be a string of at most "
                        f"{_ENDPOINT_URL_MAX_LENGTH} characters"
                    )
                parsed = urllib.parse.urlparse(endpoint_url)
                allowed_schemes = {"https"}
                if not is_cloud_mode():
                    allowed_schemes = {"https", "http"}
                if parsed.scheme not in allowed_schemes:
                    raise ValueError(
                        f"provider_config.endpoint_url scheme {parsed.scheme!r} is not permitted; "
                        f"allowed: {sorted(allowed_schemes)}"
                    )
                host = parsed.hostname
                if not host:
                    raise ValueError(
                        "provider_config.endpoint_url must include a non-empty host"
                    )
                try:
                    ipaddress.ip_address(host)
                    raise ValueError(
                        "provider_config.endpoint_url must not use a literal IP address; "
                        "use a DNS hostname instead"
                    )
                except ValueError as exc:
                    # ip_address() raises ValueError for non-IP strings — that is expected.
                    # Re-raise only if it is our own rejection message (literal IP detected).
                    if "literal IP address" in str(exc):
                        raise

        elif provider_type == "local":
            if v is not None and v != {}:
                raise ValueError("provider_config must be None or an empty dict for provider_type 'local'")

        return v


class BYOKKeyUpdate(BaseModel):
    key_alias: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")
    status: str | None = Field(default=None, pattern=r"^(active|revoked)$")


class BYOKKeyResponse(BaseModel):
    id: str
    org_id: str
    key_alias: str
    provider_type: str
    provider_config: dict[str, Any] | None = None
    status: str
    created_at: float
    revoked_at: float | None = None


class BYOKMigrateRequest(BaseModel):
    key_id: str = Field(..., min_length=1, max_length=2048)


class BYOKMigrateResponse(BaseModel):
    migrated: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class BYOKRotateRequest(BaseModel):
    new_key_id: str = Field(..., min_length=1, max_length=2048)


class BYOKRotateResponse(BaseModel):
    rotated: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class BYOKMigrationStatusResponse(BaseModel):
    total: int
    byok: int
    managed: int
    status: Literal["none", "partial", "complete"]
