"""Per-run state for one standalone chat execution."""

from __future__ import annotations

from dataclasses import dataclass, field


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
