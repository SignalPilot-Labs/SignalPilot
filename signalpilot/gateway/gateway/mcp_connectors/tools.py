"""Tool inventory: defaults from annotations (R3), refresh merge, allowed sets.

Two controls per tool: ``enabled`` (enforced) and ``policy`` (auto | ask | off;
v1 uses auto and off). Defaults: ``readOnlyHint: true`` -> on/auto;
``destructiveHint: true`` or no ``readOnlyHint`` -> off. Tools discovered after
connect are always off and flagged ``is_new``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

POLICIES = ("auto", "ask", "off")
_MAX_DESCRIPTION = 2000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANNOTATION_KEYS = {
    "readOnlyHint": "read_only_hint",
    "destructiveHint": "destructive_hint",
    "idempotentHint": "idempotent_hint",
    "openWorldHint": "open_world_hint",
}


def plain_text(value: Any) -> str:
    """Provider text is data: strip control characters and cap the length."""
    if not isinstance(value, str):
        return ""
    cleaned = _CONTROL_CHARS.sub("", value).strip()
    return cleaned[:_MAX_DESCRIPTION]


def annotations_from_upstream(annotations: Any) -> dict[str, bool]:
    if annotations is None:
        return {}
    source = annotations if isinstance(annotations, dict) else annotations.model_dump(exclude_none=True)
    return {
        snake: bool(source[camel])
        for camel, snake in _ANNOTATION_KEYS.items()
        if source.get(camel) is not None
    }


def default_controls(annotations: dict[str, bool]) -> tuple[bool, str]:
    """(enabled, policy) seeded from annotations per R3."""
    if annotations.get("destructive_hint"):
        return False, "off"
    if annotations.get("read_only_hint") is True:
        return True, "auto"
    return False, "off"


def tool_info_from_upstream(tool: Any, *, discovered_at: str | None = None) -> dict[str, Any]:
    """Build a stored ToolInfo (with the upstream input schema) from an SDK Tool."""
    annotations = annotations_from_upstream(getattr(tool, "annotations", None))
    enabled, policy = default_controls(annotations)
    title = getattr(tool, "title", None)
    if not title and getattr(tool, "annotations", None) is not None:
        title = getattr(tool.annotations, "title", None)
    return {
        "name": str(tool.name),
        "title": plain_text(title) or None,
        "description": plain_text(getattr(tool, "description", None)),
        "annotations": annotations,
        "input_schema": dict(getattr(tool, "inputSchema", None) or {}),
        "enabled": enabled,
        "policy": policy,
        "discovered_at": discovered_at or datetime.now(UTC).isoformat(),
        "is_new": False,
    }


def merge_inventory(
    existing: list[dict[str, Any]],
    upstream: list[dict[str, Any]],
    *,
    first_connect: bool,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Merge a fresh upstream listing into the stored inventory.

    Known tools keep their enabled/policy decision (descriptions and schemas are
    refreshed). Tools not seen before are OFF and ``is_new`` unless this is the
    first listing. Tools the server dropped disappear. Returns (merged, added, removed).
    """
    known = {tool["name"]: tool for tool in existing}
    merged: list[dict[str, Any]] = []
    added: list[str] = []
    for tool in upstream:
        previous = known.get(tool["name"])
        if previous is None:
            entry = dict(tool)
            if not first_connect:
                entry["enabled"] = False
                entry["policy"] = "off"
                entry["is_new"] = True
                added.append(entry["name"])
            merged.append(entry)
            continue
        entry = dict(tool)
        entry["enabled"] = bool(previous.get("enabled", False))
        entry["policy"] = previous.get("policy") if previous.get("policy") in POLICIES else "off"
        entry["discovered_at"] = previous.get("discovered_at") or entry["discovered_at"]
        entry["is_new"] = bool(previous.get("is_new", False))
        merged.append(entry)
    removed = [name for name in known if name not in {tool["name"] for tool in upstream}]
    return merged, added, removed


def apply_tool_settings(tools: list[dict[str, Any]], settings: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply {tool_name: {enabled, policy}} to the stored inventory (org-level decision)."""
    updated: list[dict[str, Any]] = []
    for tool in tools:
        entry = dict(tool)
        change = settings.get(entry["name"])
        if change is not None:
            if "enabled" in change:
                entry["enabled"] = bool(change["enabled"])
            if change.get("policy") in POLICIES:
                entry["policy"] = change["policy"]
            entry["is_new"] = False
        updated.append(entry)
    return updated


def tool_is_on(tool: dict[str, Any]) -> bool:
    return bool(tool.get("enabled")) and tool.get("policy") != "off"


def allowed_tool_names(
    tools: list[dict[str, Any]],
    *,
    member_disabled: list[str] | None = None,
    run_origin: str = "user",
) -> list[str]:
    """Names the caller may use: on at the org level, not turned off by the member.

    Unattended runs (``run_origin != "user"``) only receive tools whose policy is
    ``auto``; ``ask`` tools need a person in the loop.
    """
    disabled = set(member_disabled or [])
    names: list[str] = []
    for tool in tools:
        if not tool_is_on(tool) or tool["name"] in disabled:
            continue
        if run_origin != "user" and tool.get("policy") != "auto":
            continue
        names.append(tool["name"])
    return names


def public_tool_info(tool: dict[str, Any]) -> dict[str, Any]:
    """ToolInfo exactly as the API contract lists it (no input schema)."""
    return {
        "name": tool["name"],
        "title": tool.get("title"),
        "description": tool.get("description") or "",
        "annotations": dict(tool.get("annotations") or {}),
        "enabled": bool(tool.get("enabled")),
        "policy": tool.get("policy") if tool.get("policy") in POLICIES else "off",
        "discovered_at": tool.get("discovered_at"),
        "is_new": bool(tool.get("is_new")),
    }
