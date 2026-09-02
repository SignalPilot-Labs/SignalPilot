"""Standalone data-chat API assembled from focused route groups."""

from fastapi import APIRouter

from .chat_routes.artifacts import _sanitize_runtime_archive_html
from .chat_routes.artifacts import router as artifacts_router
from .chat_routes.conversations import router as conversations_router
from .chat_routes.files import router as files_router
from .chat_routes.projects import router as projects_router
from .chat_routes.query_results import router as query_results_router
from .chat_routes.runs import router as runs_router

router = APIRouter(prefix="/api/chat")
router.include_router(projects_router)
router.include_router(conversations_router)
router.include_router(runs_router)
router.include_router(artifacts_router)
router.include_router(files_router)
router.include_router(query_results_router)

__all__ = ["_sanitize_runtime_archive_html", "router"]
