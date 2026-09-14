"""Standalone data-chat API assembled from focused route groups."""

from fastapi import APIRouter

from .chat_routes.conversations import router as conversations_router
from .chat_routes.files import router as files_router
from .chat_routes.legacy_artifacts import router as legacy_artifacts_router
from .chat_routes.projects import router as projects_router
from .chat_routes.query_results import router as query_results_router
from .chat_routes.runs import router as runs_router
from .chat_routes.runtime_archives import _sanitize_runtime_archive_html
from .chat_routes.runtime_archives import router as runtime_archives_router
from .chat_routes.runtime_files import router as runtime_files_router
from .deps import RequireBillablePlan

# The bootstrap route (projects_router) answers for every org so a free org can
# see its plan prompt; every other chat route needs a billable plan.
router = APIRouter(prefix="/api/chat")
router.include_router(projects_router)
for _billable_router in (
    conversations_router,
    runs_router,
    runtime_archives_router,
    files_router,
    runtime_files_router,
    legacy_artifacts_router,
    query_results_router,
):
    router.include_router(_billable_router, dependencies=[RequireBillablePlan])

__all__ = ["_sanitize_runtime_archive_html", "router"]
