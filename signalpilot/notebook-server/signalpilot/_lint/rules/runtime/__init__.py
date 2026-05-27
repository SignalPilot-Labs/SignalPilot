from __future__ import annotations

from signalpilot._lint.rules.base import LintRule
from signalpilot._lint.rules.runtime.branch_expression import BranchExpressionRule
from signalpilot._lint.rules.runtime.reusable_definition_order import (
    ReusableDefinitionOrderRule,
)
from signalpilot._lint.rules.runtime.self_import import SelfImportRule

RUNTIME_RULE_CODES: dict[str, type[LintRule]] = {
    "MR001": SelfImportRule,
    "MR002": BranchExpressionRule,
    "MR003": ReusableDefinitionOrderRule,
}

__all__ = [
    "RUNTIME_RULE_CODES",
    "BranchExpressionRule",
    "ReusableDefinitionOrderRule",
    "SelfImportRule",
]
