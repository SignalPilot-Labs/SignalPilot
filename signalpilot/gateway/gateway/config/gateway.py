"""Public gateway URL settings (relocated from the removed config/k8s.py).

Notebook Runtime v2 removed the Kubernetes notebook path entirely; what
survives here is the vetted public gateway URL/port that every runtime —
notebook sandbox, eval sandbox, MCP client — uses to reach back, plus the
session-JWT TTL those runtimes are minted with.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, field_validator

from ._base import _GatewaySettingsBase

_LOCAL_GATEWAY_URL_DEFAULT = "http://gateway:3300"


class GatewaySettings(_GatewaySettingsBase):
    sp_session_jwt_ttl_seconds: int = Field(28800, alias="SP_SESSION_JWT_TTL_SECONDS")
    # Gateway URL as seen by runtimes — must be a vetted value, never derived
    # from request Host. In local mode defaults to the compose-network address.
    # In cloud mode SP_PUBLIC_GATEWAY_URL MUST be set explicitly.
    sp_public_gateway_url: str = Field(_LOCAL_GATEWAY_URL_DEFAULT, alias="SP_PUBLIC_GATEWAY_URL")
    # The public port the gateway listens on.
    sp_public_gateway_port: int = Field(3300, alias="SP_PUBLIC_GATEWAY_PORT")

    @field_validator("sp_public_gateway_url", mode="after")
    @classmethod
    def _require_in_cloud_mode(cls, v: str) -> str:
        # Read SP_DEPLOYMENT_MODE directly — config/ must not import runtime.mode.
        is_cloud = os.environ.get("SP_DEPLOYMENT_MODE", "").lower() == "cloud"
        if is_cloud and v == _LOCAL_GATEWAY_URL_DEFAULT:
            raise ValueError(
                "SP_PUBLIC_GATEWAY_URL must be set explicitly in cloud mode. "
                "The default 'http://gateway:3300' is only valid for local compose."
            )
        return v

    @field_validator("sp_public_gateway_port", mode="after")
    @classmethod
    def _validate_gateway_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(
                f"SP_PUBLIC_GATEWAY_PORT must be between 1 and 65535. Got: {v}"
            )
        return v


@lru_cache(maxsize=1)
def get_gateway_settings() -> GatewaySettings:
    return GatewaySettings()
