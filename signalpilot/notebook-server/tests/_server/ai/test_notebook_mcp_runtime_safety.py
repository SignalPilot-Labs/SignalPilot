from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from signalpilot._ast.cell import CellConfig
from signalpilot._server.ai.notebook_mcp import (
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
            changes=transaction.changes,
            source=transaction.source,
            version=1,
        )


class _Context:
    def __init__(self, session: Any) -> None:
        self._session = session
        self.session_manager = SimpleNamespace(
            auth_token="auth-token",
            skew_protection_token="server-token",
        )
        self._app = SimpleNamespace(
            state=SimpleNamespace(host="127.0.0.1", port=2718, base_url="")
        )

    def get_session(self, _session_id: str) -> Any:
        return self._session

    def get_app(self) -> Any:
        return self._app


def _session(cells: list[tuple[str, str]]) -> Any:
    cell_data = [
        SimpleNamespace(
            cell_id=CellId_t(cell_id),
            code=code,
            name="_",
            config=CellConfig(),
        )
        for cell_id, code in cells
    ]
    manager = SimpleNamespace(cell_data=lambda: list(cell_data))
    file_manager = SimpleNamespace(
        app=SimpleNamespace(cell_manager=manager),
        path=None,
    )
    return SimpleNamespace(
        app_file_manager=file_manager,
        document=_Document(),
        notify=lambda *_args, **_kwargs: None,
        session_view=SimpleNamespace(cell_notifications={}),
    )


def _payload(error: NotebookToolError) -> dict[str, Any]:
    return json.loads(str(error))


@pytest.mark.parametrize(
    ("cells", "error_type", "variable", "cell_ids"),
    [
        (
            [(CellId_t("a"), "df = 1"), (CellId_t("b"), "df = 2")],
            "MultipleDefinitionError",
            "df",
            ["a", "b"],
        ),
        (
            [(CellId_t("a"), "if True print('broken')")],
            "SyntaxError",
            None,
            ["a"],
        ),
        (
            [
                (CellId_t("a"), "left = right + 1"),
                (CellId_t("b"), "right = left + 1"),
            ],
            "CycleError",
            "left",
            ["a", "b"],
        ),
    ],
)
def test_candidate_graph_rejects_invalid_batches(
    cells: list[tuple[CellId_t, str]],
    error_type: str,
    variable: str | None,
    cell_ids: list[str],
) -> None:
    with pytest.raises(NotebookToolError) as raised:
        _validate_candidate_graph(cells)

    assert _payload(raised.value)["error"] == {
        "cell_ids": cell_ids,
        "message": _payload(raised.value)["error"]["message"],
        "type": error_type,
        "variable": variable,
    }


@pytest.mark.asyncio
async def test_duplicate_definition_is_an_mcp_error_before_document_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("a", "df = 1"), ("b", "answer = 2")])
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.ai.tools.registry",
        SimpleNamespace(SUPPORTED_BACKEND_AND_MCP_TOOLS=[]),
    )
    config = build_notebook_mcp_server(_Context(session))
    server = config["instance"]

    response = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="edit_notebook",
                arguments={
                    "session_id": "session-a",
                    "edits": [
                        {
                            "type": "update_cell",
                            "cell_id": "b",
                            "code": "df = 2",
                        }
                    ],
                },
            )
        )
    )

    assert response.root.isError is True
    assert session.document.transactions == []
    assert '"type": "MultipleDefinitionError"' in response.root.content[0].text
    assert session._signalpilot_notebook_failures[-1]["error"] == {
        "cell_ids": ["a", "b"],
        "message": session._signalpilot_notebook_failures[-1]["error"][
            "message"
        ],
        "type": "MultipleDefinitionError",
        "variable": "df",
    }


