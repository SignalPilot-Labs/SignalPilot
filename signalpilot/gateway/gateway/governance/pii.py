"""
PII column tagging and result redaction — Features #14-15 from the feature table.

PII rules are defined in schema annotations (YAML sidecar files).
The redactor processes query results before they're returned to the agent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PIIRule(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    """Redaction strategy for PII columns."""

    hash = "hash"  # SHA-256 hash of the value
    mask = "mask"  # Partial masking (e.g., j***@email.com)
    hide = "hide"  # Replace value with ***** (column still visible)


@dataclass
class PIIColumnConfig:
    """Configuration for a single PII column."""

    table: str
    column: str
    rule: PIIRule
    description: str = ""


@dataclass
class PIIRedactor:
    """Redacts PII columns from query results based on configured rules.

    Rules are loaded from schema annotations (schema.yml) and keyed by
    lowercase column name for fast lookup.
    """

    # Map of lowercase column name -> rule
    _rules: dict[str, PIIRule] = field(default_factory=dict)
    # Columns that were redacted in the last call (for audit logging)
    _last_redacted: list[str] = field(default_factory=list)

    def add_rule(self, column: str, rule: PIIRule | str) -> None:
        """Register a PII rule for a column name."""
        if isinstance(rule, str):
            # Backward compat: treat legacy "drop" as "hide"
            if rule == "drop":
                rule = "hide"
            rule = PIIRule(rule)
        self._rules[column.lower()] = rule

    def add_rules_from_annotations(self, annotations: dict[str, Any]) -> None:
        """Load PII rules from schema annotation dict.

        Expected format:
        {
            "tables": {
                "users": {
                    "columns": {
                        "email": {"pii": "hash"},
                        "ssn": {"pii": "mask"},
                        "phone": {"pii": "drop"}
                    }
                }
            }
        }
        """
        tables = annotations.get("tables", {})
        for _table_name, table_config in tables.items():
            columns = table_config.get("columns", {})
            for col_name, col_config in columns.items():
                pii_rule = col_config.get("pii")
                if pii_rule:
                    # Backward compat: treat legacy "drop" as "hide"
                    if pii_rule == "drop":
                        pii_rule = "hide"
                    if pii_rule in PIIRule.__members__:
                        self._rules[col_name.lower()] = PIIRule(pii_rule)

    def redact_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply PII redaction to a list of result rows.

        Returns new list with PII columns redacted according to their rules.
        """
        if not rows or not self._rules:
            self._last_redacted = []
            return rows

        self._last_redacted = []
        redacted_rows = []

        for row in rows:
            new_row = {}
            for col, val in row.items():
                col_lower = col.lower()
                rule = self._rules.get(col_lower)
                if rule is None:
                    new_row[col] = val
                elif rule == PIIRule.hide:
                    new_row[col] = "*****"
                    if col_lower not in self._last_redacted:
                        self._last_redacted.append(col_lower)
                elif rule == PIIRule.hash:
                    new_row[col] = _hash_value(val)
                    if col_lower not in self._last_redacted:
                        self._last_redacted.append(col_lower)
                elif rule == PIIRule.mask:
                    new_row[col] = _mask_value(val)
                    if col_lower not in self._last_redacted:
                        self._last_redacted.append(col_lower)
            redacted_rows.append(new_row)

        return redacted_rows

    @property
    def last_redacted_columns(self) -> list[str]:
        """Columns that were redacted in the most recent call."""
        return list(self._last_redacted)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def has_rules(self) -> bool:
        return bool(self._rules)


# ─── Auto-Detection ─────────────────────────────────────────────────────────

# Column name patterns that commonly contain PII
_PII_PATTERNS: dict[str, PIIRule] = {
    # Direct identifiers
    "ssn": PIIRule.hash,
    "social_security": PIIRule.hash,
    "national_id": PIIRule.hash,
    "passport": PIIRule.hash,
    "tax_id": PIIRule.hash,
    "drivers_license": PIIRule.hash,
    # Contact info
    "email": PIIRule.mask,
    "email_address": PIIRule.mask,
    "phone": PIIRule.mask,
    "phone_number": PIIRule.mask,
    "mobile": PIIRule.mask,
    "address": PIIRule.mask,
    "street_address": PIIRule.mask,
    "home_address": PIIRule.mask,
    # Financial
    "credit_card": PIIRule.hash,
    "card_number": PIIRule.hash,
    "account_number": PIIRule.hash,
    "bank_account": PIIRule.hash,
    "routing_number": PIIRule.hash,
    "iban": PIIRule.hash,
    # Auth/secrets
    "password": PIIRule.hide,
    "password_hash": PIIRule.hide,
    "secret": PIIRule.hide,
    "api_key": PIIRule.hide,
    "access_token": PIIRule.hide,
    "refresh_token": PIIRule.hide,
    # Health
    "diagnosis": PIIRule.mask,
    "medical_record": PIIRule.hash,
    # Personal
    "date_of_birth": PIIRule.mask,
    "dob": PIIRule.mask,
    "salary": PIIRule.mask,
    "income": PIIRule.mask,
}


def detect_pii_columns(column_names: list[str]) -> dict[str, PIIRule]:
    """Auto-detect likely PII columns based on naming patterns.

    Returns a dict of column_name -> suggested PIIRule for columns
    whose names match known PII patterns. This is a heuristic —
    results should be reviewed by a human and saved to schema.yml.
    """
    detected: dict[str, PIIRule] = {}
    for col in column_names:
        col_lower = col.lower().replace("-", "_")
        if col_lower in _PII_PATTERNS:
            detected[col] = _PII_PATTERNS[col_lower]
        else:
            # Check if the column name contains any PII keyword
            for pattern, rule in _PII_PATTERNS.items():
                if pattern in col_lower:
                    detected[col] = rule
                    break
    return detected


def _hash_value(val: Any) -> str:
    """SHA-256 hash a value, returning first 12 chars of hex digest."""
    if val is None:
        return "NULL"
    raw = str(val).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()[:12]}"


def _mask_value(val: Any) -> str:
    """Partially mask a value, preserving structure hints."""
    if val is None:
        return "NULL"
    s = str(val)
    if not s:
        return "***"

    # Email masking: j***@email.com
    if "@" in s:
        local, domain = s.rsplit("@", 1)
        masked_local = local[0] + "***" if local else "***"
        return f"{masked_local}@{domain}"

    # Phone masking: ***-1234
    if len(s) >= 7 and any(c.isdigit() for c in s):
        return "***" + s[-4:]

    # Generic masking: first char + *** + last char
    if len(s) <= 2:
        return "***"
    return s[0] + "***" + s[-1]
