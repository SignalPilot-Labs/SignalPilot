"""Schema linking endpoint package.

Split from ``api/schema/linking.py`` (995 LOC) in round 8.

Invariant: data-only re-export shim; preserves public name surface via
``__all__``. Imports the endpoint submodule as a side-effect so the route
handler is registered on the shared router when this package is imported.

``# isort: skip_file`` is mandatory: the endpoint import must precede the
re-export imports to ensure route registration happens before any symbol
lookups resolve.

Do not add ``__getattr__`` proxy or ``_common.py`` re-export helpers — see r9 lessons.
"""
# isort: skip_file

from __future__ import annotations

# Import endpoint for side-effect: it decorates the schema_link function on the
# shared router. gateway.api.schema.__init__ does `from gateway.api.schema import linking`
# expecting that import to register the route.
from gateway.api.schema.linking import endpoint as _endpoint  # noqa: F401

# Re-export public names so module-attribute access (and any defensive test patches)
# continues to resolve. schema_link is the route handler; _DIALECT_HINTS is the largest
# constant — exposed for parity.
from gateway.api.schema.linking._data import _DIALECT_HINTS  # noqa: F401
from gateway.api.schema.linking.endpoint import schema_link  # noqa: F401

__all__ = ["schema_link", "_DIALECT_HINTS"]
