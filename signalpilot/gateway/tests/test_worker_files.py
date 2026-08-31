"""Worker-side live file mirror.

The mirror watches Write/Edit/MultiEdit tool calls, copies scratch files
into conversation object storage, and emits debounced files_changed
events. It must never raise into the worker hot loop.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayChatFile
from gateway.standalone_chat import worker, worker_files

ORG = "org-a"
USER = "user-a"
CONV = "conv-a"
ROOT = "/tmp/signalpilot-chat-runs"


class _FakeStorage:
    """In-memory stand-in for chat object storage."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.enabled = True

    async def put_bytes(self, *, key: str, data: bytes, content_type: str):
        self.objects[key] = data
        return SimpleNamespace(
            key=key,
            byte_size=len(data),
            content_hash=hashlib.sha256(data).hexdigest(),
        )

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
        data = self.objects[key]
        if max_bytes is not None and len(data) > max_bytes:
            raise ValueError("Stored object exceeds the permitted read size")
        return data


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    storage = _FakeStorage()
    events: list[tuple[str, str, dict]] = []

    async def fake_append(run_id, event_type, payload):
        events.append((run_id, event_type, payload))

    monkeypatch.setattr(worker_files, "get_session_factory", lambda: factory)
    monkeypatch.setattr(worker_files, "chat_object_storage", lambda: storage)
    monkeypatch.setattr(worker, "_append", fake_append)
    worker_files.reset_debounce("run-1")
    yield SimpleNamespace(factory=factory, storage=storage, events=events)
    await engine.dispose()


async def _mirror(tool_name: str, tool_input, *, run_id: str = "run-1") -> None:
    await worker_files.mirror_file_tool(
        run_id=run_id,
        org_id=ORG,
        user_id=USER,
        conversation_id=CONV,
        tool_name=tool_name,
        tool_input=tool_input,
    )


async def _write(path: str, content: str = "hello", *, tool: str = "Write", run_id: str = "run-1") -> None:
    await _mirror(tool, {"file_path": path, "content": content}, run_id=run_id)


async def _rows(factory) -> list[GatewayChatFile]:
    async with factory() as db:
        return list((await db.execute(select(GatewayChatFile))).scalars())


def _files_changed(env) -> list[tuple[str, str, dict]]:
    return [event for event in env.events if event[1] == "files_changed"]


