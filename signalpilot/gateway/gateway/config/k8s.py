"""Kubernetes orchestrator settings."""

from __future__ import annotations

import ipaddress
import os
import re
from functools import lru_cache

from pydantic import Field, field_validator

from ._base import _GatewaySettingsBase

_LOCAL_GATEWAY_URL_DEFAULT = "http://gateway:3300"
_SINGLE_KV_RE = re.compile(r"^[^=,\s]+=[^=,\s]+$")


class K8sSettings(_GatewaySettingsBase):
    sp_k8s_namespace: str = Field("default", alias="SP_K8S_NAMESPACE")
    sp_notebook_image: str = Field("signalpilot-notebook:latest", alias="SP_NOTEBOOK_IMAGE")
    sp_notebook_idle_timeout: int = Field(7200, alias="SP_NOTEBOOK_IDLE_TIMEOUT")
    sp_session_jwt_ttl_seconds: int = Field(28800, alias="SP_SESSION_JWT_TTL_SECONDS")
    # Gateway URL as seen by pods — must be a vetted value, never derived from request Host.
    # In local mode defaults to the compose-network address.
    # In cloud mode SP_PUBLIC_GATEWAY_URL MUST be set explicitly.
    sp_public_gateway_url: str = Field(_LOCAL_GATEWAY_URL_DEFAULT, alias="SP_PUBLIC_GATEWAY_URL")

    # ── R3: Per-org namespace isolation settings ───────────────────────────────
    sp_notebook_namespace_prefix: str = Field("sp-nb", alias="SP_NOTEBOOK_NAMESPACE_PREFIX")
    sp_gateway_namespace: str = Field("signalpilot", alias="SP_GATEWAY_NAMESPACE")
    # Single k=v pair selector for the gateway pod. Validator rejects multi-pair or wildcards.
    sp_gateway_pod_selector: str = Field(
        "app=signalpilot-gateway", alias="SP_GATEWAY_POD_SELECTOR"
    )
    sp_gateway_service_account: str = Field(
        "signalpilot-gateway", alias="SP_GATEWAY_SERVICE_ACCOUNT"
    )
    # Optional S3 (or other external) egress CIDR. Validated as a valid IP network.
    sp_notebook_egress_cidr: str | None = Field(None, alias="SP_NOTEBOOK_EGRESS_CIDR")
    # The public port the gateway listens on — used as the egress NetworkPolicy destination port.
    # This is the ONLY source of the gateway port for NetworkPolicy; never parsed from the URL.
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

    @field_validator("sp_gateway_pod_selector", mode="after")
    @classmethod
    def _validate_pod_selector(cls, v: str) -> str:
        stripped = v.strip()
        if not _SINGLE_KV_RE.match(stripped):
            raise ValueError(
                f"SP_GATEWAY_POD_SELECTOR must be a single k=v pair (e.g. 'app=my-gateway'). "
                f"Got: {v!r}. Multi-pair selectors and wildcards are not supported."
            )
        return stripped

    @field_validator("sp_notebook_egress_cidr", mode="after")
    @classmethod
    def _validate_egress_cidr(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise ValueError(
                f"SP_NOTEBOOK_EGRESS_CIDR must be a valid IP network CIDR (e.g. '10.0.0.0/8'). "
                f"Got: {v!r}"
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
def get_k8s_settings() -> K8sSettings:
    return K8sSettings()
