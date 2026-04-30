"""Gateway errors package.

Re-exports the full public surface of the errors submodules so that
``from gateway.errors import …`` call sites continue to work unchanged.
"""

from .http import query_error_hint
from .mcp import sanitize_mcp_error, sanitize_proxy_response

__all__ = [
    "query_error_hint",
    "sanitize_mcp_error",
    "sanitize_proxy_response",
]
