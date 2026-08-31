"""Context shaping for the durable standalone-chat worker."""

from __future__ import annotations

import os
from typing import Any

from gateway import __version__ as gateway_version
from gateway.standalone_chat.projects import project_metadata_context


def message_context(context: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": row.role, "content": row.content}
        for row in context["messages"]
        if row.role in {"user", "assistant"}
    ]


def merge_text_delta(
    current: str, delta: str, *, starts_new_block: bool
) -> tuple[str, str]:
    if not delta:
        return current, ""
    separator = ""
    if current and starts_new_block:
        trailing_newlines = len(current) - len(current.rstrip("\n"))
        leading_newlines = len(delta) - len(delta.lstrip("\n"))
        separator = "\n" * max(0, 2 - trailing_newlines - leading_newlines)
    emitted = f"{separator}{delta}"
    return f"{current}{emitted}", emitted


def warm_context(
    context: dict[str, Any],
    *,
    summary_override: str | None = None,
) -> dict[str, Any]:
    conversation = context["conversation"]
    project = context["project"]
    artifacts = context["artifacts"]
    artifact_refs = [
        _artifact_reference(artifact, include_snapshot=index >= max(0, len(artifacts) - 5))
        for index, artifact in enumerate(artifacts)
    ]
    artifact_refs.reverse()

    approvals = {
        approval.proposal_id: approval
        for approval in context.get("query_approvals", [])
    }
    query_decisions = [
        {
            "proposal_id": proposal.id,
            "purpose": proposal.purpose,
            "sql_hash": proposal.sql_hash,
            "status": proposal.status,
            "estimated_cost_usd": proposal.estimated_cost_usd,
            "decision": (
                approvals[proposal.id].decision if proposal.id in approvals else None
            ),
        }
        for proposal in context.get("query_proposals", [])
    ]

    executions = {
        execution.id: execution
        for execution in context.get("query_executions", [])
    }
    result_refs = [
        {
            "result_id": result.id,
            "execution_id": result.execution_id,
            "columns": result.columns_json,
            "query_row_count": result.query_row_count,
            "saved_row_count": result.saved_row_count,
            "completeness": result.result_completeness,
            "truncation_reason": result.truncation_reason,
            "provenance": result.provenance_json,
            "connection_name": (
                executions[result.execution_id].connection_name
                if result.execution_id in executions
                else None
            ),
        }
        for result in context.get("query_results", [])
    ]

    return {
        "project": {
            "id": project.id,
            "name": project.display_name or project.name,
            "description": project.description,
            "default_branch": conversation.branch,
            "commit_sha": conversation.commit_sha,
            "connection_name": project.connection_name,
            "dbt_metadata": project_metadata_context(
                project, conversation.branch or "main"
            ),
        },
        "conversation_summary": summary_override or conversation.internal_summary,
        "prior_artifacts": artifact_refs,
        "query_decisions": query_decisions,
        "structured_results": result_refs,
        "report_reference": _latest_message_reference(context, "report_reference"),
        "dashboard_chart_reference": _latest_message_reference(
            context, "dashboard_chart_reference"
        ),
        "runtime": {
            "gateway_version": gateway_version,
            "plugin_version": os.getenv("SIGNALPILOT_PLUGIN_VERSION", "deployed"),
        },
    }


def _artifact_reference(artifact: Any, *, include_snapshot: bool) -> dict[str, Any]:
    snapshot = artifact.snapshot_json or {}
    reference: dict[str, Any] = {
        "id": artifact.id,
        "kind": artifact.kind,
        "filename": artifact.filename,
        "parent_artifact_id": artifact.parent_artifact_id,
        "schema": {
            "columns": snapshot.get("columns")
            or (snapshot.get("source") or {}).get("columns"),
            "truncated": snapshot.get("truncated", False),
        },
        "provenance": artifact.provenance_json,
        "freshness_at": (
            artifact.freshness_at.isoformat() if artifact.freshness_at else None
        ),
        "assumptions": artifact.assumptions,
        "exclusions": artifact.exclusions,
        "caveats": artifact.caveats,
    }
    if not include_snapshot:
        return reference
    if artifact.kind == "report":
        reference["snapshot"] = {
            "html_excerpt": str(snapshot.get("html") or "")[:20_000]
        }
        return reference
    rows = (
        (snapshot.get("source") or {}).get("rows")
        if artifact.kind == "chart"
        else snapshot.get("rows")
    )
    reference["snapshot"] = {
        "spec": snapshot.get("spec") if artifact.kind == "chart" else None,
        "rows": list(rows or [])[:200],
        "snapshot_row_count": len(rows or []),
    }
    return reference


def _latest_message_reference(
    context: dict[str, Any], key: str
) -> dict[str, Any] | None:
    return next(
        (
            message.metadata_json[key]
            for message in reversed(context.get("messages", []))
            if message.role == "user"
            and isinstance(message.metadata_json, dict)
            and isinstance(message.metadata_json.get(key), dict)
        ),
        None,
    )
