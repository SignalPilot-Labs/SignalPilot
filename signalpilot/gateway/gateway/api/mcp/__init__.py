"""Connectors API (external MCP servers) — routes split by concern under /api/mcp."""

from __future__ import annotations

from fastapi import APIRouter

from .activity import router as activity_router
from .connectors import router as connectors_router
from .icons import router as icons_router
from .oauth import router as oauth_router
from .policy import router as policy_router
from .proxy import router as proxy_router

router = APIRouter(prefix="/api/mcp", tags=["connectors"])
router.include_router(connectors_router)
router.include_router(icons_router)
router.include_router(oauth_router)
router.include_router(proxy_router)
router.include_router(activity_router)
router.include_router(policy_router)

__all__ = ["router"]
