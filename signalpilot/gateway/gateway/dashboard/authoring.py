"""Model-backed dashboard draft creation constrained by typed contracts."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from pydantic import Field, model_validator

from gateway.analysis_delivery.model_client import (
    AnthropicMessagesClient,
    ClaudeAgentSDKStructuredClient,
    MessagesModelClient,
)
from gateway.dashboard.domain import ContractModel, DashboardDefinition, SemanticChartQuery
from gateway.dashboard.operations import DashboardOperation, apply_dashboard_operations
from gateway.models.dashboards import DashboardSemanticContext

DEFAULT_DASHBOARD_AUTHORING_MODEL = "claude-sonnet-4-5-20250929"
DASHBOARD_AUTHORING_TIMEOUT_SECONDS = 240
logger = logging.getLogger(__name__)

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
MAX_DRAFT_ATTEMPTS = 3


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


class DashboardAuthoringAgent:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        oauth_token: str | None = None,
        model_client: MessagesModelClient | None = None,
    ) -> None:
        if api_key and oauth_token:
            raise ValueError("Configure only one dashboard authoring credential")
        self.model = os.getenv("SIGNALPILOT_DASHBOARD_AUTHORING_MODEL") or DEFAULT_DASHBOARD_AUTHORING_MODEL
        if model_client is not None:
            self.model_client = model_client
        elif oauth_token:
            self.model_client = ClaudeAgentSDKStructuredClient(
                oauth_token=oauth_token,
                timeout_seconds=DASHBOARD_AUTHORING_TIMEOUT_SECONDS,
                # The dashboard schema is too large for Claude Code's native
                # constrained decoder. Pydantic and compiler validation below
                # remain authoritative for the returned JSON object.
                use_native_structured_output=False,
            )
        else:
            self.model_client = AnthropicMessagesClient(
                api_key=api_key,
                timeout_seconds=DASHBOARD_AUTHORING_TIMEOUT_SECONDS,
            )

    async def draft(
        self,
        *,
        prompt: str,
        context: DashboardSemanticContext,
        base_definition: DashboardDefinition | None,
        validator: Callable[[DashboardAgentDraft], None] | None = None,
    ) -> DashboardAgentDraft:
        mode = "update" if base_definition is not None else "create"
        contract = DashboardAgentDraft.model_json_schema(by_alias=True)
        system = (
            "You are SignalPilot's governed dashboard author. Use only the supplied explores, fields, and metrics. "
            "Use only KPI, table, bar, line, and area visualizations. Each semantic chart queries one explore. Copy "
            "exploreName exactly from semantic_context.explores[].name; never invent an explore or use placeholders "
            "such as <UNKNOWN>. "
            "For every chart, write three distinct pieces of business copy: question is a concise natural-language "
            "question shown at the top left and ending in a question mark; title is a short 2-5 word business label "
            "such as Total Revenue or Net Revenue; description is one useful sentence. For Cartesian charts, begin "
            "the description with the visualization type, for example 'Line chart showing monthly net revenue.' "
            "Prefer compact KPI tiles in 12-column thirds and full-width 36-column Cartesian trend charts when the "
            "requested dashboard composition allows it. Arrange every dashboard row on the 36-column grid so tile "
            "widths sum to exactly 36, tiles use increasing x and y positions, and no row leaves unused horizontal space. "
            "Every dashboard must include useful global filter controls unless the user's request explicitly says to omit "
            "filters. For dashboards with time-series charts, include an applicable governed date or timestamp filter "
            "with a valid bounded default window and use a time aggregation coarse enough for that window. Otherwise, "
            "prefer a date filter when a governed date or timestamp dimension is available, then add a small "
            "number of business-relevant categorical controls. Use explicit per-tile targets across explores and mark "
            "incompatible tiles as false. Copy each filter target exactly from the dimension's filter_target object; fieldId "
            "must remain the complete supplied field_id, including its explore prefix. When updating a draft that has no "
            "controls, add them in the same typed operation "
            "set unless the current request explicitly opts out. Do not treat silence about filters as an opt-out. "
            "Every visualization encoding must copy an exact field ID already present in that chart's query: KPI field "
            "and Cartesian yField values come from query.metrics, while Cartesian xField comes from query.dimensions. "
            "For KPI format, copy the governed metric format when supplied; use percentage, never percent. "
            "For every applicable semantic bar, line, or area chart, configure a meaningful lower-grain drill hierarchy "
            "in signalPilot.drillDimensions when the same explore supplies a dimension below the chart's current business "
            "grain. Order drill dimensions from the immediate next level to the deepest level and copy complete field_id "
            "values exactly. Never repeat a query dimension or repeat a level within drillDimensions. For example, a chart "
            "grouped by region may drill to customer when customer is the lower-grain governed dimension. Omit a drill "
            "hierarchy only when the explore has no meaningful lower-grain dimension for that chart. "
            "Never emit renderer options, code, HTML, or SQL. For creation return a complete definition. "
            "The semantic context includes the server-authorized database type; never assume syntax from another "
            "database or invent a connection type. "
            "For updates return typed operations using stable IDs and do not rewrite unrelated charts. "
            "Never return a refusal-only summary, a null definition, or an empty operation list. When the request "
            "names a business concept without an exact approved metric, use the closest faithful governed metric or "
            "dimension when one is available, explain that substitution in the summary, and omit only the unsupported "
            "element rather than refusing the entire dashboard. "
            "The server validates all output and the user must explicitly apply it."
        )
        payload = {
            "mode": mode,
            "request": prompt,
            "semantic_context": compact_semantic_projection(context),
            "base_definition": (
                base_definition.model_dump(mode="json", by_alias=True, exclude_none=True)
                if base_definition is not None
                else None
            ),
        }
        request_body = {
            "model": self.model,
            "max_tokens": 16_000,
            "system": system,
            "messages": [{"role": "user", "content": json.dumps(payload, default=str)}],
            "tools": [
                {
                    "name": "submit_dashboard_draft",
                    "description": "Return one validated dashboard draft or typed update operation list.",
                    "input_schema": contract,
                }
            ],
            "tool_choice": {"type": "tool", "name": "submit_dashboard_draft"},
        }

        async def request_tool_input(body: dict[str, Any]) -> Any:
            response = await self.model_client.create_message(body)
            content = response.get("content")
            if not isinstance(content, list):
                raise ValueError("Dashboard authoring model returned no tool result")
            return next(
                (
                    block.get("input")
                    for block in content
                    if isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "submit_dashboard_draft"
                ),
                None,
            )

        last_error: ValueError | None = None
        validation_errors: list[str] = []
        for attempt in range(MAX_DRAFT_ATTEMPTS):
            rejected_draft: Any = None
            try:
                rejected_draft = await request_tool_input(request_body)
                rejected_draft = canonicalize_agent_draft_query_encodings(rejected_draft, context)
                draft = DashboardAgentDraft.model_validate(rejected_draft)
                if base_definition is None and draft.definition is None:
                    raise ValueError("Dashboard creation requires a complete definition")
                if base_definition is not None and draft.definition is not None:
                    raise ValueError("Dashboard updates require typed operations")
                if not explicitly_omits_filters(prompt):
                    draft = add_default_governed_date_filter(draft, context)
                if not explicitly_omits_filters(prompt) and not draft_has_filters(
                    draft, base_definition=base_definition
                ):
                    raise ValueError(
                        "Dashboard authoring requires at least one governed filter control. Add a useful governed "
                        "filter, prefer a bounded date filter when available, and include explicit per-tile targets."
                    )
                if validator is not None:
                    validator(draft)
                return draft
            except ValueError as exc:
                error_text = str(exc)[:6000]
                empty_payload_feedback: str | None = None
                if (
                    isinstance(rejected_draft, dict)
                    and rejected_draft.get("definition") is None
                    and not rejected_draft.get("operations")
                ):
                    if mode == "create":
                        empty_payload_feedback = (
                            "The previous response was a refusal or empty payload. Dashboard creation must return a "
                            "complete definition; do not return a limitation-only summary, null definition, or empty "
                            "operations. Build the closest faithful dashboard supported by semantic_context. If a "
                            "requested concept has no exact approved metric, use a faithful governed dimension or metric "
                            "when available, explain the substitution in summary, and omit only that unsupported element."
                        )
                    else:
                        empty_payload_feedback = (
                            "The previous response was a refusal or empty payload. Dashboard updates must return at "
                            "least one typed operation; do not return a limitation-only summary, null definition, or "
                            "empty operations. Apply the closest faithful update supported by semantic_context and the "
                            "base definition without inventing fields or metrics."
                        )
                last_error = ValueError(empty_payload_feedback) if empty_payload_feedback else exc
                if empty_payload_feedback and empty_payload_feedback not in validation_errors:
                    validation_errors.append(empty_payload_feedback)
                if error_text not in validation_errors:
                    validation_errors.append(error_text)
                logger.warning(
                    "Dashboard authoring draft rejected attempt=%s/%s error=%s",
                    attempt + 1,
                    MAX_DRAFT_ATTEMPTS,
                    str(exc)[:1000],
                )
                if attempt + 1 >= MAX_DRAFT_ATTEMPTS:
                    raise
                repair_payload = {
                    **payload,
                    "validation_feedback": (
                        "The server rejected the previous draft. Correct every reported contract or semantic error, "
                        "copy explore and field identifiers exactly from semantic_context, preserve otherwise valid "
                        f"work, and resubmit the complete {mode} payload. Valid exploreName values: "
                        f"{', '.join(explore.name for explore in context.explores) or 'none'}. Never use <UNKNOWN> "
                        "or another placeholder. Preserve every correction from earlier attempts. All validation "
                        "failures reported so far must be fixed together:\n- " + "\n- ".join(validation_errors)
                    ),
                }
                if rejected_draft is not None:
                    repair_payload["rejected_draft"] = rejected_draft
                request_body = {
                    **request_body,
                    "messages": [{"role": "user", "content": json.dumps(repair_payload, default=str)}],
                }
        assert last_error is not None
        raise last_error


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