# ── Write ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_creates_row_object_and_event(env):
    await _write(f"{ROOT}/run-1/notes/spec.md", "hello")
    rows = await _rows(env.factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.path == "run-1/notes/spec.md"
    assert row.filename == "spec.md"
    assert row.kind == "markdown"
    assert row.origin == "mirror"
    assert row.origin_run_id == "run-1"
    assert row.byte_size == 5
    assert row.content_hash == hashlib.sha256(b"hello").hexdigest()
    assert env.storage.objects[row.object_key] == b"hello"
    assert _files_changed(env) == [("run-1", "files_changed", {"changed": 1})]


@pytest.mark.asyncio
async def test_prefixed_tool_names_are_handled(env):
    await _write(f"{ROOT}/run-1/report.md", "x", tool="mcp__scratch__Write")
    assert len(await _rows(env.factory)) == 1


@pytest.mark.asyncio
async def test_rewrite_reuses_the_existing_object_key(env):
    await _write(f"{ROOT}/run-1/a.md", "one")
    first_key = (await _rows(env.factory))[0].object_key
    await _write(f"{ROOT}/run-1/a.md", "two")
    rows = await _rows(env.factory)
    assert len(rows) == 1
    assert rows[0].object_key == first_key
    assert env.storage.objects[first_key] == b"two"


@pytest.mark.asyncio
async def test_non_file_tools_are_ignored(env):
    await _mirror("Bash", {"file_path": f"{ROOT}/run-1/a.md", "content": "x"})
    await _mirror("Read", {"file_path": f"{ROOT}/run-1/a.md"})
    assert await _rows(env.factory) == []
    assert env.storage.objects == {}


@pytest.mark.asyncio
async def test_oversized_write_is_skipped(env, monkeypatch):
    monkeypatch.setattr(worker_files, "_MAX_WRITE_BYTES", 4)
    await _write(f"{ROOT}/run-1/big.md", "hello")
    assert await _rows(env.factory) == []
    assert env.events == []


# ── Path rules ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paths_outside_the_scratch_root_are_rejected(env):
    for path in (
        "/etc/passwd",
        f"{ROOT}/run-1/../../etc/passwd",
        "relative/notes.md",
        ROOT,
    ):
        await _write(path)
    assert await _rows(env.factory) == []
    assert env.events == []


@pytest.mark.asyncio
async def test_skipped_basenames_and_segments(env):
    for path in (
        f"{ROOT}/run-1/.gateway-token",
        f"{ROOT}/run-1/analysis.py",
        f"{ROOT}/run-1/.env",
        f"{ROOT}/run-1/__pycache__/mod.py",
        f"{ROOT}/run-1/.git/config",
    ):
        await _write(path)
    assert await _rows(env.factory) == []
    assert env.events == []


# ── Edit and MultiEdit ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_applies_the_replacement_and_updates_the_hash(env):
    await _write(f"{ROOT}/run-1/a.md", "alpha beta alpha")
    await _mirror(
        "Edit",
        {"file_path": f"{ROOT}/run-1/a.md", "old_string": "alpha", "new_string": "gamma"},
    )
    rows = await _rows(env.factory)
    assert env.storage.objects[rows[0].object_key] == b"gamma beta alpha"
    assert rows[0].content_hash == hashlib.sha256(b"gamma beta alpha").hexdigest()


@pytest.mark.asyncio
async def test_edit_replace_all(env):
    await _write(f"{ROOT}/run-1/a.md", "alpha beta alpha")
    await _mirror(
        "Edit",
        {
            "file_path": f"{ROOT}/run-1/a.md",
            "old_string": "alpha",
            "new_string": "gamma",
            "replace_all": True,
        },
    )
    rows = await _rows(env.factory)
    assert env.storage.objects[rows[0].object_key] == b"gamma beta gamma"


@pytest.mark.asyncio
async def test_edit_with_a_non_matching_old_string_is_a_no_op(env):
    await _write(f"{ROOT}/run-1/a.md", "alpha")
    await _mirror(
        "Edit",
        {"file_path": f"{ROOT}/run-1/a.md", "old_string": "missing", "new_string": "x"},
    )
    rows = await _rows(env.factory)
    assert env.storage.objects[rows[0].object_key] == b"alpha"
    assert rows[0].content_hash == hashlib.sha256(b"alpha").hexdigest()


@pytest.mark.asyncio
async def test_edit_without_an_existing_row_is_a_no_op(env):
    await _mirror(
        "Edit",
        {"file_path": f"{ROOT}/run-1/a.md", "old_string": "a", "new_string": "b"},
    )
    assert await _rows(env.factory) == []


@pytest.mark.asyncio
async def test_edit_of_an_oversized_object_is_skipped(env, monkeypatch):
    await _write(f"{ROOT}/run-1/a.md", "alpha")
    monkeypatch.setattr(worker_files, "_MAX_EDIT_SOURCE_BYTES", 2)
    await _mirror(
        "Edit",
        {"file_path": f"{ROOT}/run-1/a.md", "old_string": "alpha", "new_string": "x"},
    )
    rows = await _rows(env.factory)
    assert env.storage.objects[rows[0].object_key] == b"alpha"


@pytest.mark.asyncio
async def test_multi_edit_applies_edits_sequentially(env):
    await _write(f"{ROOT}/run-1/a.md", "one two")
    await _mirror(
        "MultiEdit",
        {
            "file_path": f"{ROOT}/run-1/a.md",
            "edits": [
                {"old_string": "one", "new_string": "1"},
                {"old_string": "1 two", "new_string": "1 2"},
            ],
        },
    )
    rows = await _rows(env.factory)
    assert env.storage.objects[rows[0].object_key] == b"1 2"


@pytest.mark.asyncio
async def test_multi_edit_aborts_on_the_first_non_matching_edit(env):
    await _write(f"{ROOT}/run-1/a.md", "one two")
    await _mirror(
        "MultiEdit",
        {
            "file_path": f"{ROOT}/run-1/a.md",
            "edits": [
                {"old_string": "one", "new_string": "1"},
                {"old_string": "missing", "new_string": "x"},
            ],
        },
    )
    rows = await _rows(env.factory)
    assert env.storage.objects[rows[0].object_key] == b"one two"


# ── Debounce ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_files_changed_is_debounced_per_run(env):
    await _write(f"{ROOT}/run-1/a.md", "one")
    await _write(f"{ROOT}/run-1/b.md", "two")
    assert len(_files_changed(env)) == 1
    worker_files.reset_debounce("run-1")
    await _write(f"{ROOT}/run-1/c.md", "three")
    assert len(_files_changed(env)) == 2


@pytest.mark.asyncio
async def test_debounce_is_scoped_to_the_run(env):
    worker_files.reset_debounce("run-2")
    await _write(f"{ROOT}/run-1/a.md", "one")
    await _write(f"{ROOT}/run-2/a.md", "two", run_id="run-2")
    assert len(_files_changed(env)) == 2


# ── Failure isolation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_errors_never_propagate(env):
    async def broken_put(**kwargs):
        raise RuntimeError("s3 exploded")

    env.storage.put_bytes = broken_put
    await _write(f"{ROOT}/run-1/a.md", "one")
    assert await _rows(env.factory) == []
    assert env.events == []


@pytest.mark.asyncio
async def test_disabled_storage_is_a_fast_no_op(env):
    env.storage.enabled = False
    await _write(f"{ROOT}/run-1/a.md", "one")
    assert await _rows(env.factory) == []
    assert env.events == []


@pytest.mark.asyncio
async def test_malformed_input_never_propagates(env):
    await _mirror("Write", None)
    await _mirror("Write", {"file_path": 42, "content": "x"})
    await _mirror("Write", {"file_path": f"{ROOT}/run-1/a.md", "content": 42})
    await _mirror("MultiEdit", {"file_path": f"{ROOT}/run-1/a.md", "edits": "nope"})
    assert await _rows(env.factory) == []


# ── Review-round hardening ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_bearing_content_is_never_stored(env):
    await worker_files.mirror_file_tool(
        run_id="run-1",
        org_id=ORG,
        user_id=USER,
        conversation_id=CONV,
        tool_name="Write",
        tool_input={
            "file_path": f"{ROOT}/run-1/leak.md",
            "content": "token is sekret-token-value here",
        },
        secrets=("sekret-token-value",),
    )
    assert await _rows(env.factory) == []
    assert env.storage.objects == {}


@pytest.mark.asyncio
async def test_edit_mismatch_soft_deletes_the_stale_row(env):
    await _write(f"{ROOT}/run-1/spec.md", "alpha beta")
    worker_files.reset_debounce("run-1")
    await _mirror(
        "Edit",
        {
            "file_path": f"{ROOT}/run-1/spec.md",
            "old_string": "NOT PRESENT",
            "new_string": "x",
        },
    )
    rows = await _rows(env.factory)
    assert len(rows) == 1
    assert rows[0].status == "deleted"
    # The stale drop announces itself so the panel refetches.
    assert len(_files_changed(env)) == 2


@pytest.mark.asyncio
async def test_control_characters_are_stripped_from_filenames(env):
    await _write(f"{ROOT}/run-1/bad\rname.md", "x")
    rows = await _rows(env.factory)
    assert len(rows) == 1
    assert "\r" not in rows[0].filename
    assert rows[0].filename == "bad_name.md"
