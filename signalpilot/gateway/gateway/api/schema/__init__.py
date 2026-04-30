"""Schema introspection, compression, and agent-context endpoints."""

from __future__ import annotations

from gateway.api.schema import (  # noqa: F401  (side-effect: route registration)
    _router,  # noqa: F401
    agent_context,
    compact,
    endorsements,
    exploration,
    introspection,
    linking,
    refinement,
    relationships,
    semantic_model,
)
from gateway.api.schema._identifiers import _quote_identifier, _quote_table_name
from gateway.api.schema._router import router
from gateway.connectors.pool_manager import pool_manager  # tests patch via shim path

__all__ = [
    # Router (consumed by gateway.api.__init__.register_routers)
    "router",
    # SQL identifier helpers (imported by tests/test_sql_injection.py)
    "_quote_identifier",
    "_quote_table_name",
    # External symbol re-exported solely so tests can patch it on the shim
    # (tests/test_sql_injection.py:294, 331 do `patch("gateway.api.schema.pool_manager")`).
    "pool_manager",
]
