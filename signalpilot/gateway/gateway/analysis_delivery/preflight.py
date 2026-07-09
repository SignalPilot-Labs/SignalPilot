"""Preflight request classification for external analysis channels."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class AnalysisPreflightKind(StrEnum):
    DIRECT = "direct"
    AMBIGUOUS = "ambiguous"
    ANALYZE = "analyze"


@dataclass(frozen=True)
class AnalysisPreflightDecision:
    kind: AnalysisPreflightKind
    response: str | None = None


_GREETING_PATTERNS = (
    r"hi+",
    r"hello+",
    r"hey+",
    r"yo+",
    r"good\s+(morning|afternoon|evening)",
)
_THANKS_PATTERNS = (
    r"thanks?",
    r"thank\s+you",
    r"ty",
    r"ok(?:ay)?",
    r"cool",
)
_CLEAR_ACTION_TERMS = {
    "analyze",
    "analyse",
    "compare",
    "calculate",
    "compute",
    "find",
    "show",
    "plot",
    "chart",
    "rank",
    "summarize",
    "summarise",
    "breakdown",
    "break",
    "trend",
    "forecast",
    "estimate",
    "evaluate",
    "investigate",
    "explain",
}
_DATA_TERMS = {
    "arr",
    "booking",
    "bookings",
    "churn",
    "cohort",
    "conversion",
    "cost",
    "customer",
    "customers",
    "data",
    "database",
    "db",
    "ebitda",
    "gmv",
    "growth",
    "lead",
    "leads",
    "margin",
    "marts",
    "metric",
    "metrics",
    "mrr",
    "orders",
    "pipeline",
    "profit",
    "revenue",
    "sales",
    "schema",
    "table",
    "tables",
    "transfer",
    "transfers",
    "usage",
}
_SPECIFICITY_TERMS = {
    "by",
    "for",
    "from",
    "last",
    "monthly",
    "quarter",
    "quarterly",
    "q1",
    "q2",
    "q3",
    "q4",
    "this",
    "top",
    "trend",
    "vs",
    "versus",
    "week",
    "weekly",
    "year",
    "yearly",
    "ytd",
}
_HTML_DELIVERABLE_PATTERNS = (
    r"\b(?:dashboard|scorecard)\b",
    r"\b(?:build|create|make|generate|show|produce)\s+(?:a\s+)?(?:data[-\s]+backed\s+)?report\b",
    r"\b(?:html|interactive|static)\s+(?:dashboard|report)\b",
    r"\breport\s+(?:with|using|from|based\s+on)\s+(?:the\s+)?(?:data|db|database|metrics|revenue|sales|customers)\b",
)

DIRECT_GREETING_RESPONSE = "Hi. Send me a specific data question and I will run it through SignalPilot."
DIRECT_THANKS_RESPONSE = "You are welcome. Send a specific data question when you want me to analyze something."
AMBIGUOUS_ANALYSIS_RESPONSE = (
    "SignalPilot needs a fresh, specific analysis request before it starts a notebook run. "
    "For example: `Compare monthly revenue by product for Q2 and show the top drivers.`"
)


def classify_analysis_request(prompt: str) -> AnalysisPreflightDecision:
    normalized = _normalize(prompt)
    if not normalized:
        return AnalysisPreflightDecision(
            AnalysisPreflightKind.DIRECT,
            "Ask me a specific data question and I will run it through SignalPilot.",
        )

    if _matches_any(normalized, _GREETING_PATTERNS):
        return AnalysisPreflightDecision(AnalysisPreflightKind.DIRECT, DIRECT_GREETING_RESPONSE)
    if _matches_any(normalized, _THANKS_PATTERNS):
        return AnalysisPreflightDecision(AnalysisPreflightKind.DIRECT, DIRECT_THANKS_RESPONSE)

    if wants_html_deliverable(normalized):
        return AnalysisPreflightDecision(AnalysisPreflightKind.ANALYZE)

    words = re.findall(r"[a-z0-9_.$%-]+", normalized)
    word_set = set(words)
    has_data_term = bool(word_set & _DATA_TERMS) or _looks_like_table_reference(normalized)
    has_clear_action = bool(word_set & _CLEAR_ACTION_TERMS)
    has_specificity = bool(word_set & _SPECIFICITY_TERMS) or _has_date_or_number(normalized)

    if has_clear_action and (has_data_term or len(words) >= 3):
        return AnalysisPreflightDecision(AnalysisPreflightKind.ANALYZE)
    if has_data_term and has_specificity and len(words) >= 4:
        return AnalysisPreflightDecision(AnalysisPreflightKind.ANALYZE)
    if normalized.endswith("?") and has_data_term and len(words) >= 4:
        return AnalysisPreflightDecision(AnalysisPreflightKind.ANALYZE)
    if has_data_term:
        return AnalysisPreflightDecision(AnalysisPreflightKind.AMBIGUOUS, AMBIGUOUS_ANALYSIS_RESPONSE)

    if len(words) <= 3:
        return AnalysisPreflightDecision(
            AnalysisPreflightKind.DIRECT,
            "Send me a specific data question and I will run it through SignalPilot.",
        )
    return AnalysisPreflightDecision(AnalysisPreflightKind.AMBIGUOUS, AMBIGUOUS_ANALYSIS_RESPONSE)


def wants_html_deliverable(prompt: str) -> bool:
    normalized = _normalize(prompt)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _HTML_DELIVERABLE_PATTERNS)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.fullmatch(pattern, value) for pattern in patterns)


def _looks_like_table_reference(value: str) -> bool:
    return bool(re.search(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\b", value))


def _has_date_or_number(value: str) -> bool:
    return bool(re.search(r"\b(?:20\d{2}|q[1-4]|\d+(?:\.\d+)?%?)\b", value))
