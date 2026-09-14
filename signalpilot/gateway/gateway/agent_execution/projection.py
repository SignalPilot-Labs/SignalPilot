"""Lightweight read-only views over existing ChatRunEventInfo records."""

SUMMARY_EVENT_TYPES = (
    "runtime_boot",
    "tool_started",
    "tool_completed",
    "status",
    "error",
    "clarification_requested",
    "query_approval_requested",
)


def summarize_event(event: dict) -> dict | None:
    kind = event["type"]
    if kind not in SUMMARY_EVENT_TYPES:
        return None
    source = event.get("payload") or {}
    payload = {}
    for field in ("tool", "status", "error", "chat_url", "phase"):
        if isinstance(source.get(field), (str, bool)):
            payload[field] = source[field][:240] if isinstance(source[field], str) else source[field]
    if isinstance(source.get("summary"), str):
        payload["summary"] = source["summary"][:240]
    return {**event, "payload": payload}
