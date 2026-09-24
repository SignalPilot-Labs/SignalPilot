"""Tableau API: admin settings (``/api/tableau/integration``) and chat-run runtime routes."""

from fastapi import APIRouter

from .admin import router as admin_router
from .runtime import router as runtime_router
from .runtime_publish import router as runtime_publish_router

router = APIRouter()
router.include_router(admin_router)
# Publish routes first: POST /workbooks must not fall into a {ref:path} route.
router.include_router(runtime_publish_router)
router.include_router(runtime_router)

__all__ = ["router"]