def test_delete_then_add_removes_the_old_kernel_definition_before_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("old", "df = 1"), ("consumer", "answer = df + 1")])
    calls: list[tuple[str, dict[str, Any]]] = []

    def post(url: str, **kwargs: Any) -> Any:
        calls.append((url, kwargs["json"]))
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    result = _handle_edit_notebook(
        _Context(session),
        {
            "session_id": "session-a",
            "edits": [
                {"type": "delete_cell", "cell_id": "old"},
                {"type": "add_cell", "code": "df = 3"},
            ],
        },
    )

    assert json.loads(result[0].text)["status"] == "completed"
    assert [(url.rsplit("/", 1)[-1], body) for url, body in calls] == [
        ("delete", {"cellId": "old"}),
        (
            "run",
            {
                "cellIds": [json.loads(result[0].text)["edits"][1]["cell_id"]],
                "codes": ["df = 3"],
            },
        ),
    ]


def test_kernel_sync_failure_marks_the_mutated_notebook_dirty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("old", "df = 1")])

    import requests

    monkeypatch.setattr(
        requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=500),
    )
    with pytest.raises(NotebookToolError) as raised:
        _handle_edit_notebook(
            _Context(session),
            {
                "session_id": "session-a",
                "edits": [{"type": "delete_cell", "cell_id": "old"}],
            },
        )

    assert session._signalpilot_notebook_dirty is True
    assert len(session.document.transactions) == 1
    assert _payload(raised.value)["error"] == {
        "cell_ids": ["old"],
        "message": "RuntimeError",
        "type": "DocumentKernelSynchronizationError",
        "variable": None,
    }


class SpExceptionRaisedError:
    exception_type = "ValueError"

    def describe(self) -> str:
        return "The cell raised an exception"


class MultipleDefinitionError:
    name = "df"
    cells = (CellId_t("other"),)

    def describe(self) -> str:
        return "The variable was defined by another cell"


class SpInterruptionError:
    def describe(self) -> str:
        return "The cell was interrupted"


@pytest.mark.asyncio
async def test_run_cells_failure_is_an_mcp_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("cell", "answer = 1")])
    session.session_view.cell_notifications[CellId_t("cell")] = (
        SimpleNamespace(
            timestamp=1.0,
            status="idle",
            output=None,
            console=[],
        )
    )

    def post(url: str, **_kwargs: Any) -> Any:
        if url.endswith("/run"):
            session.session_view.cell_notifications[CellId_t("cell")] = (
                SimpleNamespace(
                    timestamp=2.0,
                    status="idle",
                    output=SimpleNamespace(
                        channel=SimpleNamespace(value="sp-error"),
                        mimetype="application/vnd.sp+error",
                        data=[SpExceptionRaisedError()],
                    ),
                    console=[],
                )
            )
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.ai.tools.registry",
        SimpleNamespace(SUPPORTED_BACKEND_AND_MCP_TOOLS=[]),
    )
    server = build_notebook_mcp_server(_Context(session))["instance"]
    response = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="run_cells",
                arguments={"session_id": "session-a", "cell_ids": ["cell"]},
            )
        )
    )

    assert response.root.isError is True
    assert '"status": "failed"' in response.root.content[0].text


@pytest.mark.parametrize(
    "error",
    [
        SpExceptionRaisedError(),
        MultipleDefinitionError(),
        SpInterruptionError(),
    ],
)
def test_run_cells_rejects_python_graph_and_cancellation_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Any,
) -> None:
    session = _session([("cell", "answer = 1")])
    session.session_view.cell_notifications[CellId_t("cell")] = (
        SimpleNamespace(
            timestamp=1.0,
            status="idle",
            output=None,
            console=[],
        )
    )

    def post(url: str, **_kwargs: Any) -> Any:
        if url.endswith("/run"):
            session.session_view.cell_notifications[CellId_t("cell")] = (
                SimpleNamespace(
                    timestamp=2.0,
                    status="idle",
                    output=SimpleNamespace(
                        channel=SimpleNamespace(value="sp-error"),
                        mimetype="application/vnd.sp+error",
                        data=[error],
                    ),
                    console=[],
                )
            )
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    with pytest.raises(NotebookToolError) as raised:
        _handle_run_cells(
            _Context(session),
            {"session_id": "session-a", "cell_ids": ["cell"]},
        )

    payload = _payload(raised.value)
    assert payload["status"] == "failed"
    assert payload["has_errors"] is True
    assert payload["failed_cell_ids"] == ["cell"]
    assert payload["cells"][0]["errors"][0]["type"] == type(error).__name__


