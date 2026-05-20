"""Kubernetes orchestrator settings."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, field_validator

from ._base import _GatewaySettingsBase

_LOCAL_GATEWAY_URL_DEFAULT = "http://gateway:3300"


class K8sSettings(_GatewaySettingsBase):
    sp_k8s_namespace: str = Field("default", alias="SP_K8S_NAMESPACE")
    sp_notebook_image: str = Field("signalpilot-notebook:latest", alias="SP_NOTEBOOK_IMAGE")
    sp_notebook_idle_timeout: int = Field(7200, alias="SP_NOTEBOOK_IDLE_TIMEOUT")
    sp_session_jwt_ttl_seconds: int = Field(28800, alias="SP_SESSION_JWT_TTL_SECONDS")
    # Gateway URL as seen by pods — must be a vetted value, never derived from request Host.
    # In local mode defaults to the compose-network address.
    # In cloud mode SP_PUBLIC_GATEWAY_URL MUST be set explicitly.
    sp_public_gateway_url: str = Field(_LOCAL_GATEWAY_URL_DEFAULT, alias="SP_PUBLIC_GATEWAY_URL")

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


@lru_cache(maxsize=1)
def get_k8s_settings() -> K8sSettings:
    return K8sSettings()
