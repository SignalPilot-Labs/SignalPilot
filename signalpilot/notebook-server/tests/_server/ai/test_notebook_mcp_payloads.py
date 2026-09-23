"""Agent-facing payload contracts for the notebook MCP tools.

Covers the edit_notebook rejection payload (committed cells only plus the
uncreated candidates), the MultipleDefinition and private-name hints, the
plain-text run_cells error payload, and the session-free
get_active_notebooks discovery.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from signalpilot._ast.cell import CellConfig
from signalpilot._messaging.tracebacks import plain_traceback_text
from signalpilot._server.ai.notebook_mcp import (
    REJECTED_NEW_CELLS_HINT,
    NotebookToolError,
    _handle_edit_notebook,
    _handle_run_cells,
    _validate_candidate_graph,
    build_notebook_mcp_server,
)
from signalpilot._types.ids import CellId_t


class _Document:
    def __init__(self) -> None:
        self.transactions: list[Any] = []

    def apply(self, transaction: Any) -> Any:
        self.transactions.append(transaction)
        return type(transaction)(
            changes=transaction.changes, source=transaction.source, version=1
        )


class _Context:
    def __init__(self, session: Any) -> None:
        self._session = session
        self.session_manager = SimpleNamespace(
            auth_token="auth-token", skew_protection_token="server-token"
        )
        self._app = SimpleNamespace(
            state=SimpleNamespace(host="127.0.0.1", port=2718, base_url="")
        )

    def get_session(self, _session_id: str) -> Any:
        return self._session

    def get_app(self) -> Any:
        return self._app


def _session(cells: list[tuple[str, str]], *, chat_runtime: bool = False) -> Any:
    cell_data = [
        SimpleNamespace(
            cell_id=CellId_t(cell_id), code=code, name="_", config=CellConfig()
        )
        for cell_id, code in cells
    ]
    manager = SimpleNamespace(cell_data=lambda: list(cell_data))
    file_manager = SimpleNamespace(
        app=SimpleNamespace(cell_manager=manager), path=None
    )
    return SimpleNamespace(
        app_file_manager=file_manager,
        document=_Document(),
        notify=lambda *_args, **_kwargs: None,
        session_view=SimpleNamespace(cell_notifications={}),
        _signalpilot_chat_runtime=chat_runtime,
    )


def _payload(error: NotebookToolError) -> dict[str, Any]:
    return json.loads(str(error))


# --- E1: rejection payload -------------------------------------------------


def test_rejected_add_cell_is_not_listed_among_committed_cells() -> None:
    session = _session([("a", "df = 1")])

    with pytest.raises(NotebookToolError) as raised:
        _handle_edit_notebook(
            _Context(session),
            {
                "session_id": "s",
                "edits": [{"type": "add_cell", "code": "df = 2"}],
            },
        )

    payload = _payload(raised.value)
    assert session.document.transactions == []
    assert payload["status"] == "rejected"
    assert payload["error"]["type"] == "MultipleDefinitionError"
    assert payload["error"]["cell_ids"] == ["a"]
    assert len(payload["rejected_new_cells"]) == 1
    new_id = payload["rejected_new_cells"][0]
    assert new_id != "a"
    assert len(new_id) == 8
    assert payload["hint"] == REJECTED_NEW_CELLS_HINT
    assert payload["error"]["hint"] == (
        "cell a already defines `df`. Either include update_cell for a in "
        "this batch, or use a different name in the new cell."
    )
    assert session._signalpilot_notebook_failures[-1] == payload


def test_two_new_cells_defining_one_name_name_the_batch() -> None:
    session = _session([("a", "answer = 1")])

    with pytest.raises(NotebookToolError) as raised:
        _handle_edit_notebook(
            _Context(session),
            {
                "session_id": "s",
                "edits": [
                    {"type": "add_cell", "code": "x = 1"},
                    {"type": "add_cell", "code": "x = 2"},
                ],
            },
        )

    payload = _payload(raised.value)
    assert payload["error"]["cell_ids"] == []
    assert len(payload["rejected_new_cells"]) == 2
    first, second = payload["rejected_new_cells"]
    assert payload["error"]["hint"] == (
        f"cells {first}, {second} in this batch all define `x`. "
        "Use a different name in all but one of them."
    )


def test_accepted_batch_has_no_rejection_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("a", "answer = 1")])
    import requests

    monkeypatch.setattr(
        requests, "post", lambda *_a, **_k: SimpleNamespace(status_code=200)
    )
    result = json.loads(
        _handle_edit_notebook(
            _Context(session),
            {"session_id": "s", "edits": [{"type": "add_cell", "code": "b = 2"}]},
        )[0].text
    )
    assert result["status"] == "completed"
    assert "rejected_new_cells" not in result
    assert "hint" not in result


def test_cell_not_found_still_lists_available_cells() -> None:
    session = _session([("a", "answer = 1")])
    with pytest.raises(NotebookToolError) as raised:
        _handle_edit_notebook(
            _Context(session),
            {
                "session_id": "s",
                "edits": [{"type": "update_cell", "cell_id": "zz", "code": "1"}],
            },
        )
    error = _payload(raised.value)["error"]
    assert error["type"] == "CellNotFound"
    assert error["message"] == "Available cells: ['a']"


# --- E2: hints from the graph ----------------------------------------------


def test_update_hint_names_the_updated_cell() -> None:
    with pytest.raises(NotebookToolError) as raised:
        _validate_candidate_graph(
            [(CellId_t("setup"), "import pandas as pd"), (CellId_t("b"), "import pandas as pd")],
            batch_cell_ids={"b"},
        )
    assert _payload(raised.value)["error"]["hint"] == (
        "cell setup already defines `pd`. Either include update_cell for "
        "setup in this batch, or use a different name in cell b."
    )


def test_private_reference_hint_names_the_defining_cell() -> None:
    with pytest.raises(NotebookToolError) as raised:
        _validate_candidate_graph(
            [(CellId_t("a"), "_p = 1"), (CellId_t("b"), "q = _p + 1")]
        )
    error = _payload(raised.value)["error"]
    assert error["type"] == "PrivateVariableCrossCellReference"
    assert error["message"].startswith("_p is private to cell(s) ['a']")
    assert error["hint"] == (
        "Give the value a name without a leading underscore in cell a."
    )


# --- E4: run_cells plain-text errors -----------------------------------------

_HTML_TRACEBACK = (
    '<span class="codehilite"><div class="highlight"><pre><span></span>'
    '<span class="gt">Traceback (most recent call last):</span>\n'
    '<span class="w">  </span>File <span class="nb">&quot;/tmp/nb.py&quot;</span>, '
    'line <span class="m">1</span>, in <span class="n">&lt;module&gt;</span>\n'
    '<span class="w">    </span>a()\n'
    '  File "/tmp/nb.py", line 2, in a\n    b()\n'
    '  File "/tmp/nb.py", line 3, in b\n    c()\n'
    '  File "/tmp/nb.py", line 4, in c\n'
    '    raise ValueError("bad &amp; worse")\n'
    '<span class="gr">ValueError</span>: <span class="n">bad &amp; worse</span>\n'
    "</pre></div></span>"
)


def test_plain_traceback_text_keeps_last_three_frames_without_html() -> None:
    text = plain_traceback_text(_HTML_TRACEBACK)
    assert "<" not in text
    assert "&amp;" not in text
    assert text.splitlines() == [
        "Traceback (most recent call last):",
        "  ... 1 earlier frame(s) omitted",
        '  File "/tmp/nb.py", line 2, in a',
        "    b()",
        '  File "/tmp/nb.py", line 3, in b',
        "    c()",
        '  File "/tmp/nb.py", line 4, in c',
        '    raise ValueError("bad & worse")',
        "ValueError: bad & worse",
    ]


def test_plain_traceback_text_clips_from_the_front() -> None:
    text = plain_traceback_text("x" * 700 + "\nValueError: end", max_chars=100)
    assert len(text) == 100
    assert text.startswith("...")
    assert text.endswith("ValueError: end")


@dataclass
class _Raised:
    msg: str = "division by zero"
    exception_type: str = "ZeroDivisionError"
    raising_cell: Any = None
    traceback: str | None = _HTML_TRACEBACK

    def describe(self) -> str:
        return self.msg


@dataclass
class _AncestorRaised:
    msg: str = "An ancestor raised an exception (ZeroDivisionError): "
    exception_type: str = "Ancestor raised"
    raising_cell: Any = field(default_factory=lambda: CellId_t("parent"))
    traceback: str | None = None

    def describe(self) -> str:
        return self.msg


def _run_two_cells(
    monkeypatch: pytest.MonkeyPatch, *, chat_runtime: bool
) -> dict[str, Any]:
    session = _session(
        [("parent", "x = 1 / 0"), ("child", "y = x + 1")],
        chat_runtime=chat_runtime,
    )
    for cell in ("parent", "child"):
        session.session_view.cell_notifications[CellId_t(cell)] = (
            SimpleNamespace(timestamp=1.0, status="idle", output=None, console=[])
        )
    console_item = SimpleNamespace(
        channel="stderr",
        mimetype="application/vnd.sp+traceback",
        data=_HTML_TRACEBACK,
    )

    def post(url: str, **_kwargs: Any) -> Any:
        if url.endswith("/run"):
            notifications = session.session_view.cell_notifications
            notifications[CellId_t("parent")] = SimpleNamespace(
                timestamp=2.0,
                status="idle",
                output=SimpleNamespace(
                    channel=SimpleNamespace(value="sp-error"),
                    mimetype="application/vnd.sp+error",
                    data=[_Raised()],
                ),
                console=[console_item],
            )
            notifications[CellId_t("child")] = SimpleNamespace(
                timestamp=2.0,
                status="idle",
                output=SimpleNamespace(
                    channel=SimpleNamespace(value="sp-error"),
                    mimetype="application/vnd.sp+error",
                    data=[_AncestorRaised()],
                ),
                console=[],
            )
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    with pytest.raises(NotebookToolError) as raised:
        _handle_run_cells(
            _Context(session),
            {"session_id": "s", "cell_ids": ["parent", "child"]},
        )
    return _payload(raised.value)


def test_run_cells_chat_runtime_reports_plain_text_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _run_two_cells(monkeypatch, chat_runtime=True)

    assert payload["status"] == "failed"
    assert payload["failed_cell_ids"] == ["parent"]
    assert payload["skipped_cell_ids"] == ["child"]
    parent, child = payload["cells"]
    assert child == {
        "cell_id": "child",
        "status": "skipped",
        "skipped_because": "ancestor parent failed",
    }
    assert parent["status"] == "failed"
    assert "console" not in parent  # the HTML traceback never reaches chat
    (error,) = parent["errors"]
    assert list(error) == [
        "type",
        "exception_type",
        "message",
        "cell_ids",
        "traceback_text",
    ]
    assert error["exception_type"] == "ZeroDivisionError"
    assert error["message"] == "division by zero"
    assert "<" not in error["traceback_text"]
    assert error["traceback_text"].endswith("ValueError: bad & worse")
    assert len(error["traceback_text"]) <= 600
    assert payload["error"]["type"] == "_Raised"
    assert payload["error"]["cell_ids"] == ["parent"]


def test_run_cells_ui_path_keeps_highlighted_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _run_two_cells(monkeypatch, chat_runtime=False)
    parent = payload["cells"][0]
    assert parent["console"][0]["text"].startswith('<span class="codehilite">')
    assert "<" not in parent["errors"][0]["traceback_text"]
    assert payload["cells"][1]["status"] == "skipped"


def test_run_cells_only_skipped_cells_still_fail_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("child", "y = x + 1")], chat_runtime=True)
    session.session_view.cell_notifications[CellId_t("child")] = (
        SimpleNamespace(timestamp=1.0, status="idle", output=None, console=[])
    )

    def post(url: str, **_kwargs: Any) -> Any:
        if url.endswith("/run"):
            session.session_view.cell_notifications[CellId_t("child")] = (
                SimpleNamespace(
                    timestamp=2.0,
                    status="idle",
                    output=SimpleNamespace(
                        channel=SimpleNamespace(value="sp-error"),
                        mimetype="application/vnd.sp+error",
                        data=[_AncestorRaised()],
                    ),
                    console=[],
                )
            )
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    with pytest.raises(NotebookToolError) as raised:
        _handle_run_cells(_Context(session), {"session_id": "s"})
    payload = _payload(raised.value)
    assert payload["failed_cell_ids"] == []
    assert payload["skipped_cell_ids"] == ["child"]
    assert payload["error"] == {
        "type": "AncestorFailed",
        "variable": None,
        "cell_ids": ["child"],
        "message": "ancestor parent failed",
    }


# --- A: get_active_notebooks is session-free and filtered --------------------


@dataclass
class _Info:
    name: str
    path: str
    session_id: str


@dataclass
class _Summary:
    total_notebooks: int
    active_connections: int


@dataclass
class _Data:
    summary: _Summary
    notebooks: list[_Info]


@dataclass
class _Output:
    status: str
    data: _Data


@dataclass
class _EmptyArgs:
    pass


class _FakeActiveNotebooks:
    name = "get_active_notebooks"
    description = "List notebooks"
    Args = _EmptyArgs

    def __init__(self, context: Any) -> None:
        self.context = context

    async def __call__(self, _arguments: dict[str, Any]) -> _Output:
        infos = [
            _Info("analysis.py", "/tmp/analysis.py", "s-run"),
            _Info("other.py", "/tmp/other.py", "s-other"),
        ]
        return _Output(
            status="success", data=_Data(_Summary(len(infos), 2), infos)
        )


async def _call_active(server: Any) -> Any:
    return await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="get_active_notebooks", arguments={}
            )
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorizer", "expected"),
    [
        (lambda sid: sid == "s-run", ["s-run"]),
        (lambda _sid: False, []),
        (None, ["s-run", "s-other"]),
    ],
)
async def test_get_active_notebooks_skips_the_session_check_and_filters(
    monkeypatch: pytest.MonkeyPatch,
    authorizer: Any,
    expected: list[str],
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.ai.tools.registry",
        SimpleNamespace(SUPPORTED_BACKEND_AND_MCP_TOOLS=[_FakeActiveNotebooks]),
    )
    server = build_notebook_mcp_server(
        _Context(_session([])), session_authorizer=authorizer
    )["instance"]

    response = await _call_active(server)

    assert response.root.isError is False
    body = json.loads(response.root.content[0].text)
    assert [n["session_id"] for n in body["data"]["notebooks"]] == expected
    assert body["data"]["summary"]["total_notebooks"] == len(expected)


@pytest.mark.asyncio
async def test_other_tools_still_require_an_authorized_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.ai.tools.registry",
        SimpleNamespace(SUPPORTED_BACKEND_AND_MCP_TOOLS=[]),
    )
    server = build_notebook_mcp_server(
        _Context(_session([])), session_authorizer=lambda _sid: False
    )["instance"]
    response = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="run_cells", arguments={"session_id": "s-other"}
            )
        )
    )
    assert response.root.isError is True
    assert "NOTEBOOK_SESSION_SCOPE_MISMATCH" in response.root.content[0].text