def test_run_cells_rejects_unknown_state_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("cell", "answer = 1")])
    session.session_view.cell_notifications[CellId_t("cell")] = (
        SimpleNamespace(
            timestamp=1.0,
            status="idle",
            output=None,
            console=[],
        )
    )

    def post(url: str, **_kwargs: Any) -> Any:
        if url.endswith("/run"):
            session.session_view.cell_notifications[CellId_t("cell")] = (
                SimpleNamespace(
                    timestamp=2.0,
                    status="disabled-transitively",
                    output=None,
                    console=[],
                )
            )
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    with pytest.raises(NotebookToolError) as unknown:
        _handle_run_cells(_Context(session), {"session_id": "session-a"})
    assert _payload(unknown.value)["cells"][0]["errors"] == [
        {
            "message": "Unexpected terminal state: disabled-transitively",
            "type": "UnknownStateError",
        }
    ]

    monkeypatch.setattr(
        requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200),
    )
    with pytest.raises(NotebookToolError) as timed_out:
        _handle_run_cells(
            _Context(session),
            {"session_id": "session-a", "timeout": 0},
        )
    assert _payload(timed_out.value)["cells"][0]["errors"] == [
        {
            "message": "Cell execution did not reach a terminal state",
            "type": "TimeoutError",
        }
    ]


def test_run_cells_returns_a_structured_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("cell", "answer = 1")])
    session.session_view.cell_notifications[CellId_t("cell")] = (
        SimpleNamespace(
            timestamp=1.0,
            status="idle",
            output=None,
            console=[],
        )
    )

    def post(url: str, **_kwargs: Any) -> Any:
        if url.endswith("/run"):
            session.session_view.cell_notifications[CellId_t("cell")] = (
                SimpleNamespace(
                    timestamp=2.0,
                    status="idle",
                    output=SimpleNamespace(
                        channel=SimpleNamespace(value="output"),
                        mimetype="text/plain",
                        data="1",
                    ),
                    console=[],
                )
            )
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    result = _handle_run_cells(
        _Context(session),
        {"session_id": "session-a", "cell_ids": ["cell"]},
    )
    payload = json.loads(result[0].text)
    payload.pop("elapsed_seconds")

    assert payload == {
        "cell_ids": ["cell"],
        "cells": [
            {
                "cell_id": "cell",
                "output": {"data": "1", "mimetype": "text/plain"},
                "runtime_state": "idle",
                "status": "completed",
            }
        ],
        "failed_cell_ids": [],
        "has_errors": False,
        "status": "completed",
        "timed_out": False,
    }


def test_run_cells_clears_a_stale_error_before_a_successful_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session([("cell", "answer = 1")])
    notification = SimpleNamespace(
        timestamp=1.0,
        status="idle",
        output=SimpleNamespace(
            channel=SimpleNamespace(value="sp-error"),
            mimetype="application/vnd.sp+error",
            data=[SpExceptionRaisedError()],
        ),
        console=[],
    )
    session.session_view.cell_notifications[CellId_t("cell")] = notification

    def post(url: str, **_kwargs: Any) -> Any:
        if url.endswith("/run"):
            # A successful no-output execution updates the cell lifecycle, but
            # the session-view merge used to retain its previous error output.
            notification.timestamp = 2.0
            notification.status = "idle"
        return SimpleNamespace(status_code=200)

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    result = _handle_run_cells(
        _Context(session),
        {"session_id": "session-a", "cell_ids": ["cell"]},
    )
    payload = json.loads(result[0].text)

    assert payload["status"] == "completed"
    assert payload["has_errors"] is False
    assert payload["failed_cell_ids"] == []
