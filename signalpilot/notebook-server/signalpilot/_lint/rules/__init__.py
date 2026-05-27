# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._lint.rules.base import LintRule
from signalpilot._lint.rules.breaking import BREAKING_RULE_CODES
from signalpilot._lint.rules.formatting import FORMATTING_RULE_CODES
from signalpilot._lint.rules.runtime import RUNTIME_RULE_CODES

RULE_CODES: dict[str, type[LintRule]] = (
    BREAKING_RULE_CODES | RUNTIME_RULE_CODES | FORMATTING_RULE_CODES
)

__all__ = [
    "BREAKING_RULE_CODES",
    "FORMATTING_RULE_CODES",
    "RULE_CODES",
    "RUNTIME_RULE_CODES",
]
