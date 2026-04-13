"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from ..store import list_connections, list_sandboxes, load_settings
from .deps import get_sandbox_client

router = APIRouter()


@router.get("/health")
async def health():
    settings = load_settings()
    sandbox_status = "unknown"
    try:
        client = get_sandbox_client()
        data = await client.health()
        sandbox_status = data.get("status", "unknown")
    except Exception as e:
        sandbox_status = f"error: {e}"

    return {
        "status": "healthy",
        "version": "0.1.0",
        "sandbox_manager": settings.sandbox_manager_url,
        "sandbox_status": sandbox_status,
        "active_sandboxes": len(list_sandboxes()),
        "connections": len(list_connections()),
    }
