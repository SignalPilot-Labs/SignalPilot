"""Route package — exports all APIRouter instances."""

from workspaces_api.routes.health import router as health_router
from workspaces_api.routes.runs import router as runs_router

__all__ = ["health_router", "runs_router"]
