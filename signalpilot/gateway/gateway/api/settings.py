"""Gateway settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
async def update_settings(new_settings: GatewaySettings):
    current = load_settings()

    # Normalize: strip whitespace from API keys
    if new_settings.api_key:
        new_settings.api_key = new_settings.api_key.strip()
    if hasattr(new_settings, 'sandbox_api_key') and new_settings.sandbox_api_key:
        new_settings.sandbox_api_key = new_settings.sandbox_api_key.strip()

    # If the redacted placeholder was sent back, preserve the existing key
    if new_settings.api_key == "***":
        new_settings.api_key = current.api_key
    if hasattr(new_settings, 'sandbox_api_key') and new_settings.sandbox_api_key == "***":
        new_settings.sandbox_api_key = current.sandbox_api_key

    # Prevent disabling auth by clearing the API key
    if current.api_key and not new_settings.api_key:
        raise HTTPException(
            status_code=400,
            detail="Cannot disable authentication by removing the API key. Set a new key or keep the existing one.",
        )

    # Enforce minimum key length to prevent weak keys
    if new_settings.api_key and new_settings.api_key != current.api_key and len(new_settings.api_key) < 16:
        raise HTTPException(
            status_code=400,
            detail="API key must be at least 16 characters long.",
        )

    save_settings(new_settings)
    reset_sandbox_client()
    return _redact_settings(new_settings)
