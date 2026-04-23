"""File browser endpoint — browse host filesystem for local DB files via sandbox manager."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..scope_guard import RequireScope
from .deps import StoreD, get_sandbox_client_with_store

router = APIRouter(prefix="/api")


@router.get("/files/browse", dependencies=[RequireScope("read")])
async def browse_files(
    store: StoreD,
    path: str | None = Query(default=None, description="Directory to browse"),
    pattern: str = Query(default="*.duckdb", description="File glob pattern"),
):
    """Browse the host filesystem for database files.

    Proxies to the sandbox manager which has host filesystem access.
    Returns files matching the pattern and subdirectories.
    """
    client = await get_sandbox_client_with_store(store)
    return await client.browse_files(path=path, pattern=pattern)
