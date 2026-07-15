"""Shared orchestration helpers for notebook-backed external analysis."""

from .credentials import delivery_api_key_for_org
from .followups import DeliverableFollowupPlan, plan_deliverable_followup
from .html_orchestrator import (
    HtmlDeliverableResult,
    HtmlOrchestrator,
    render_followup,
    render_html_deliverable,
)
from .preflight import (
    AnalysisPreflightDecision,
    AnalysisPreflightKind,
    classify_analysis_request,
    wants_html_deliverable,
)
from .progress import (
    ANALYSIS_INITIAL_PROGRESS_TEXT,
    SlackTraceProgressReporter,
    render_slack_final_message,
    render_slack_progress_message,
)
from .renderer import (
    DeliveryRenderer,
    DeliveryResult,
    delivery_result_to_status,
    render_delivery,
)
from .trace_loader import (
    DeliveryPacket,
    FinalStatement,
    WorkerPlan,
    WorkerProgress,
    load_delivery_packet,
    load_delivery_packet_from_events,
)

__all__ = [
    "ANALYSIS_INITIAL_PROGRESS_TEXT",
    "AnalysisPreflightDecision",
    "AnalysisPreflightKind",
    "DeliveryPacket",
    "DeliveryRenderer",
    "DeliveryResult",
    "DeliverableFollowupPlan",
    "FinalStatement",
    "HtmlDeliverableResult",
    "HtmlOrchestrator",
    "SlackTraceProgressReporter",
    "WorkerPlan",
    "WorkerProgress",
    "classify_analysis_request",
    "delivery_api_key_for_org",
    "delivery_result_to_status",
    "load_delivery_packet",
    "load_delivery_packet_from_events",
    "render_delivery",
    "render_followup",
    "render_html_deliverable",
    "render_slack_final_message",
    "render_slack_progress_message",
    "wants_html_deliverable",
    "plan_deliverable_followup",
]
