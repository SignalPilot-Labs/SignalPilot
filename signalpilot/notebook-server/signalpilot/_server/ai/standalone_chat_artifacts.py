"""Collected artifact and notebook lifecycle state for one chat run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StandaloneArtifactCollector:
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    report_proposal: dict[str, Any] | None = None
    report_action_outcome: dict[str, Any] | None = None
    report_catalog_revision: str | None = None
    next_report_catalog_cursor: str | None = None
    report_catalog_scan_complete: bool = False
    proactive_creation_allowed: bool = False
    loaded_report_ids: set[str] = field(default_factory=set)


@dataclass
class StandaloneNotebookLifecycle:
    # Every live kernel of the run, keyed by notebook name.
    sessions: dict[str, str] = field(default_factory=dict)

    @property
    def session_id(self) -> str | None:
        # Compatibility view: the analysis notebook's kernel session.
        return self.sessions.get("analysis")

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        if value is None:
            self.sessions.pop("analysis", None)
        else:
            self.sessions["analysis"] = value


def _clean_metadata(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": str(arguments.get("filename") or "").strip(),
        "freshness_at": arguments.get("freshness_at"),
        "assumptions": list(arguments.get("assumptions") or []),
        "exclusions": list(arguments.get("exclusions") or []),
        "caveats": list(arguments.get("caveats") or []),
        "provenance": dict(arguments.get("provenance") or {}),
        "parent_artifact_id": arguments.get("parent_artifact_id"),
    }


def _collected_artifact_is_complete(artifact: dict[str, Any]) -> bool:
    if (
        artifact.get("kind") not in {"table", "chart", "report"}
        or not str(artifact.get("filename") or "").strip()
    ):
        return False
    payload = (
        artifact.get("payload")
        if isinstance(artifact.get("payload"), dict)
        else {}
    )
    if artifact.get("kind") == "report":
        references = (artifact.get("provenance") or {}).get(
            "result_references"
        ) or []
        return bool(str(payload.get("html") or "").strip()) and all(
            not isinstance(reference, dict)
            or reference.get("completeness") == "complete"
            for reference in references
        )
    source = (
        payload.get("source") if artifact.get("kind") == "chart" else payload
    )
    return (
        isinstance(source, dict)
        and source.get("truncated") is not True
        and source.get("completeness") in {None, "complete"}
    )
