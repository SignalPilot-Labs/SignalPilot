# isort: skip_file
"""Schema linking endpoint package — split from a 995-LOC monolith in r8."""

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
