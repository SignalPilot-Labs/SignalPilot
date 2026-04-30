"""
SQL Query Engine — the gatekeeper between AI agents and databases.

Pipeline:
1. Parse SQL to AST (sqlglot)
2. Validate: read-only, no stacking, no blocked tables
3. Inject LIMIT if missing
4. Execute with timeout
5. Return governed result
"""

from __future__ import annotations

from .transforms import inject_limit, redact_sql_literals
from .validation import ValidationResult, validate_sql

__all__ = ["ValidationResult", "inject_limit", "redact_sql_literals", "validate_sql"]
