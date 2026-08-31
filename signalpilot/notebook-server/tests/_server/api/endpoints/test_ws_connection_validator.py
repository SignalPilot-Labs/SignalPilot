from signalpilot._server.api.endpoints.ws.analysis_trails import (
    is_generated_analysis_trail_notebook,
)


def test_project_backed_slack_analysis_trail_is_lazy() -> None:
    assert is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/slack/slack-ba96530d8fb3514d-hi",
        file_key="notebooks/slack/hi-can-you-figure-out-if-our-fin-db.py",
    )


def test_project_backed_notion_analysis_trail_is_lazy() -> None:
    assert is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/notion/notion-ba96530d8fb3514d-hi",
        file_key="notebooks/notion/hi-can-you-figure-out-if-our-fin-db.py",
    )


def test_regular_project_notebook_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="main",
        file_key="notebooks/slack/handwritten-notebook.py",
    )


def test_non_analysis_notebook_under_analysis_branch_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/slack/slack-ba96530d8fb3514d-hi",
        file_key="notebooks/intro.py",
    )


def test_mismatched_analysis_source_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/notion/notion-ba96530d8fb3514d-hi",
        file_key="notebooks/slack/hi-can-you-figure-out-if-our-fin-db.py",
    )


def test_non_project_notebook_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id=None,
        branch="analysis/slack/slack-ba96530d8fb3514d-hi",
        file_key="notebooks/slack/hi-can-you-figure-out-if-our-fin-db.py",
    )


import pytest
from unittest.mock import AsyncMock, MagicMock


def _validator_for(
    *,
    query: dict[str, str | None],
    existing_session: object | None,
):
    # Imported lazily and after the endpoints package: under the conftest
    # signalpilot stub, importing the validator module graph directly trips
    # an import cycle through signalpilot._data; importing the ui plugin
    # package first resolves it.
    import signalpilot._plugins.ui  # noqa: F401
    from signalpilot._server.api.endpoints.ws.ws_connection_validator import (
        WebSocketConnectionValidator,
    )

    app_state = MagicMock()
    app_state.query_params = lambda key: query.get(key)
    app_state.session_manager.get_session.return_value = existing_session
    app_state.session_manager.workspace.directory = "/workspace"
    app_state.config_manager_at_file.return_value.get_config.return_value = {
        "experimental": {},
        "runtime": {"auto_instantiate": True},
    }
    validator = WebSocketConnectionValidator.__new__(WebSocketConnectionValidator)
    validator.app_state = app_state
    validator.websocket = MagicMock()
    validator.websocket.close = AsyncMock()
    return validator


@pytest.mark.asyncio
async def test_reconnect_by_session_id_skips_workspace_file_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chat live-notebook panel attaches by kernel session id; the session's
    analysis notebook lives OUTSIDE the workspace (run-scoped scratch dir) and
    must not be rejected by path validation on reconnect."""
    monkeypatch.delenv("SP_PROJECT_ID", raising=False)
    scratch_file = "/tmp/signalpilot-chat-runs/run-1/analysis.py"
    existing = MagicMock()
    existing.app_file_manager.path = scratch_file
    validator = _validator_for(
        query={"session_id": "s_abc123", "file": scratch_file},
        existing_session=existing,
    )

    params = await validator.extract_connection_params()

    assert params is not None
    assert params.session_id == "s_abc123"
    assert params.file_key == scratch_file
    validator.websocket.close.assert_not_called()


@pytest.mark.asyncio
async def test_new_session_still_validates_file_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an existing session the outside-workspace path is refused —
    the reconnect carve-out must not weaken new-session validation."""
    monkeypatch.delenv("SP_PROJECT_ID", raising=False)
    validator = _validator_for(
        query={
            "session_id": "s_zzz999",
            "file": "/tmp/signalpilot-chat-runs/run-1/analysis.py",
        },
        existing_session=None,
    )

    params = await validator.extract_connection_params()

    assert params is None
    validator.websocket.close.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_by_session_id_needs_no_file_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live notebook panel connects with ONLY the kernel session id — no
    file query param. The existing session supplies its own file."""
    monkeypatch.delenv("SP_PROJECT_ID", raising=False)
    scratch_file = "/tmp/signalpilot-chat-runs/run-1/analysis.py"
    existing = MagicMock()
    existing.app_file_manager.path = scratch_file
    validator = _validator_for(
        query={"session_id": "s_abc123"},
        existing_session=existing,
    )
    # No file param and no unique workspace file either.
    validator.app_state.session_manager.workspace.get_unique_file_key.return_value = None

    params = await validator.extract_connection_params()

    assert params is not None
    assert params.file_key == scratch_file
    validator.websocket.close.assert_not_called()
