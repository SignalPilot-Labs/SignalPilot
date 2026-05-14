"""Health check route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from workspaces_api.config import Settings, get_settings
from workspaces_api.schemas import HealthResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return service health and deployment mode. No DB call."""
    return HealthResponse(status="ok", deployment_mode=settings.sp_deployment_mode)
