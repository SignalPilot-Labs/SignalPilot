"""POST /api/chat/runtime-files: sandbox file ingest.

Covers scope and run-state guards, path rules, size and hash checks, the
token refusal, image sniffing, the unchanged short-circuit, the
files_changed payload, soft deletes, quotas, and shared-file visibility.
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.chat_routes import files as files_routes
from gateway.api.chat_routes import runtime_files as routes
from gateway.db.models import GatewayBase, GatewayChatRun, GatewayWorkspaceProject
from gateway.models.standalone_chat import ChatRunEventInfo
from gateway.standalone_chat.object_storage import StoredObject, conversation_prefix
from gateway.store import standalone_chat as chat_store

ORG = "org-a"
USER = "user-a"
PROJECT = "project-a"
TOKEN = "scoped-run-token-abcdef0123456789"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "1")
    monkeypatch.setenv("SP_FEATURE_CHAT_ORG_SHARING", "1")


class _FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        self.objects[key] = data
        self.content_types[key] = content_type
        return StoredObject(key=key, byte_size=len(data), content_hash=hashlib.sha256(data).hexdigest())

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
        return self.objects[key]

    async def copy(self, *, source_key: str, destination_key: str) -> StoredObject:
        data = self.objects[source_key]
        self.objects[destination_key] = data
        return StoredObject(
            key=destination_key, byte_size=len(data), content_hash=hashlib.sha256(data).hexdigest()
        )


@pytest.fixture
def storage(monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr(routes, "chat_object_storage", lambda: fake)
    monkeypatch.setattr(files_routes, "chat_object_storage", lambda: fake)
    monkeypatch.setattr(chat_store, "chat_object_storage", lambda: fake)
    return fake


async def _running_run(db: AsyncSession) -> GatewayChatRun:
    project = GatewayWorkspaceProject(
        id=PROJECT,
        org_id=ORG,
        name="revenue",
        display_name="Revenue",
        description="Revenue analytics",
        connection_name="production",
        source="managed",
        status="active",
        settings={},
        file_count=1,
        total_bytes=10,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db.add(project)
    await db.commit()
    _conversation, run = await chat_store.create_conversation_with_run(
        db,
        org_id=ORG,
        user_id=USER,
        project=project,
        branch="main",
        message="Chart revenue",
        commit_sha="a" * 40,
    )
    run.status = "running"
    await db.commit()
    return run


def _store(db: AsyncSession, user_id: str = USER):
    return SimpleNamespace(session=db, user_id=user_id, _require_org_id=lambda: ORG)


def _request(run_id: str, *, token: str = TOKEN, project_id: str = PROJECT):
    return SimpleNamespace(
        state=SimpleNamespace(
            _jwt_claims={"execution_identity": f"chat:{run_id}", "project_id": project_id}
        ),
        headers={"authorization": f"Bearer {token}"},
    )


def _upload(data: bytes, filename: str = "upload.bin") -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=filename, size=len(data))


async def _post(
    db: AsyncSession,
    run: GatewayChatRun,
    path: str,
    data: bytes | None,
    *,
    content_hash: str | None = "auto",
    tool_call_id: str | None = "toolu_1",
    deleted: str | None = None,
    request=None,
):
    if content_hash == "auto":
        content_hash = hashlib.sha256(data or b"").hexdigest()
    return await routes.publish_runtime_file(
        request or _request(run.id),
        _store(db),
        path=path,
        content_hash=content_hash,
        tool_call_id=tool_call_id,
        reason="tool",
        deleted=deleted,
        file=_upload(data) if data is not None else None,
    )


async def _events(db: AsyncSession, run: GatewayChatRun, event_type: str = "files_changed"):
    events = await chat_store.list_run_events(db, org_id=ORG, user_id=USER, run_id=run.id)
    return [event for event in events if event.type == event_type]


# ── Guards ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requires_a_chat_run_identity(db_session, enabled, storage):
    run = await _running_run(db_session)
    request = SimpleNamespace(
        state=SimpleNamespace(_jwt_claims={"execution_identity": "agent", "project_id": PROJECT}),
        headers={},
    )
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/x.png", PNG, request=request)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rejects_a_finished_run_and_a_foreign_project(db_session, enabled, storage):
    run = await _running_run(db_session)
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/x.png", PNG, request=_request(run.id, project_id="other"))
    assert exc.value.status_code == 403

    run.status = "completed"
    run.terminal_at = datetime.now(UTC)
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/x.png", PNG)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_disabled_feature_hides_the_route(db_session, storage, monkeypatch):
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "0")
    run = await _running_run(db_session)
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/x.png", PNG)
    assert exc.value.status_code == 404


# ── Path rules ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/abs/x.png",
        "artifacts/../x.png",
        "../x.png",
        "artifacts//x.png",
        "artifacts/.hidden",
        ".claude/settings.json",
        "artifacts/__pycache__/x.pyc",
        "analysis.py",
        "a" * 513,
        "artifacts\\x.png",
        "artifacts/bad\x00name",
    ],
)
def test_path_rules_reject(path):
    with pytest.raises(HTTPException) as exc:
        routes.validate_runtime_path(path)
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    "path",
    ["artifacts/x.png", "notes/deep/report.md", "artifacts/helper.py", "x.csv", "a" * 512],
)
def test_path_rules_accept(path):
    assert routes.validate_runtime_path(path) == path


# ── Body, hash, secret ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oversize_body_is_413(db_session, enabled, storage, monkeypatch):
    monkeypatch.setenv("SP_CHAT_FILE_MAX_BYTES", "1024")
    run = await _running_run(db_session)
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/big.bin", b"x" * 1025)
    assert exc.value.status_code == 413
    assert storage.objects == {}


@pytest.mark.asyncio
async def test_hash_mismatch_is_422(db_session, enabled, storage):
    run = await _running_run(db_session)
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/x.csv", b"a,b\n1,2\n", content_hash="0" * 64)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/x.csv", b"a,b\n1,2\n", content_hash=None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_missing_file_part_is_422(db_session, enabled, storage):
    run = await _running_run(db_session)
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/x.csv", None, content_hash="0" * 64)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_token_bearing_bytes_are_refused(db_session, enabled, storage):
    run = await _running_run(db_session)
    data = b"export TOKEN=" + TOKEN.encode() + b"\n"
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/env.txt", data)
    assert exc.value.status_code == 422
    assert TOKEN not in exc.value.detail
    assert storage.objects == {}
    assert await _events(db_session, run) == []


# ── Classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PNG, "image/png"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 8, "image/jpeg"),
        (b"GIF89a" + b"\x00" * 8, "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b'<?xml version="1.0"?>\n<SVG xmlns="http://www.w3.org/2000/svg"></SVG>', "image/svg+xml"),
        (b"not an image", None),
    ],
)
def test_sniff_image_mime(data, mime):
    assert routes.sniff_image_mime(data) == mime


def test_classify_downgrades_fake_images_and_keeps_text_kinds():
    assert routes.classify("chart.png", b"<html>") == ("other", "application/octet-stream")
    assert routes.classify("chart.png", PNG) == ("image", "image/png")
    assert routes.classify("rows.csv", b"a,b\n") == ("data", "text/csv")
    assert routes.classify("report.html", b"<html>") == ("html", "text/html")
    assert routes.classify("notes.md", b"# hi") == ("markdown", "text/markdown")
    assert routes.classify("blob", b"\x00\x01")[0] == "other"


@pytest.mark.asyncio
async def test_fake_png_is_stored_as_other(db_session, enabled, storage):
    run = await _running_run(db_session)
    result = await _post(db_session, run, "artifacts/chart.png", b"<script>alert(1)</script>")
    assert result["kind"] == "other"
    row = await chat_store.get_conversation_file(
        db_session, org_id=ORG, user_id=USER, conversation_id=run.conversation_id, file_id=result["file_id"]
    )
    assert row is not None
    assert row.kind == "other"
    assert row.mime_type == "application/octet-stream"


# ── Happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_file_is_stored_and_announced(db_session, enabled, storage):
    run = await _running_run(db_session)
    result = await _post(db_session, run, "artifacts/revenue.png", PNG)
    assert set(result) == {"file_id", "path", "kind", "byte_size", "content_hash"}
    assert result["path"] == "artifacts/revenue.png"
    assert result["kind"] == "image"
    assert result["byte_size"] == len(PNG)
    assert result["content_hash"] == hashlib.sha256(PNG).hexdigest()

    row = await chat_store.get_conversation_file(
        db_session, org_id=ORG, user_id=USER, conversation_id=run.conversation_id, file_id=result["file_id"]
    )
    assert row is not None
    assert row.origin == "runtime"
    assert row.origin_run_id == run.id
    assert row.mime_type == "image/png"
    assert row.object_key.startswith(f"{conversation_prefix(ORG, run.conversation_id)}/files/")
    assert row.object_key.endswith(f"{row.id}-revenue.png")
    assert storage.objects[row.object_key] == PNG
    assert storage.content_types[row.object_key] == "image/png"

    events = await _events(db_session, run)
    assert len(events) == 1
    payload = events[0].payload
    assert payload == {
        "changed": 1,
        "files": [
            {
                "file_id": row.id,
                "path": "artifacts/revenue.png",
                "filename": "revenue.png",
                "kind": "image",
                "byte_size": len(PNG),
                "content_hash": hashlib.sha256(PNG).hexdigest(),
                "deleted": False,
            }
        ],
        "tool_call_id": "toolu_1",
        "origin": "runtime",
    }
    # The enriched payload must replay through the public event model.
    info = ChatRunEventInfo(
        run_id=run.id, sequence=1, type="files_changed", payload=payload, created_at=datetime.now(UTC)
    )
    assert info.type == "files_changed"


@pytest.mark.asyncio
async def test_unchanged_upload_is_200_without_an_event(db_session, enabled, storage):
    run = await _running_run(db_session)
    first = await _post(db_session, run, "artifacts/revenue.png", PNG)
    second = await _post(db_session, run, "artifacts/revenue.png", PNG, tool_call_id="toolu_2")
    assert second.status_code == 200
    assert second.body == b'{"file_id":"%s","unchanged":true}' % first["file_id"].encode()
    assert len(await _events(db_session, run)) == 1
    assert len(storage.objects) == 1


@pytest.mark.asyncio
async def test_changed_upload_reuses_the_key_and_announces_again(db_session, enabled, storage):
    run = await _running_run(db_session)
    first = await _post(db_session, run, "artifacts/rows.csv", b"a\n1\n")
    second = await _post(db_session, run, "artifacts/rows.csv", b"a\n1\n2\n", tool_call_id="toolu_2")
    assert second["file_id"] == first["file_id"]
    assert second["content_hash"] != first["content_hash"]
    assert len(storage.objects) == 1
    assert list(storage.objects.values()) == [b"a\n1\n2\n"]
    events = await _events(db_session, run)
    assert [event.payload["tool_call_id"] for event in events] == ["toolu_1", "toolu_2"]
    assert events[1].payload["files"][0]["content_hash"] == second["content_hash"]


@pytest.mark.asyncio
async def test_delete_soft_deletes_and_announces(db_session, enabled, storage):
    run = await _running_run(db_session)
    created = await _post(db_session, run, "artifacts/rows.csv", b"a\n1\n")
    response = await _post(db_session, run, "artifacts/rows.csv", None, content_hash=None, deleted="1")
    assert response.status_code == 200
    row = await chat_store.get_conversation_file_by_path(
        db_session, org_id=ORG, user_id=USER, conversation_id=run.conversation_id, path="artifacts/rows.csv"
    )
    assert row is not None and row.status == "deleted"
    events = await _events(db_session, run)
    assert len(events) == 2
    assert events[1].payload["files"][0] == {
        "file_id": created["file_id"],
        "path": "artifacts/rows.csv",
        "filename": "rows.csv",
        "kind": "data",
        "byte_size": 4,
        "content_hash": created["content_hash"],
        "deleted": True,
    }
    # A second delete is a no-op.
    again = await _post(db_session, run, "artifacts/rows.csv", None, content_hash=None, deleted="1")
    assert again.status_code == 200
    assert b'"unchanged":true' in again.body
    assert len(await _events(db_session, run)) == 2

    # A later write reactivates the same row.
    revived = await _post(db_session, run, "artifacts/rows.csv", b"a\n9\n")
    assert revived["file_id"] == created["file_id"]


# ── Quotas ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_count_quota_is_413(db_session, enabled, storage, monkeypatch):
    monkeypatch.setenv("SP_CHAT_CONVERSATION_FILE_QUOTA_COUNT", "2")
    run = await _running_run(db_session)
    await _post(db_session, run, "artifacts/a.csv", b"a\n")
    await _post(db_session, run, "artifacts/b.csv", b"b\n")
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/c.csv", b"c\n")
    assert exc.value.status_code == 413
    # Replacing an existing file does not count against the limit.
    replaced = await _post(db_session, run, "artifacts/a.csv", b"a2\n")
    assert replaced["byte_size"] == 3


@pytest.mark.asyncio
async def test_byte_quota_is_413(db_session, enabled, storage, monkeypatch):
    monkeypatch.setenv("SP_CHAT_CONVERSATION_FILE_QUOTA_BYTES", "1024")
    run = await _running_run(db_session)
    await _post(db_session, run, "artifacts/a.bin", b"x" * 600)
    with pytest.raises(HTTPException) as exc:
        await _post(db_session, run, "artifacts/b.bin", b"y" * 600)
    assert exc.value.status_code == 413
    # Replacing a.bin frees its bytes first.
    replaced = await _post(db_session, run, "artifacts/a.bin", b"z" * 1000)
    assert replaced["byte_size"] == 1000


# ── Sharing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shared_files_hide_running_run_output_until_terminal(db_session, enabled, storage):
    run = await _running_run(db_session)
    created = await _post(db_session, run, "artifacts/revenue.png", PNG)
    shared = await chat_store.create_share_grant(
        db_session, org_id=ORG, user_id=USER, conversation_id=run.conversation_id
    )
    assert shared is not None
    _, token = shared

    listed = await files_routes.list_shared_conversation_files(token, _store(db_session, "user-b"))
    assert listed == {"files": []}
    with pytest.raises(HTTPException) as exc:
        await files_routes.get_shared_conversation_file_content(
            token, created["file_id"], _store(db_session, "user-b")
        )
    assert exc.value.status_code == 404

    run.status = "completed"
    run.terminal_at = datetime.now(UTC)
    await db_session.commit()

    listed = await files_routes.list_shared_conversation_files(token, _store(db_session, "user-b"))
    assert [item["id"] for item in listed["files"]] == [created["file_id"]]
    response = await files_routes.get_shared_conversation_file_content(
        token, created["file_id"], _store(db_session, "user-b")
    )
    assert response.body == PNG
    assert response.headers["ETag"] == f'"{created["content_hash"]}"'

    # A revoked grant closes the door.
    await chat_store.revoke_share_grants(
        db_session, org_id=ORG, user_id=USER, conversation_id=run.conversation_id
    )
    with pytest.raises(HTTPException) as exc:
        await files_routes.list_shared_conversation_files(token, _store(db_session, "user-b"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_shared_list_excludes_files_of_a_nonterminal_run(db_session, enabled, storage):
    run = await _running_run(db_session)

    async def _row(path: str, origin_run_id: str | None):
        return await chat_store.upsert_conversation_file(
            db_session,
            org_id=ORG,
            user_id=USER,
            conversation_id=run.conversation_id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            mime_type="text/markdown",
            byte_size=1,
            content_hash=hashlib.sha256(b"x").hexdigest(),
            object_key=f"objects/{path}",
            origin_run_id=origin_run_id,
            origin="mirror",
        )

    live = await _row("artifacts/live.md", run.id)
    safe = await _row("artifacts/safe.md", None)
    shared = await chat_store.create_share_grant(
        db_session, org_id=ORG, user_id=USER, conversation_id=run.conversation_id
    )
    assert shared is not None
    _, token = shared
    viewer = _store(db_session, "user-b")
    listed = await files_routes.list_shared_conversation_files(token, viewer)
    assert [item["id"] for item in listed["files"]] == [safe.id]
    with pytest.raises(HTTPException) as exc:
        await files_routes.get_shared_conversation_file_content(token, live.id, viewer)
    assert exc.value.status_code == 404

    run.status = "completed"
    run.terminal_at = datetime.now(UTC)
    await db_session.commit()
    listed = await files_routes.list_shared_conversation_files(token, viewer)
    assert {item["id"] for item in listed["files"]} == {live.id, safe.id}
