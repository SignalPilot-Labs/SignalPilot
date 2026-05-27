from __future__ import annotations

from signalpilot._lint.rules.base import LintRule, UnsafeFixRule
from signalpilot._lint.rules.formatting.empty_cells import EmptyCellRule
from signalpilot._lint.rules.formatting.general import GeneralFormattingRule
from signalpilot._lint.rules.formatting.markdown_dedent import MarkdownDedentRule
from signalpilot._lint.rules.formatting.parsing import (
    MiscLogRule,
    SqlParseRule,
    StderrRule,
    StdoutRule,
)

FORMATTING_RULE_CODES: dict[str, type[LintRule]] = {
    "MF001": GeneralFormattingRule,
    "MF002": StdoutRule,
    "MF003": StderrRule,
    "MF004": EmptyCellRule,
    "MF005": SqlParseRule,
    "MF006": MiscLogRule,
    "MF007": MarkdownDedentRule,
}

__all__ = [
    "FORMATTING_RULE_CODES",
    "EmptyCellRule",
    "GeneralFormattingRule",
    "MarkdownDedentRule",
    "MiscLogRule",
    "SqlParseRule",
    "StderrRule",
    "StdoutRule",
    "UnsafeFixRule",
]
