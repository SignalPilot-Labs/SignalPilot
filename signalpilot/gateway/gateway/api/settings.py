"""Gateway settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..models import GatewaySettings
from ..store import load_settings, save_settings
from .deps import reset_sandbox_client

router = APIRouter(prefix="/api")


@router.get("/settings")
async def get_settings():
    return load_settings()


@router.put("/settings")
async def update_settings(settings: GatewaySettings):
    save_settings(settings)
    reset_sandbox_client()  # Reconnect with new URL
    return settings
