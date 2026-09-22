"""The run plan kept as artifacts/plan.md: path matching, open-item counts,
and the completion guard that reads it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from signalpilot._server.ai import claude_agent_events as events
from signalpilot._server.ai.plan_file import (
    is_plan_file_path,
    open_plan_file_count,
    open_plan_items,
)

if TYPE_CHECKING:
    from pathlib import Path

PLAN = """# Plan: Q3 revenue by region
- [x] Load the dbt workflow
- [ ] Query revenue by region
* [ ] Chart the result
- [X] not a checkbox we count as open
"""


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/signalpilot-chat-runs/r1/artifacts/plan.md",
        r"C:\scratch\artifacts\plan.md",
        "artifacts/plan.md",
    ],
)
def test_plan_file_paths_match(path: str) -> None:
    assert is_plan_file_path(path)


@pytest.mark.parametrize(
    "path", ["/tmp/plan.md", "/tmp/artifacts/plan.txt", "/x/artifacts/sub/plan.md", None, 3]
)
def test_other_paths_do_not_match(path: object) -> None:
    assert not is_plan_file_path(path)


def test_open_items_count_unchecked_boxes_only() -> None:
    assert open_plan_items(PLAN) == 2
    assert open_plan_items("") == 0


def test_open_plan_file_count_reads_the_file(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    assert open_plan_file_count(str(plan)) == 2
    assert open_plan_file_count(str(tmp_path / "missing.md")) == 0
    assert open_plan_file_count(None) == 0


class _Client:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def query(self, prompt: str) -> None:
        self.queries.append(prompt)


@pytest.mark.asyncio
async def test_guard_continues_while_the_plan_file_has_open_steps(tmp_path: Path) -> None:
    plan = tmp_path / "artifacts" / "plan.md"
    plan.parent.mkdir()
    plan.write_text(PLAN, encoding="utf-8")
    state = events._SdkStreamState()
    state.plan_file_path = str(plan)
    client = _Client()
    msg = SimpleNamespace(is_error=False)
    assert await events._continue_open_plan(client, msg, state) is True
    assert client.queries == [events.PLAN_CONTINUATION_PROMPT]
    # Every step checked: the run may finish.
    plan.write_text(PLAN.replace("[ ]", "[x]"), encoding="utf-8")
    assert await events._continue_open_plan(client, msg, state) is False
