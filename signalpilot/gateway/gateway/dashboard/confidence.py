"""Deterministic dashboard confidence and semantic matching."""

from __future__ import annotations

import hashlib
import json

from gateway.dashboard.domain import DashboardDefinition, SemanticChartQuery


def dashboard_confidence_counts(definition: DashboardDefinition) -> tuple[int, int]:
    high = sum(chart.query.kind == "semantic" for chart in definition.charts)
    return high, len(definition.charts) - high


def semantic_query_signature(query: SemanticChartQuery) -> str:
    payload = query.model_dump(mode="json")
    payload.pop("commitSha", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
