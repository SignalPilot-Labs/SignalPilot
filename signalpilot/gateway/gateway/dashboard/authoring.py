"""Model-backed dashboard draft creation constrained by typed contracts."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from pydantic import Field, model_validator

from gateway.analysis_delivery.model_client import AnthropicMessagesClient, MessagesModelClient
from gateway.dashboard.domain import ContractModel, DashboardDefinition
from gateway.dashboard.operations import DashboardOperation, apply_dashboard_operations
from gateway.models.dashboards import DashboardSemanticContext

DEFAULT_DASHBOARD_AUTHORING_MODEL = "claude-sonnet-4-5-20250929"

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


def compact_semantic_projection(context: DashboardSemanticContext) -> dict[str, Any]:
    """Bounded agent-facing projection; it does not create a second catalog."""
    return {
        "project_id": context.project_id,
        "commit_sha": context.commit_sha,
        "connection_name": context.connection_name,
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
    def __init__(self, *, api_key: str, model_client: MessagesModelClient | None = None) -> None:
        self.model = os.getenv("SIGNALPILOT_DASHBOARD_AUTHORING_MODEL") or DEFAULT_DASHBOARD_AUTHORING_MODEL
        self.model_client = model_client or AnthropicMessagesClient(api_key=api_key, timeout_seconds=90)

    async def draft(
        self,
        *,
        prompt: str,
        context: DashboardSemanticContext,
        base_definition: DashboardDefinition | None,
    ) -> DashboardAgentDraft:
        mode = "update" if base_definition is not None else "create"
        contract = DashboardAgentDraft.model_json_schema(by_alias=True)
        system = (
            "You are SignalPilot's governed dashboard author. Use only the supplied explores, fields, and metrics. "
            "Use only KPI, table, bar, line, and area visualizations. Each semantic chart queries one explore. "
            "For every chart, write three distinct pieces of business copy: question is a concise natural-language "
            "question shown at the top left and ending in a question mark; title is a short 2-5 word business label "
            "such as Total Revenue or Net Revenue; description is one useful sentence. For Cartesian charts, begin "
            "the description with the visualization type, for example 'Line chart showing monthly net revenue.' "
            "Prefer compact KPI tiles in 12-column thirds and full-width 36-column Cartesian trend charts when the "
            "requested dashboard composition allows it. Arrange every dashboard row on the 36-column grid so tile "
            "widths sum to exactly 36, tiles use increasing x and y positions, and no row leaves unused horizontal space. "
            "Every dashboard must include useful global filter controls unless the user's request explicitly says to omit "
            "filters. Prefer a date filter when a governed date or timestamp dimension is available, then add a small "
            "number of business-relevant categorical controls. Use explicit per-tile targets across explores and mark "
            "incompatible tiles as false. When updating a draft that has no controls, add them in the same typed operation "
            "set unless the current request explicitly opts out. Do not treat silence about filters as an opt-out. "
            "Never emit renderer options, code, HTML, or SQL. For creation return a complete definition. "
            "For updates return typed operations using stable IDs and do not rewrite unrelated charts. "
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

        async def request_draft(body: dict[str, Any]) -> DashboardAgentDraft:
            response = await self.model_client.create_message(body)
            content = response.get("content")
            if not isinstance(content, list):
                raise ValueError("Dashboard authoring model returned no tool result")
            tool_input = next(
                (
                    block.get("input")
                    for block in content
                    if isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "submit_dashboard_draft"
                ),
                None,
            )
            return DashboardAgentDraft.model_validate(tool_input)

        draft = await request_draft(request_body)
        if not explicitly_omits_filters(prompt) and not draft_has_filters(draft, base_definition=base_definition):
            repair_payload = {
                **payload,
                "rejected_draft": draft.model_dump(mode="json", by_alias=True, exclude_none=True),
                "validation_feedback": (
                    "The previous draft was rejected because it omitted dashboard filter controls. Add useful governed "
                    "filters now. Prefer a date filter when available, include explicit per-tile targets, and preserve "
                    "all otherwise valid chart and layout work."
                ),
            }
            request_body = {
                **request_body,
                "messages": [{"role": "user", "content": json.dumps(repair_payload, default=str)}],
            }
            draft = await request_draft(request_body)
            if not draft_has_filters(draft, base_definition=base_definition):
                raise ValueError("Dashboard authoring requires at least one governed filter control")
        if base_definition is None and draft.definition is None:
            raise ValueError("Dashboard creation requires a complete definition")
        if base_definition is not None and draft.definition is not None:
            raise ValueError("Dashboard updates require typed operations")
        return draft


def explicitly_omits_filters(prompt: str) -> bool:
    normalized = " ".join(prompt.casefold().split())
    return any(re.search(pattern, normalized) for pattern in FILTER_OPT_OUT_PATTERNS)


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
