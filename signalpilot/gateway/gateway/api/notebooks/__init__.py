"""Notebook API package.

Split from ``api/notebooks.py`` (476 LOC) to reduce file size and improve
maintainability. Mirrors the MCP tools notebooks package split (round 10).

Route registration order is critical for FastAPI path matching:
static paths (/notebooks/search, /notebooks/summary, /notebooks/batch/*)
must be registered BEFORE parameterized paths (/notebooks/{notebook_id}).

Ordering rationale:
- list_router, search_router: pure static GETs, no conflict
- batch_router: POST /notebooks/batch/* — must precede crud which has POST /notebooks/{notebook_id}/analyze
- analysis_router: includes GET /notebooks/summary (static) — must precede crud's GET /notebooks/{notebook_id}
- crud_router: has GET/DELETE/PATCH /notebooks/{notebook_id} — after all static routes
- download_router, activities_router, compare_router: all /notebooks/{notebook_id}/... sub-paths
"""

from __future__ import annotations

from fastapi import APIRouter

from .activities import router as activities_router
from .analysis import router as analysis_router
from .batch import router as batch_router
from .compare import router as compare_router
from .crud import router as crud_router
from .download import router as download_router
from .list import router as list_router
from .quality import router as quality_router
from .search import router as search_router
from .versions import router as versions_router

router = APIRouter(prefix="/api")

# Static routes registered before any parameterized {notebook_id} routes.
router.include_router(list_router)       # GET /notebooks
router.include_router(search_router)     # GET /notebooks/search
router.include_router(quality_router)    # GET /notebooks/quality
router.include_router(batch_router)      # POST /notebooks/batch/analyze, POST /notebooks/batch/delete
router.include_router(analysis_router)   # GET /notebooks/summary (static) + /notebooks/{notebook_id}/analysis etc.
# Parameterized-only routes — after static paths.
router.include_router(crud_router)       # POST /notebooks, GET/DELETE/PATCH /notebooks/{notebook_id}
router.include_router(download_router)   # GET /notebooks/{notebook_id}/download
router.include_router(activities_router) # GET /notebooks/{notebook_id}/activities
router.include_router(compare_router)    # GET /notebooks/{notebook_id}/compare/{other_id}
router.include_router(versions_router)   # GET /notebooks/{notebook_id}/versions
