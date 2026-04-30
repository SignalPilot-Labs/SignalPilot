"""Optional sqlglot dependency guard.

Centralises the try/except so that the RuntimeWarning fires exactly once
per process, regardless of how many engine sub-modules are imported.
"""

from __future__ import annotations

import warnings

try:
    import sqlglot
    import sqlglot.expressions as exp

    HAS_SQLGLOT: bool = True
except ImportError:
    sqlglot = None  # type: ignore[assignment]
    exp = None  # type: ignore[assignment]
    HAS_SQLGLOT = False
    warnings.warn(
        "sqlglot is not installed — SQL validation is DISABLED. Install it with: pip install sqlglot>=25.0.0",
        RuntimeWarning,
        stacklevel=2,
    )

__all__ = ["HAS_SQLGLOT", "exp", "sqlglot"]
