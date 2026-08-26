from __future__ import annotations

from signalpilot._lint.rules.base import LintRule
from signalpilot._lint.rules.breaking.graph import (
    CycleDependenciesRule,
    MultipleDefinitionsRule,
    SetupCellDependenciesRule,
)
from signalpilot._lint.rules.breaking.syntax_error import SyntaxErrorRule
from signalpilot._lint.rules.breaking.unparsable import UnparsableRule

BREAKING_RULE_CODES: dict[str, type[LintRule]] = {
    "MB001": UnparsableRule,
    "MB002": MultipleDefinitionsRule,
    "MB003": CycleDependenciesRule,
    "MB004": SetupCellDependenciesRule,
    "MB005": SyntaxErrorRule,
}

__all__ = [
    "BREAKING_RULE_CODES",
    "CycleDependenciesRule",
    "MultipleDefinitionsRule",
    "SetupCellDependenciesRule",
    "SyntaxErrorRule",
    "UnparsableRule",
]
