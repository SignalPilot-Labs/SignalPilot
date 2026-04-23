"""Gateway settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..models import GatewaySettings
from ..scope_guard import RequireScope
from .deps import StoreD, reset_sandbox_client

router = APIRouter(prefix="/api")


@router.get("/settings")
async def get_settings(store: StoreD):
    return await store.load_settings()


@router.put("/settings", dependencies=[RequireScope("admin")])
async def update_settings(settings: GatewaySettings, store: StoreD):
    await store.save_settings(settings)
    reset_sandbox_client()  # Reconnect with new URL
    return settings
