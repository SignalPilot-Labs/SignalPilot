"""Kubernetes orchestrator settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class K8sSettings(_GatewaySettingsBase):
    sp_k8s_namespace: str = Field("default", alias="SP_K8S_NAMESPACE")
    sp_notebook_image: str = Field("signalpilot-notebook:latest", alias="SP_NOTEBOOK_IMAGE")
    sp_notebook_idle_timeout: int = Field(7200, alias="SP_NOTEBOOK_IDLE_TIMEOUT")


@lru_cache(maxsize=1)
def get_k8s_settings() -> K8sSettings:
    return K8sSettings()
