"""Shared gate + error handling for the Tableau runtime routes.

Runtime routes serve chat runs only: the caller must present a run session
token (``auth_method == "notebook_session"``) that carries the ``tableau``
capability, and the org integration must be active. Every call logs one line
``tableau.runtime org=<id> op=<op> ref=<ref> status=<code>``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request

from ...tableau import service as tableau_service
from ...tableau.client import TableauClient, TableauError
from ..deps import StoreD

logger = logging.getLogger("gateway.tableau.runtime")

TABLEAU_CAPABILITY = "tableau"


def require_run_token(request: Request) -> None:
    """403 unless the caller is a chat run session token with the tableau capability."""
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("auth_method") != "notebook_session":
        raise HTTPException(
            status_code=403, detail="Tableau runtime routes accept chat run tokens only (missing run capability)"
        )
    if TABLEAU_CAPABILITY not in (auth.get("capabilities") or []):
        raise HTTPException(
            status_code=403,
            detail="This run may not use Tableau: the tableau capability is missing (integration not enabled)",
        )


def _log(org_id: str, op: str, ref: str | None, status: int) -> None:
    logger.info("tableau.runtime org=%s op=%s ref=%s status=%s", org_id, op, (ref or "-")[:200], status)


async def run_tableau[T](
    request: Request,
    store: StoreD,
    op: str,
    ref: str | None,
    fn: Callable[[TableauClient], Awaitable[T]],
) -> T:
    """Gate the caller, open the org's Tableau client, run ``fn``, map errors to HTTP."""
    require_run_token(request)
    org_id = store.org_id or "local"
    try:
        creds = await tableau_service.org_credentials(store.session, org_id)
        async with tableau_service.make_client(creds, cache_key=org_id) as client:
            result = await fn(client)
    except TableauError as exc:
        _log(org_id, op, ref, exc.status_code)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    except HTTPException as exc:
        _log(org_id, op, ref, exc.status_code)
        raise
    except Exception:
        _log(org_id, op, ref, 500)
        raise
    _log(org_id, op, ref, 200)
    return result


def clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))
