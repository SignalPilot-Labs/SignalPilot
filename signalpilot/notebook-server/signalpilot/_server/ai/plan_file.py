"""The run plan as a markdown file.

Claude Code 2.1.280 has no TodoWrite tool, so the chat agent keeps its plan in
``$SP_CHAT_ARTIFACTS_DIRECTORY/plan.md`` as a GitHub task list:

    # Plan: <what the run does>
    - [x] A finished step
    - [ ] The next step

A checked box is a finished step; the first unchecked box is the current step.
The web plan dock reads the same file from the Write/Edit tool events.
"""

from __future__ import annotations

import re
from pathlib import Path

PLAN_FILE_NAME = "plan.md"
# The file tools the agent writes the plan with.
PLAN_FILE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})
_OPEN_ITEM = re.compile(r"^\s*[-*+]\s+\[ \]\s+\S", re.MULTILINE)


def is_plan_file_path(path: object) -> bool:
    """True for ``.../artifacts/plan.md`` in any path style."""
    if not isinstance(path, str) or not path:
        return False
    parts = path.replace("\\", "/").rstrip("/").split("/")
    return len(parts) >= 2 and parts[-2:] == ["artifacts", PLAN_FILE_NAME]


def open_plan_items(markdown: str) -> int:
    """Count unchecked task-list items (``- [ ] ...``)."""
    return len(_OPEN_ITEM.findall(markdown or ""))


def open_plan_file_count(path: str | None) -> int:
    """Count unchecked items in the plan file; 0 when it is missing."""
    if not path:
        return 0
    try:
        return open_plan_items(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return 0
