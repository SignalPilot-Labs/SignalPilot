"""Health check endpoint — public, no user data."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy", "version": "0.1.0"}
