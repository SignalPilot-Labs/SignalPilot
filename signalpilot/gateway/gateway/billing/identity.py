"""Service identity: work the gateway starts on its own behalf never consumes credits.

Readiness checks, dbt map compiles, health probes, and schema refreshes run
under a service identity. Emitters call ``is_service_identity`` before
writing a consuming row and write nothing (or a zero-credit row with reason
``service_identity``) when it returns True.

Two ways to mark work as service-initiated:

1. Wrap the code path in ``service_identity()``. This sets a context variable
   that every emitter inside the block sees, regardless of the user id the
   audit row carries.
2. Run under one of the reserved service user ids (``system``, ``gateway``,
   or any id with the ``service:`` prefix).

The eval runner (``eval-runner``) is deliberately not a service identity:
eval queries are customer work and bill as governed queries.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

SERVICE_USER_IDS: frozenset[str] = frozenset({"system", "gateway"})
SERVICE_USER_PREFIX = "service:"

service_identity_var: contextvars.ContextVar[bool] = contextvars.ContextVar("billing_service_identity", default=False)


@contextmanager
def service_identity() -> Iterator[None]:
    """Mark everything inside the block as gateway self-initiated work."""
    token = service_identity_var.set(True)
    try:
        yield
    finally:
        service_identity_var.reset(token)


def is_service_user_id(user_id: str | None) -> bool:
    """Return True when ``user_id`` is one of the reserved service identities."""
    if not user_id:
        return False
    return user_id in SERVICE_USER_IDS or user_id.startswith(SERVICE_USER_PREFIX)


def is_service_identity(ctx: Any = None) -> bool:
    """Return True when the current work is gateway self-initiated.

    ``ctx`` may be None (only the context variable is consulted), a user id
    string, a mapping with ``user_id`` / ``is_service`` / ``source`` keys, or
    any object exposing those as attributes (a Store, an MCP context, a
    dataclass). ``source == "system"`` and a truthy ``is_service`` both count.
    """
    if service_identity_var.get():
        return True
    if ctx is None:
        return False
    if isinstance(ctx, str):
        return is_service_user_id(ctx)
    if isinstance(ctx, dict):
        return bool(ctx.get("is_service")) or ctx.get("source") == "system" or is_service_user_id(ctx.get("user_id"))
    if getattr(ctx, "is_service", False):
        return True
    if getattr(ctx, "source", None) == "system":
        return True
    return is_service_user_id(getattr(ctx, "user_id", None))


__all__ = [
    "SERVICE_USER_IDS",
    "SERVICE_USER_PREFIX",
    "is_service_identity",
    "is_service_user_id",
    "service_identity",
    "service_identity_var",
]
