"""Pure dashboard authoring contracts and bounded semantic projections."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from pydantic import Field, model_validator

from gateway.dashboard.domain import ContractModel, DashboardDefinition, SemanticChartQuery
from gateway.dashboard.operations import DashboardOperation, apply_dashboard_operations
from gateway.models.dashboards import DashboardSemanticContext

FILTER_OPT_OUT_PATTERNS = (
    r"\bwithout (?:any )?(?:dashboard )?filters?\b",
    r"\bno (?:dashboard )?filters?\b",
    r"\bdo not (?:add|include|create|generate|show|use) (?:any )?(?:dashboard )?filters?\b",
    r"\bdon['’]t (?:add|include|create|generate|show|use) (?:any )?(?:dashboard )?filters?\b",
    r"\bomit (?:all )?(?:dashboard )?filters?\b",
    r"\bfilterless dashboard\b",
    r"\bsem filtros?\b",
    r"\bn[aã]o (?:adicione|inclua|crie|use) filtros?\b",
    r"\bn[aã]o quero filtros?\b",
)


class DashboardAgentDraft(ContractModel):
    summary: str = Field(min_length=1, max_length=1000)
    definition: DashboardDefinition | None = None
    operations: list[DashboardOperation] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def exactly_one_payload(self) -> DashboardAgentDraft:
        if (self.definition is None) == (not self.operations):
            raise ValueError("Agent draft must contain either a complete definition or typed operations")
        return self


def canonicalize_agent_draft_query_encodings(
    value: Any,
    context: DashboardSemanticContext,
) -> Any:
    """Repair only unambiguous raw visualization references before contract validation."""
    if not isinstance(value, dict) or not isinstance(value.get("definition"), dict):
        return value
    normalized = deepcopy(value)
    charts = normalized["definition"].get("charts")
    if not isinstance(charts, list):
        return normalized
    metric_formats = {
        metric.field_id: metric.format for explore in context.explores for metric in explore.metrics if metric.format
    }

    def resolve(reference: Any, candidates: list[str], *, singleton: bool = False) -> Any:
        if not isinstance(reference, str) or reference in candidates:
            return reference
        folded = reference.casefold()
        matches = [
            candidate
            for candidate in candidates
            if candidate.casefold() == folded or candidate.rsplit(".", 1)[-1].casefold() == folded
        ]
        if len(matches) == 1:
            return matches[0]
        if singleton and len(candidates) == 1:
            return candidates[0]
        return reference

    for chart in charts:
        if not isinstance(chart, dict):
            continue
        query = chart.get("query")
        visualization = chart.get("visualization")
        if not isinstance(query, dict) or query.get("kind") != "semantic" or not isinstance(visualization, dict):
            continue
        dimensions = [item for item in query.get("dimensions", []) if isinstance(item, str)]
        metrics = [item for item in query.get("metrics", []) if isinstance(item, str)]
        config = visualization.get("config")
        if not isinstance(config, dict):
            continue
        if visualization.get("type") == "big_number":
            config["field"] = resolve(config.get("field"), metrics, singleton=True)
            governed_format = metric_formats.get(config["field"])
            if governed_format:
                config["format"] = "decimal" if governed_format == "number" else governed_format
        elif visualization.get("type") == "cartesian":
            layout = config.get("layout")
            if not isinstance(layout, dict):
                continue
            layout["xField"] = resolve(layout.get("xField"), dimensions, singleton=True)
            y_fields = layout.get("yField")
            if isinstance(y_fields, list):
                singleton = len(y_fields) == 1
                layout["yField"] = [resolve(item, metrics, singleton=singleton) for item in y_fields]
        elif visualization.get("type") == "table":
            outputs = [*dimensions, *metrics]
            for key in ("columns", "groups"):
                references = config.get(key)
                if isinstance(references, list):
                    config[key] = [resolve(item, outputs) for item in references]
    return normalized


def compact_semantic_projection(context: DashboardSemanticContext) -> dict[str, Any]:
    """Bounded agent-facing projection; it does not create a second catalog."""
    return {
        "project_id": context.project_id,
        "commit_sha": context.commit_sha,
        "connection_name": context.connection_name,
        "connection_type": context.connection_type,
        "semantic_fingerprint": context.semantic_fingerprint,
        "explores": [
            {
                "name": explore.name,
                "label": explore.label,
                "description": explore.description,
                "dimensions": [
                    {
                        "field_id": field.field_id,
                        "logical_type": field.logical_type,
                        "description": field.description,
                        "filter_target": {
                            "tableName": explore.name,
                            "fieldId": field.field_id,
                        },
                    }
                    for field in explore.dimensions
                ],
                "metrics": [
                    {
                        "field_id": metric.field_id,
                        "label": metric.label,
                        "aggregation": metric.aggregation,
                        "format": metric.format,
                        "human_verified": metric.human_verified,
                    }
                    for metric in explore.metrics
                ],
            }
            for explore in context.explores
        ],
        "verification_refs": context.verification_refs,
        "eval_refs": context.eval_refs,
    }


def explicitly_omits_filters(prompt: str) -> bool:
    normalized = " ".join(prompt.casefold().split())
    return any(re.search(pattern, normalized) for pattern in FILTER_OPT_OUT_PATTERNS)


def add_default_governed_date_filter(
    draft: DashboardAgentDraft,
    context: DashboardSemanticContext,
) -> DashboardAgentDraft:
    """Add a bounded date control when creation omitted filters and the mapping is governed."""
    definition = draft.definition
    if definition is None or definition.filters.dimensions or definition.filters.metrics:
        return draft
    date_fields_by_explore = {
        explore.name: [field for field in explore.dimensions if field.logical_type in {"date", "timestamp"}]
        for explore in context.explores
    }
    selected_explore: str | None = None
    selected_field = None
    for chart in definition.charts:
        if not isinstance(chart.query, SemanticChartQuery):
            continue
        candidates = {field.field_id: field for field in date_fields_by_explore.get(chart.query.exploreName, [])}
        selected_field = next(
            (candidates[field_id] for field_id in chart.query.dimensions if field_id in candidates),
            None,
        )
        if selected_field is not None:
            selected_explore = chart.query.exploreName
            break
    if selected_field is None:
        for explore in context.explores:
            fields = date_fields_by_explore.get(explore.name, [])
            if fields:
                selected_explore = explore.name
                selected_field = fields[0]
                break
    if selected_explore is None or selected_field is None:
        return draft

    charts_by_id = {chart.id: chart for chart in definition.charts}
    tile_targets: dict[str, dict[str, str] | bool] = {}
    for tile in definition.tiles:
        chart = charts_by_id.get(tile.chartId)
        if chart is None or not isinstance(chart.query, SemanticChartQuery):
            tile_targets[tile.uuid] = False
            continue
        target_fields = date_fields_by_explore.get(chart.query.exploreName, [])
        if not target_fields:
            tile_targets[tile.uuid] = False
            continue
        target_field = selected_field if chart.query.exploreName == selected_explore else target_fields[0]
        tile_targets[tile.uuid] = {
            "tableName": chart.query.exploreName,
            "fieldId": target_field.field_id,
        }

    payload = definition.model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"] = [
        {
            "id": "date-filter",
            "operator": "inThePast",
            "values": [30],
            "target": {"tableName": selected_explore, "fieldId": selected_field.field_id},
            "tileTargets": tile_targets,
            "label": selected_field.label or selected_field.column.replace("_", " ").title(),
            "settings": {"unitOfTime": "days"},
        }
    ]
    return draft.model_copy(update={"definition": DashboardDefinition.model_validate(payload)})


def draft_has_filters(draft: DashboardAgentDraft, *, base_definition: DashboardDefinition | None) -> bool:
    definition = materialize_agent_draft(draft, base_definition=base_definition)
    return bool(definition.filters.dimensions or definition.filters.metrics)


def materialize_agent_draft(
    draft: DashboardAgentDraft,
    *,
    base_definition: DashboardDefinition | None,
) -> DashboardDefinition:
    if draft.definition is not None:
        return draft.definition
    if base_definition is None:
        raise ValueError("Typed updates require a base dashboard version")
    return apply_dashboard_operations(base_definition, draft.operations)
