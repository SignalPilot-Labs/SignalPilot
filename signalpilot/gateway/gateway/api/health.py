"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from .deps import get_sandbox_client

router = APIRouter()


@router.get("/health")
async def health():
    """Public health check — returns minimal info to avoid leaking internals."""
    sandbox_status = "unknown"
    try:
        client = get_sandbox_client()
        data = await client.health()
        sandbox_status = data.get("status", "unknown")
    except Exception:
        sandbox_status = "error"

    return {
        "status": "healthy",
        "version": "0.1.0",
        "sandbox_status": sandbox_status,
    }
