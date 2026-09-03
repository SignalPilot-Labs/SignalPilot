"""Tool-boundary and run-end capture hooks, and the stream relay wiring."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.api.endpoints.chat_files.capture import (
    CapturedFile,
    ScratchFileCapture,
)
from signalpilot._server.api.endpoints.chat_files.hooks import (
    build_after_tool_result_hook,
    capture_after_tool_result,
    capture_at_run_end,
    tool_is_read_only,
)
from signalpilot._server.api.endpoints.chat_files.uploader import (
    UploadOutcome,
)
from signalpilot._server.api.endpoints.standalone_chat_stream import (
    AgentRunState,
    forward_agent_events,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class FakeUploader:
    fail_paths: set[str] = field(default_factory=set)
    unchanged_paths: set[str] = field(default_factory=set)
    calls: list[tuple[list[str], str, str | None]] = field(
        default_factory=list
    )

    async def upload_many(
        self,
        files: list[CapturedFile],
        *,
        reason: str,
        tool_call_id: str | None,
    ) -> list[UploadOutcome]:
        self.calls.append(([f.path for f in files], reason, tool_call_id))
        return [
            UploadOutcome(
                path=f.path,
                ok=f.path not in self.fail_paths,
                status_code=200 if f.path in self.unchanged_paths else 201,
                unchanged=f.path in self.unchanged_paths,
                deleted=f.deleted,
            )
            for f in files
        ]


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def _capture(tmp_path: Path) -> ScratchFileCapture:
    capture = ScratchFileCapture(scratch=tmp_path, run_id="run-1")
    await capture.baseline()
    return capture


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("Read", True),
        ("Glob", True),
        ("Grep", True),
        ("Skill", True),
        ("TodoWrite", True),
        ("ToolSearch", True),
        ("WebFetch", True),
        ("WebSearch", True),
        ("mcp__signalpilot__query_database", True),
        ("mcp__signalpilot__list_tables", True),
        ("mcp__signalpilot__explore_columns", True),
        ("mcp__signalpilot__explore_table", True),
        ("mcp__signalpilot__explore_value", True),
        ("mcp__signalpilot__get_schema", True),
        ("mcp__signalpilot__search_knowledge", True),
        ("mcp__signalpilot__explain_query", True),
        ("mcp__signalpilot__validate_sql", True),
        ("mcp__standalone-chat__inspect_dbt", True),
        ("mcp__signalpilot__plan_query", True),
        ("mcp__signalpilot-notebook__get_notebook_errors", True),
        ("Bash", False),
        ("Write", False),
        ("Edit", False),
        ("Agent", False),
        ("mcp__signalpilot-notebook__run_cells", False),
        ("mcp__signalpilot-notebook__edit_notebook", False),
        ("mcp__signalpilot__sandbox_exec", False),
        ("mcp__signalpilot__sandbox_write_file", False),
        ("mcp__standalone-chat__start_analysis_notebook", False),
        ("mcp__acme-connector__frobnicate", False),
        ("", False),
        ("SomeUnknownTool", False),
    ],
)
def test_read_only_denylist(tool: str, expected: bool) -> None:
    assert tool_is_read_only(tool) is expected


@pytest.mark.asyncio
async def test_read_only_tools_skip_the_sweep(tmp_path: Path) -> None:
    capture = await _capture(tmp_path)
    uploader = FakeUploader()
    _write(tmp_path / "artifacts" / "x.png", b"png")
    event = AgentEvent(type="tool_result", tool_call_id="toolu_1")

    lines = [
        line
        async for line in capture_after_tool_result(
            event, "Read", capture=capture, uploader=uploader
        )
    ]
    assert lines == []
    assert uploader.calls == []
    # The file is still pending for the next write tool.
    assert "artifacts/x.png" not in capture.snapshot


@pytest.mark.asyncio
async def test_write_tools_sweep_and_emit_progress_lines(
    tmp_path: Path,
) -> None:
    capture = await _capture(tmp_path)
    uploader = FakeUploader(unchanged_paths={"artifacts/same.csv"})
    _write(tmp_path / "artifacts" / "x.png", b"png")
    _write(tmp_path / "artifacts" / "same.csv", b"a\n")
    event = AgentEvent(type="tool_result", tool_call_id="toolu_9")
    hook = build_after_tool_result_hook(capture=capture, uploader=uploader)

    lines = [
        json.loads(line)
        async for line in hook(event, "mcp__signalpilot-notebook__run_cells")
    ]

    assert lines == [
        {
            "type": "progress",
            "content": "Saved artifacts/x.png",
            "is_error": False,
        }
    ]
    assert uploader.calls == [
        (["artifacts/same.csv", "artifacts/x.png"], "tool", "toolu_9")
    ] or uploader.calls == [
        (["artifacts/x.png", "artifacts/same.csv"], "tool", "toolu_9")
    ]


@pytest.mark.asyncio
async def test_failed_uploads_are_retried_at_run_end(tmp_path: Path) -> None:
    capture = await _capture(tmp_path)
    uploader = FakeUploader(fail_paths={"artifacts/x.png"})
    _write(tmp_path / "artifacts" / "x.png", b"png")
    event = AgentEvent(type="tool_result", tool_call_id="toolu_1")

    first = [
        line
        async for line in capture_after_tool_result(
            event, "Bash", capture=capture, uploader=uploader
        )
    ]
    assert first == []
    assert "artifacts/x.png" not in capture.snapshot

    uploader.fail_paths.clear()
    lines = await capture_at_run_end(capture=capture, uploader=uploader)
    assert [json.loads(line) for line in lines] == [
        {
            "type": "progress",
            "content": "Saved artifacts/x.png",
            "is_error": False,
        }
    ]
    assert uploader.calls[-1] == (["artifacts/x.png"], "run_end", None)


@pytest.mark.asyncio
async def test_run_end_reports_deletions_and_never_raises(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "artifacts" / "old.csv", b"a\n")
    capture = await _capture(tmp_path)
    uploader = FakeUploader()
    (tmp_path / "artifacts" / "old.csv").unlink()

    lines = await capture_at_run_end(capture=capture, uploader=uploader)
    assert [json.loads(line)["content"] for line in lines] == [
        "Removed artifacts/old.csv"
    ]

    class ExplodingUploader:
        async def upload_many(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("boom")

    _write(tmp_path / "artifacts" / "new.csv", b"b\n")
    assert (
        await capture_at_run_end(
            capture=capture,
            uploader=ExplodingUploader(),  # type: ignore[arg-type]
        )
        == []
    )
    event = AgentEvent(type="tool_result", tool_call_id="t")
    _write(tmp_path / "artifacts" / "new.csv", b"bb\n")
    assert [
        line
        async for line in capture_after_tool_result(
            event,
            "Bash",
            capture=capture,
            uploader=ExplodingUploader(),  # type: ignore[arg-type]
        )
    ] == []


@pytest.mark.asyncio
async def test_stream_relay_yields_hook_lines_after_tool_result(
    tmp_path: Path,
) -> None:
    capture = await _capture(tmp_path)
    uploader = FakeUploader()

    async def events() -> Any:
        yield AgentEvent(
            type="tool_use", tool_name="Read", tool_call_id="read-1"
        )
        yield AgentEvent(type="tool_result", tool_call_id="read-1")
        yield AgentEvent(
            type="tool_use",
            tool_name="mcp__signalpilot-notebook__run_cells",
            tool_call_id="run-1",
        )
        _write(tmp_path / "artifacts" / "chart.png", b"\x89PNG")
        yield AgentEvent(type="tool_result", tool_call_id="run-1")
        yield AgentEvent(type="text", content="Done")

    lines = [
        json.loads(chunk)
        async for chunk in forward_agent_events(
            events(),
            state=AgentRunState(),
            agent_model="m",
            auth_config_override=None,
            resume_agent_session=False,
            max_turns=5,
            analysis_session=lambda: None,
            after_tool_result=build_after_tool_result_hook(
                capture=capture, uploader=uploader
            ),
        )
    ]

    assert [(line["type"], line.get("content")) for line in lines] == [
        ("tool_use", ""),
        ("tool_result", ""),
        ("tool_use", ""),
        ("tool_result", ""),
        ("progress", "Saved artifacts/chart.png"),
    ]
    assert uploader.calls == [(["artifacts/chart.png"], "tool", "run-1")]
    digest = hashlib.sha256(b"\x89PNG").hexdigest()
    assert capture.snapshot["artifacts/chart.png"].size == 4
    assert digest


@pytest.mark.asyncio
async def test_stream_relay_survives_a_raising_hook() -> None:
    async def events() -> Any:
        yield AgentEvent(type="tool_use", tool_name="Bash", tool_call_id="b")
        yield AgentEvent(type="tool_result", tool_call_id="b")

    async def bad_hook(_event: Any, _tool: str) -> Any:
        raise RuntimeError("hook exploded")
        yield b""  # pragma: no cover

    lines = [
        json.loads(chunk)
        async for chunk in forward_agent_events(
            events(),
            state=AgentRunState(),
            agent_model="m",
            auth_config_override=None,
            resume_agent_session=False,
            max_turns=5,
            analysis_session=lambda: None,
            after_tool_result=bad_hook,
        )
    ]
    assert [line["type"] for line in lines] == ["tool_use", "tool_result"]
