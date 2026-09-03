"""Per-run state for one standalone chat execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StandaloneArtifactCollector:
    """Run-scoped results the in-process tools record for the final payload."""

    dashboard_preview: dict[str, Any] | None = None


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
