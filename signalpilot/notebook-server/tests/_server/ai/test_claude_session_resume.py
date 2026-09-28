"""Resume is claimed only for a session that was really stored.

`claude --resume <id>` exits 1 with "No conversation found with session ID"
when the session is not on disk, which fails the whole follow-up message. So
`persist_claude_session` returning False must stop the next message from
passing --resume.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self

import pytest

from signalpilot._server.ai import claude_session_archive as archive

if TYPE_CHECKING:
    from pathlib import Path


def _state(tmp_path: Path, *, upload_url: str | None, write_session: bool) -> archive.ClaudeSessionState:
    cwd = tmp_path / "checkout" / "dumpsters_dbt_simplified"
    cwd.mkdir(parents=True)
    config_dir = tmp_path / "cfg"
    session_id = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
    if write_session:
        project = config_dir / "projects" / archive._project_storage_name(cwd)
        project.mkdir(parents=True)
        (project / f"{session_id}.jsonl").write_text("{}\n", encoding="utf-8")
    return archive.ClaudeSessionState(
        session_id=session_id,
        config_dir=config_dir,
        cwd=cwd,
        resume=False,
        storage="s3",
        upload_url=upload_url,
    )


def test_session_path_matches_the_cli_layout(tmp_path: Path) -> None:
    """The CLI keys sessions on the working directory:
    ``~/.claude/projects/<cwd with every non-alphanumeric replaced by ->``.

    Checked against claude 2.1.280 in the notebook image: with cwd
    /tmp/co/dumpsters_dbt_simplified it writes
    projects/-tmp-co-dumpsters-dbt-simplified/. The assertion derives the
    expected name from the resolved path so it holds on any platform (a POSIX
    path resolves to a drive-qualified one on Windows).
    """
    cwd = tmp_path / "co" / "dumpsters_dbt_simplified"
    cwd.mkdir(parents=True)
    expected = re.sub(r"[^a-zA-Z0-9]", "-", str(cwd.resolve()))
    assert archive._project_storage_name(cwd) == expected
    assert "dumpsters-dbt-simplified" in expected
    assert "_" not in expected
    assert "/" not in expected


@pytest.mark.asyncio
async def test_no_upload_url_cannot_be_resumed(tmp_path: Path) -> None:
    assert await archive.persist_claude_session(_state(tmp_path, upload_url=None, write_session=True)) is False


@pytest.mark.asyncio
async def test_missing_session_file_cannot_be_resumed(tmp_path: Path) -> None:
    """A cwd that moved between turns looks exactly like this."""
    state = _state(tmp_path, upload_url="https://example.invalid/put", write_session=False)
    assert await archive.persist_claude_session(state) is False


@pytest.mark.asyncio
async def test_a_stored_session_reports_true(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, upload_url="https://example.invalid/put", write_session=True)
    sent: dict[str, object] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

    class _Client:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def put(self, url: str, content: bytes, **_kw: object) -> _Resp:
            sent["url"] = url
            sent["bytes"] = len(content)
            return _Resp()

    monkeypatch.setattr(archive.httpx, "AsyncClient", lambda **_k: _Client())
    assert await archive.persist_claude_session(state) is True
    assert sent["url"] == "https://example.invalid/put"
    assert sent["bytes"] > 0


# --- the cwd used for bookkeeping must be the cwd the agent runs in -----------
#
# The regression: execution passed the checkout ROOT to prepare_claude_session
# while the agent ran in the configured dbt project SUBDIRECTORY. The session
# was written under one slug and looked for under another, so nothing was
# archived and the next message asked the CLI to resume a session it could not
# find. The two must come from one resolve_agent_cwd call.


def test_session_cwd_is_the_agent_cwd_not_the_checkout_root(tmp_path, monkeypatch) -> None:
    from signalpilot._dbt import materialize
    from signalpilot._server.ai import claude_agent_options as opts

    checkout = tmp_path / "checkout"
    for name in ("dumpsters_dbt", "dumpsters_dbt_simplified"):
        (checkout / name).mkdir(parents=True)
        (checkout / name / "dbt_project.yml").write_text("name: x\n", encoding="utf-8")
    monkeypatch.setattr(materialize, "resolve_dbt_project_dir", lambda **_k: "dumpsters_dbt_simplified")

    agent_cwd, _ = opts.resolve_agent_cwd(str(checkout))
    assert agent_cwd == str((checkout / "dumpsters_dbt_simplified").resolve())

    # The slug the CLI will use, and the slug the archive checks, must match.
    from pathlib import Path as _Path

    assert archive._project_storage_name(_Path(agent_cwd)) != archive._project_storage_name(checkout)
    assert archive._project_storage_name(_Path(agent_cwd)) == re.sub(
        r"[^a-zA-Z0-9]", "-", str((checkout / "dumpsters_dbt_simplified").resolve())
    )


def test_execution_resolves_the_agent_cwd_before_restoring_the_session() -> None:
    """Guards the call order in standalone_chat_execution: resolve_agent_cwd
    must be used for the cwd handed to restore_agent_session."""
    import inspect

    from signalpilot._server.api.endpoints import (
        standalone_chat_execution as ex,
    )

    src = inspect.getsource(ex)
    resolve_at = src.index("resolve_agent_cwd(str(project_directory))")
    restore_at = src.index("restore_agent_session(")
    assert resolve_at < restore_at
    assert "cwd=Path(agent_cwd)" in src
    assert "cwd=project_directory," not in src


# --- a session is found wherever the CLI stored it -----------------------------
#
# `claude --resume <id>` finds a session regardless of the directory it runs
# from (verified against 2.1.280: created in proj_a, resumed from proj_b, exit
# 0). Keying our own check on cwd made a moved working directory look like a
# missing session, and the caller then tried to create it again with
# `--session-id <id>`, which the CLI refuses with "Session ID ... is already in
# use" and exit 1. That is the failure every follow-up hit.


def _write_session(config_dir: Path, slug_for: Path, session_id: str) -> Path:
    project = config_dir / "projects" / archive._project_storage_name(slug_for)
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{session_id}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    return path


def test_session_stored_under_another_cwd_is_still_found(tmp_path) -> None:
    config_dir = tmp_path / "cfg"
    root = tmp_path / "checkout"
    subdir = root / "dumpsters_dbt_simplified"
    subdir.mkdir(parents=True)
    session_id = "cccccccc-1111-2222-3333-dddddddddddd"

    # Written when the agent ran at the checkout root, read now that it runs in
    # the dbt project subdirectory.
    _write_session(config_dir, root, session_id)
    assert archive._has_session(config_dir, session_id, subdir) is True
    assert archive._find_session_file(config_dir, session_id, subdir) is not None


def test_the_current_cwd_is_preferred_when_both_exist(tmp_path) -> None:
    config_dir = tmp_path / "cfg"
    root = tmp_path / "checkout"
    subdir = root / "proj"
    subdir.mkdir(parents=True)
    session_id = "eeeeeeee-1111-2222-3333-ffffffffffff"
    _write_session(config_dir, root, session_id)
    expected = _write_session(config_dir, subdir, session_id)
    assert archive._find_session_file(config_dir, session_id, subdir) == expected


def test_a_genuinely_absent_session_is_absent(tmp_path) -> None:
    config_dir = tmp_path / "cfg"
    cwd = tmp_path / "checkout"
    cwd.mkdir()
    _write_session(config_dir, cwd, "11111111-1111-1111-1111-111111111111")
    assert archive._has_session(config_dir, "22222222-2222-2222-2222-222222222222", cwd) is False


def test_missing_projects_directory_is_not_an_error(tmp_path) -> None:
    cwd = tmp_path / "checkout"
    cwd.mkdir()
    assert archive._has_session(tmp_path / "empty-cfg", "33333333-3333-3333-3333-333333333333", cwd) is False
