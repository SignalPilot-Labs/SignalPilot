"""Connection CRUD and management endpoints.

Split from ``api/connections.py`` (1959 LOC) in round 6.

Invariant: FastAPI route registration order — submodules are imported in the
order their endpoints appeared in the original monolith; verify with
``len(router.routes)`` and route-path order. Static-path routes must register
before parametric ``{name}`` routes to preserve FastAPI's match priority.

``# isort: skip_file`` is mandatory: reordering imports changes endpoint
registration order and breaks FastAPI path-matching priority.

Do not add ``__getattr__`` proxy or ``_common.py`` re-export helpers — see r9 lessons.
"""

from __future__ import annotations

# fmt: off
# Import order is intentional: static-path routes must register before
# parametric {name} routes to preserve FastAPI's match priority.
# isort: skip_file
from gateway.api.connections import _router  # noqa: F401
from gateway.api.connections import stats  # noqa: F401
from gateway.api.connections import porting  # noqa: F401
from gateway.api.connections import schema_ops  # noqa: F401
from gateway.api.connections import url_tools  # noqa: F401
from gateway.api.connections import testing  # noqa: F401
from gateway.api.connections import health  # noqa: F401
from gateway.api.connections import crud  # noqa: F401
from gateway.api.connections import diagnostics  # noqa: F401
from gateway.api.connections import capabilities  # noqa: F401
from gateway.api.connections._router import router
from gateway.api.connections._validation import _validate_connection_params
from gateway.api.connections.crud import clone_connection
# fmt: on

__all__ = [
    # Router (consumed by gateway.api.__init__.register_routers via line 12)
    "router",
    # Endpoint imported directly by tests/test_concurrency.py:355
    "clone_connection",
    # Helper imported directly by tests/test_security_hardening.py (4 sites)
    "_validate_connection_params",
]
