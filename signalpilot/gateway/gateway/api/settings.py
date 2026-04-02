"""Gateway settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..models import GatewaySettings
from ..store import load_settings, save_settings
from .deps import reset_sandbox_client

router = APIRouter(prefix="/api")


def _redact_settings(settings: GatewaySettings) -> dict:
    """Return settings with sensitive fields redacted."""
    data = settings.model_dump()
    for key in ("api_key", "sandbox_api_key"):
        if data.get(key):
            data[key] = "***"
    return data


@router.get("/settings")
async def get_settings():
    return _redact_settings(load_settings())


@router.put("/settings")
async def update_settings(settings: GatewaySettings):
    save_settings(settings)
    reset_sandbox_client()  # Reconnect with new URL
    return _redact_settings(settings)
