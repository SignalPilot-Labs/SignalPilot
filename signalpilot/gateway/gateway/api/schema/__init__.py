"""Schema introspection, compression, and agent-context endpoints.

Split from ``api/schema.py`` (3736 LOC) in round 5.

Invariant: FastAPI route registration order — submodules are imported in the
order their endpoints appeared in the original monolith; verify with
``len(router.routes)`` and route-path order.

``# isort: skip_file`` (via per-import ``# noqa: F401``) is mandatory:
reordering imports changes endpoint registration order and breaks FastAPI
path-matching priority.

Do not add ``__getattr__`` proxy or ``_common.py`` re-export helpers — see r9 lessons.
"""

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
