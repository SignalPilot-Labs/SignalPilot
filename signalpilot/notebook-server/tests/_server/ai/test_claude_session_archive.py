from __future__ import annotations

import io
import tarfile
from typing import TYPE_CHECKING, Self

import pytest

from signalpilot._server.ai import claude_session_archive as sessions

if TYPE_CHECKING:
    from pathlib import Path

CONVERSATION_ID = "11111111-2222-4333-8444-555555555555"


def _write_native_session(config_dir: Path, cwd: Path) -> None:
    project_dir = config_dir / "projects" / sessions._project_storage_name(cwd)
    project_dir.mkdir(parents=True)
    (project_dir / f"{CONVERSATION_ID}.jsonl").write_text(
        '{"type":"user","message":"7"}\n',
        encoding="utf-8",
    )
    (config_dir / ".claude.json").write_text(
        '{"firstStartTime":"now"}',
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_local_native_session_resumes_without_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SP_CHAT_CLAUDE_STATE_ROOT", str(tmp_path))
    config_dir = tmp_path / CONVERSATION_ID
    cwd = tmp_path / "stable-conversation-cwd"
    _write_native_session(config_dir, cwd)

    state = await sessions.prepare_claude_session(
        conversation_id=CONVERSATION_ID,
        cwd=cwd,
        transfer={
            "session_id": CONVERSATION_ID,
            "storage": "s3",
            "download_url": "https://storage.test/session.tgz",
        },
    )

    assert state.resume is True
    assert state.config_dir == config_dir


@pytest.mark.asyncio
async def test_session_from_different_cwd_falls_back_to_database_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SP_CHAT_CLAUDE_STATE_ROOT", str(tmp_path))
    config_dir = tmp_path / CONVERSATION_ID
    _write_native_session(config_dir, tmp_path / "old-run-directory")

    state = await sessions.prepare_claude_session(
        conversation_id=CONVERSATION_ID,
        cwd=tmp_path / "stable-conversation-directory",
        transfer=None,
    )

    assert state.resume is False


@pytest.mark.asyncio
async def test_archive_round_trip_restores_native_session_for_cold_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    cwd = tmp_path / "stable-conversation-cwd"
    _write_native_session(source, cwd)
    stored = sessions._create_archive(source)
    target_root = tmp_path / "restored"
    monkeypatch.setenv("SP_CHAT_CLAUDE_STATE_ROOT", str(target_root))

    class Response:
        status_code = 200
        content = stored

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _url: str) -> Response:
            return Response()

    monkeypatch.setattr(sessions.httpx, "AsyncClient", Client)
    state = await sessions.prepare_claude_session(
        conversation_id=CONVERSATION_ID,
        cwd=cwd,
        transfer={
            "session_id": CONVERSATION_ID,
            "storage": "s3",
            "download_url": "https://storage.test/session.tgz",
        },
    )

    assert state.resume is True
    assert (state.config_dir / ".claude.json").is_file()
    assert next((state.config_dir / "projects").glob("*/*.jsonl")).read_text(
        encoding="utf-8"
    ).endswith('"7"}\n')


def test_archive_rejects_path_traversal(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(ValueError, match="path traversal"):
        sessions._extract_archive(payload.getvalue(), tmp_path / "target")


@pytest.mark.asyncio
async def test_persist_uploads_complete_native_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / CONVERSATION_ID
    cwd = tmp_path / "stable-conversation-cwd"
    _write_native_session(config_dir, cwd)
    uploaded: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def put(self, url: str, **kwargs: object) -> Response:
            uploaded.update(url=url, **kwargs)
            return Response()

    monkeypatch.setattr(sessions.httpx, "AsyncClient", Client)
    state = sessions.ClaudeSessionState(
        session_id=CONVERSATION_ID,
        config_dir=config_dir,
        cwd=cwd,
        resume=True,
        storage="s3",
        upload_url="https://storage.test/session.tgz",
    )

    assert await sessions.persist_claude_session(state) is True
    assert uploaded["url"] == "https://storage.test/session.tgz"
    archive_bytes = bytes(uploaded["content"])
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        names = set(archive.getnames())
    assert ".claude.json" in names
    assert any(name.endswith(f"/{CONVERSATION_ID}.jsonl") for name in names)
