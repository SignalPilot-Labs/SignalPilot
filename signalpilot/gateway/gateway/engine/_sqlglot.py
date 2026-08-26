"""sqlglot import — hard dependency for SQL validation.

sqlglot is required for AST-based governance in dbt_validation.py. If it is
absent, import fails loudly (fail closed — do not skip validation).
"""

from __future__ import annotations

import sqlglot
import sqlglot.expressions as exp

# Re-export for callers that previously used the conditional-import pattern.
HAS_SQLGLOT: bool = True

__all__ = ["HAS_SQLGLOT", "exp", "sqlglot"]
