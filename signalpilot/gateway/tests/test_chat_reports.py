"""Focused acceptance contracts for the Data Chat report library."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.chat_reports import _require_browser_principal
from gateway.connectors.schema_cache import _schema_fingerprint
from gateway.db.models import (
    GatewayBase,
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayReportRefresh,
    GatewaySavedReportVersion,
    GatewayWorkspaceProject,
)
from gateway.http.log_redaction import SecretPathLogFilter, redact_secret_path
from gateway.store import chat_reports
from gateway.store import standalone_chat as chat_store


@pytest_asyncio.fixture
async def db_session():
    database_url = os.getenv("CHAT_REPORTS_TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        if database_url.startswith("postgresql"):
            await connection.run_sync(GatewayBase.metadata.drop_all)
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_project(db: AsyncSession) -> None:
    db.add(
        GatewayWorkspaceProject(
            id="project-a",
            org_id="org-a",
            name="revenue",
            display_name="Revenue Warehouse",
            description="Revenue analytics",
            connection_name="production",
            source="managed",
            status="active",
            settings={"dbt_metadata_checksum": "metadata-a"},
            file_count=1,
            total_bytes=100,
            default_branch="main",
            created_at=1.0,
            updated_at=1.0,
        )
    )
    await db.commit()


async def _artifact(
    db: AsyncSession,
    *,
    user_id: str = "user-a",
    artifact_id: str | None = None,
    conversation_id: str | None = None,
    filename: str = "revenue.csv",
    value: int = 100,
    title: str = "Quarterly revenue",
    created_at: datetime | None = None,
) -> GatewayChatArtifact:
    artifact_id = artifact_id or str(uuid.uuid4())
    conversation_id = conversation_id or f"conversation-{artifact_id}"
    run_id = f"run-{artifact_id}"
    if await db.get(GatewayChatConversation, conversation_id) is None:
        db.add(
            GatewayChatConversation(
                id=conversation_id,
                org_id="org-a",
                user_id=user_id,
                project_id="project-a",
                surface="standalone",
                branch="main",
                commit_sha="a" * 40,
                status="active",
                title=title,
                message_count=1,
                total_tokens=0,
                total_cost_usd=0,
                created_at=1.0,
                updated_at=1.0,
            )
        )
    db.add(
        GatewayChatRun(
            id=run_id,
            org_id="org-a",
            user_id=user_id,
            conversation_id=conversation_id,
            project_id="project-a",
            user_message_id=f"message-{artifact_id}",
            status="completed",
            terminal_at=datetime.now(UTC),
        )
    )
    artifact = GatewayChatArtifact(
        id=artifact_id,
        org_id="org-a",
        user_id=user_id,
        conversation_id=conversation_id,
        run_id=run_id,
        kind="table",
        filename=filename,
        mime_type="text/csv",
        snapshot_json={
            "columns": [{"name": "revenue"}],
            "rows": [{"revenue": value, "private_dataset_text": "dataset-only-needle"}],
        },
        storage_kind="inline",
        content_hash=None,
        freshness_at=datetime(2026, 8, 1, tzinfo=UTC),
        provenance_json={"commit_sha": "a" * 40, "sql": "select private rows"},
        created_at=created_at or datetime.now(UTC),
    )
    db.add(artifact)
    await db.commit()
    return artifact


@pytest.mark.asyncio
async def test_library_is_owner_only_and_searches_metadata_not_rows(db_session: AsyncSession) -> None:
    await _seed_project(db_session)
    artifact = await _artifact(db_session, filename="recognized-file.csv")
    await _artifact(db_session, user_id="user-b", filename="other-user-secret.csv")

    visible = await chat_reports.list_library(
        db_session,
        org_id="org-a",
        user_id="user-a",
        search="recognized-file",
    )
    assert [item.id for item in visible.artifacts.items] == [artifact.id]
    assert visible.facets.projects == [{"id": "project-a", "name": "Revenue Warehouse"}]

    dataset_search = await chat_reports.list_library(
        db_session,
        org_id="org-a",
        user_id="user-a",
        search="dataset-only-needle",
    )
    assert dataset_search.artifacts.items == []
    assert dataset_search.reports.items == []

    peer = await chat_reports.list_library(db_session, org_id="org-a", user_id="user-b")
    assert len(peer.artifacts.items) == 1
    assert peer.artifacts.items[0].id != artifact.id


@pytest.mark.asyncio
async def test_library_groups_same_thread_and_filename_using_the_newest_artifact(
    db_session: AsyncSession,
) -> None:
    await _seed_project(db_session)
    older = await _artifact(
        db_session,
        artifact_id="artifact-group-older",
        conversation_id="conversation-grouped",
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
    )
    other_thread = await _artifact(
        db_session,
        artifact_id="artifact-other-thread",
        conversation_id="conversation-other",
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    newest = await _artifact(
        db_session,
        artifact_id="artifact-group-newest",
        conversation_id="conversation-grouped",
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
        value=200,
    )

    library = await chat_reports.list_library(db_session, org_id="org-a", user_id="user-a")

    assert [item.id for item in library.artifacts.items] == [newest.id, other_thread.id]
    assert older.id not in {item.id for item in library.artifacts.items}
    grouped = library.artifacts.items[0]
    assert isinstance(grouped, chat_reports.LibraryArtifact)
    assert [item.id for item in grouped.history] == [newest.id, older.id]


@pytest.mark.asyncio
async def test_promotion_deduplicates_exact_content_within_owner_only(db_session: AsyncSession) -> None:
    await _seed_project(db_session)
    first = await _artifact(db_session, artifact_id="artifact-one", value=100)
    duplicate = await _artifact(db_session, artifact_id="artifact-two", value=100)
    other_user = await _artifact(db_session, user_id="user-b", artifact_id="artifact-peer", value=100)

    status, report, version = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=first.id,
        title="Revenue report",
    )
    assert status == "created"
    assert first.content_hash is not None

    duplicate_status, duplicate_report, duplicate_version = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=duplicate.id,
        title="Ignored duplicate title",
    )
    assert duplicate_status == "existing"
    assert duplicate_report.id == report.id
    assert duplicate_version.id == version.id

    peer_status, peer_report, _ = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-b",
        artifact_id=other_user.id,
        title="Peer revenue",
    )
    assert peer_status == "created"
    assert peer_report.id != report.id


@pytest.mark.asyncio
async def test_promotion_appends_a_version_for_a_case_insensitive_title_match(
    db_session: AsyncSession,
) -> None:
    await _seed_project(db_session)
    first = await _artifact(db_session, artifact_id="artifact-title-one", value=100)
    second = await _artifact(
        db_session,
        artifact_id="artifact-title-two",
        filename="revenue 2026.csv",
        value=200,
    )

    _, report, version_one = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=first.id,
        title="Revenue 2026",
    )
    saved_detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=first.conversation_id,
    )
    assert saved_detail is not None
    first_info = next(item for item in saved_detail.artifacts if item.id == first.id)
    assert first_info.report_action == "open"

    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=second.conversation_id,
    )
    assert detail is not None
    second_info = next(item for item in detail.artifacts if item.id == second.id)
    assert second_info.report_action == "update"
    assert second_info.saved_report_id == report.id
    assert second_info.saved_report_version_id == version_one.id
    assert second_info.saved_report_title == "Revenue 2026"

    status, matching_report, version_two = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=second.id,
        title="revenue 2026",
    )

    assert status == "updated"
    assert matching_report.id == report.id
    assert matching_report.revision == 2
    assert matching_report.current_version_id == version_two.id
    assert version_two.id != version_one.id
    assert version_two.ordinal == 2
    reports = list((await db_session.execute(select(GatewaySavedReportVersion.report_id))).scalars())
    assert reports == [report.id, report.id]


async def _refresh_candidate(
    db: AsyncSession,
    *,
    report_id: str,
    base_version_id: str,
    artifact: GatewayChatArtifact,
    drift_state: str = "none",
) -> GatewayReportRefresh:
    refresh = GatewayReportRefresh(
        id=str(uuid.uuid4()),
        report_id=report_id,
        base_version_id=base_version_id,
        org_id="org-a",
        owner_user_id="user-a",
        original_conversation_id=artifact.conversation_id,
        drift_state=drift_state,
        drift_json={
            "explanation": "No changes",
            "observed_schema_fingerprint": "schema-b",
        },
        run_id=artifact.run_id,
        status="update_available",
        candidate_artifact_ids_json=[artifact.id],
    )
    db.add(refresh)
    await db.commit()
    return refresh


@pytest.mark.asyncio
async def test_promoting_a_refresh_artifact_updates_the_originating_report(
    db_session: AsyncSession,
) -> None:
    await _seed_project(db_session)
    base = await _artifact(db_session, artifact_id="artifact-report-base", value=100)
    _, report, version_one = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=base.id,
        title="Revenue 2026",
    )
    refreshed = await _artifact(db_session, artifact_id="artifact-report-refresh", value=200)
    refresh = await _refresh_candidate(
        db_session,
        report_id=report.id,
        base_version_id=version_one.id,
        artifact=refreshed,
    )

    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=refreshed.conversation_id,
    )
    assert detail is not None
    refreshed_info = next(item for item in detail.artifacts if item.id == refreshed.id)
    assert refreshed_info.report_action == "update"
    assert refreshed_info.saved_report_id == report.id
    assert refreshed_info.saved_report_version_id == version_one.id
    assert refreshed_info.saved_report_title == "Revenue 2026"

    status, updated_report, version_two = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=refreshed.id,
        title="Revenue 2026",
    )

    assert status == "updated"
    assert updated_report.id == report.id
    assert updated_report.revision == 2
    assert updated_report.current_version_id == version_two.id
    assert version_two.ordinal == 2
    assert refresh.status == "current"
    report_ids = list((await db_session.execute(select(GatewaySavedReportVersion.report_id))).scalars())
    assert report_ids == [report.id, report.id]


@pytest.mark.asyncio
async def test_refresh_queues_a_plain_agent_request_without_confirmation(
    db_session: AsyncSession,
) -> None:
    await _seed_project(db_session)
    base = await _artifact(db_session, artifact_id="artifact-base", value=100)
    _, report, version = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=base.id,
        title="Revenue report",
    )

    refresh = await chat_reports.create_refresh(
        db_session,
        org_id="org-a",
        user_id="user-a",
        report_id=report.id,
        expected_version_id=version.id,
    )

    assert refresh.status == "refreshing"
    assert refresh.run_id is not None
    assert refresh.confirmed_at is None
    run = await db_session.get(GatewayChatRun, refresh.run_id)
    assert run is not None
    message = await db_session.get(GatewayChatMessage, run.user_message_id)
    assert message is not None
    assert message.content == (
        'Refresh saved report "Revenue report" using current live warehouse data. Publish a table artifact for review.'
    )
    assert "commit" not in message.content.lower()
    assert message.metadata_json["report_reference"] == {
        "mode": "refresh",
        "report_id": report.id,
        "version_id": version.id,
        "version_ordinal": 1,
        "title": "Revenue report",
        "kind": "table",
        "source_artifact_id": base.id,
        "drift": {"explanation": "Refresh requested in the original thread."},
    }


@pytest.mark.asyncio
async def test_updates_require_refresh_lineage_preserve_history_and_detect_stale_writers(
    db_session: AsyncSession,
) -> None:
    await _seed_project(db_session)
    base_artifact = await _artifact(db_session, artifact_id="artifact-base", value=100)
    _, report, version_one = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=base_artifact.id,
        title="Revenue report",
    )
    candidate = await _artifact(db_session, artifact_id="artifact-refresh", value=200)
    await _refresh_candidate(
        db_session,
        report_id=report.id,
        base_version_id=version_one.id,
        artifact=candidate,
    )

    status, updated_report, version_two = await chat_reports.publish_version(
        db_session,
        org_id="org-a",
        user_id="user-a",
        report_id=report.id,
        artifact_id=candidate.id,
        expected_current_version_id=version_one.id,
    )
    assert status == "created"
    assert version_two.ordinal == 2
    assert updated_report.current_version_id == version_two.id
    assert (
        len(
            list(
                (
                    await db_session.execute(
                        select(GatewaySavedReportVersion).where(GatewaySavedReportVersion.report_id == report.id)
                    )
                ).scalars()
            )
        )
        == 2
    )

    with pytest.raises(chat_reports.ReportConflictError) as stale:
        await chat_reports.publish_version(
            db_session,
            org_id="org-a",
            user_id="user-a",
            report_id=report.id,
            artifact_id=candidate.id,
            expected_current_version_id=version_one.id,
        )
    assert stale.value.actual_current_version_id == version_two.id

    ordinary_follow_up = await _artifact(db_session, artifact_id="artifact-follow-up", value=300)
    with pytest.raises(chat_reports.ReportValidationError):
        await chat_reports.publish_version(
            db_session,
            org_id="org-a",
            user_id="user-a",
            report_id=report.id,
            artifact_id=ordinary_follow_up.id,
            expected_current_version_id=version_two.id,
        )


@pytest.mark.asyncio
async def test_identical_refresh_is_noop_and_fixed_share_is_remembered_then_revoked(
    db_session: AsyncSession,
) -> None:
    await _seed_project(db_session)
    base = await _artifact(db_session, artifact_id="artifact-base", value=100)
    _, report, version = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=base.id,
        title="Pinned revenue",
    )
    identical = await _artifact(db_session, artifact_id="artifact-identical", value=100)
    refresh = await _refresh_candidate(
        db_session,
        report_id=report.id,
        base_version_id=version.id,
        artifact=identical,
    )
    status, _, matching = await chat_reports.publish_version(
        db_session,
        org_id="org-a",
        user_id="user-a",
        report_id=report.id,
        artifact_id=identical.id,
        expected_current_version_id=version.id,
    )
    assert status == "existing"
    assert matching.id == version.id
    assert refresh.status == "current"

    grant, token = await chat_reports.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        version_id=version.id,
    )
    owner_detail = await chat_reports.get_owned_report_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        report_id=report.id,
    )
    assert owner_detail is not None
    assert owner_detail.active_share_version_ids == [version.id]
    shared = await chat_reports.redeem_shared_report(
        db_session,
        org_id="org-a",
        recipient_user_id="user-b",
        token=token,
    )
    assert shared is not None
    assert shared.version.id == version.id
    assert not hasattr(shared, "original_thread_id")
    shared_payload = shared.model_dump()
    assert "report_id" not in shared_payload
    assert "original_thread_id" not in shared_payload
    assert "content_hash" not in shared_payload["version"]
    assert "dbt_commit_sha" not in shared_payload["version"]
    assert "schema_fingerprint" not in shared_payload["version"]
    assert (
        await chat_reports.redeem_shared_report(
            db_session,
            org_id="org-b",
            recipient_user_id="user-b",
            token=token,
        )
        is None
    )
    assert await chat_reports.authorized_version_artifact(
        db_session,
        org_id="org-a",
        user_id="user-b",
        version_id=version.id,
    )

    later = await _artifact(db_session, artifact_id="artifact-later-version", value=500)
    await _refresh_candidate(
        db_session,
        report_id=report.id,
        base_version_id=version.id,
        artifact=later,
    )
    status, _, version_two = await chat_reports.publish_version(
        db_session,
        org_id="org-a",
        user_id="user-a",
        report_id=report.id,
        artifact_id=later.id,
        expected_current_version_id=version.id,
    )
    assert status == "created"
    assert version_two.ordinal == 2
    pinned = await chat_reports.redeem_shared_report(
        db_session,
        org_id="org-a",
        recipient_user_id="user-b",
        token=token,
    )
    assert pinned is not None
    assert pinned.version.id == version.id

    recipient_library = await chat_reports.list_library(db_session, org_id="org-a", user_id="user-b")
    assert [item.version_id for item in recipient_library.reports.items] == [version.id]
    assert recipient_library.reports.items[0].original_thread_id is None

    assert await chat_reports.revoke_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        version_id=version.id,
    )
    assert grant.state == "revoked"
    owner_detail = await chat_reports.get_owned_report_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        report_id=report.id,
    )
    assert owner_detail is not None
    assert owner_detail.active_share_version_ids == []
    assert (
        await chat_reports.redeem_shared_report(
            db_session,
            org_id="org-a",
            recipient_user_id="user-b",
            token=token,
        )
        is None
    )
    assert (
        await chat_reports.authorized_version_artifact(
            db_session,
            org_id="org-a",
            user_id="user-b",
            version_id=version.id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_report_reference_is_owner_thread_and_version_scoped(db_session: AsyncSession) -> None:
    await _seed_project(db_session)
    artifact = await _artifact(db_session, artifact_id="artifact-reference")
    _, report, version = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=artifact.id,
        title="Reference report",
    )
    reference = await chat_reports.verified_report_reference(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=artifact.conversation_id,
        report_id=report.id,
        version_id=version.id,
    )
    assert reference == {
        "mode": "follow_up",
        "report_id": report.id,
        "version_id": version.id,
        "version_ordinal": 1,
        "title": "Reference report",
        "kind": "table",
        "source_artifact_id": artifact.id,
    }
    assert (
        await chat_reports.verified_report_reference(
            db_session,
            org_id="org-a",
            user_id="user-b",
            conversation_id=artifact.conversation_id,
            report_id=report.id,
            version_id=version.id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_object_backed_report_version_download_keeps_exact_bytes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_project(db_session)
    artifact = await _artifact(db_session, artifact_id="artifact-object")
    content = b"\xef\xbb\xbfrevenue\n999\n"
    artifact.storage_kind = "object"
    artifact.object_key = "chat/artifacts/artifact-object/revenue.csv"
    artifact.binary_data = None
    artifact.byte_size = len(content)
    artifact.content_hash = hashlib.sha256(content).hexdigest()
    await db_session.commit()

    class FakeStorage:
        async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
            assert key == artifact.object_key
            assert max_bytes == 10 * 1024 * 1024
            return content

    monkeypatch.setattr(chat_reports, "chat_object_storage", lambda: FakeStorage())
    _, report, version = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=artifact.id,
        title="Object report",
    )
    downloadable = await chat_reports.authorized_version_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        version_id=version.id,
    )
    assert downloadable is not None
    assert await chat_reports.artifact_download_bytes(downloadable) == content
    assert report.current_version_id == version.id


@pytest.mark.asyncio
async def test_artifact_persistence_records_server_owned_report_lineage(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_project(db_session)
    seeded = await _artifact(db_session, artifact_id="artifact-lineage-seed")
    run = await db_session.get(GatewayChatRun, seeded.run_id)
    assert run is not None
    observed_schema = {
        "analytics.revenue": {
            "columns": [{"name": "amount", "type": "numeric", "nullable": False, "primary_key": False}]
        }
    }
    monkeypatch.setattr(chat_store.schema_cache, "get", lambda _connection: observed_schema)

    artifact = await chat_store.persist_artifact(
        db_session,
        run=run,
        payload={
            "kind": "table",
            "filename": "lineage.csv",
            "mime_type": "text/csv",
            "snapshot": {
                "columns": [{"name": "amount"}],
                "rows": [{"amount": 10}],
            },
            "provenance": {
                "commit_sha": "agent-controlled",
                "schema_fingerprint": "agent-controlled",
            },
        },
    )

    assert artifact.provenance_json is not None
    assert artifact.provenance_json["commit_sha"] == "a" * 40
    assert artifact.provenance_json["schema_fingerprint"] == _schema_fingerprint(observed_schema)


@pytest.mark.parametrize(
    ("auth", "claims"),
    [
        ({"auth_method": "api_key"}, {}),
        ({"auth_method": "notebook_session"}, {}),
        ({}, {"execution_identity": "agent"}),
    ],
)
def test_report_mutations_reject_non_browser_principals(auth: dict, claims: dict) -> None:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.auth = auth
    request.state._jwt_claims = claims
    with pytest.raises(HTTPException) as rejected:
        _require_browser_principal(request)
    assert rejected.value.status_code == 403


def test_report_share_tokens_are_redacted_from_application_and_access_logs() -> None:
    secret = "secret-fixed-version-token"
    path = f"/api/chat/shared-reports/{secret}?download=1"
    assert redact_secret_path(path) == "/api/chat/shared-reports/[redacted]?download=1"

    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1", "GET", path, "1.1", 200),
        exc_info=None,
    )
    assert SecretPathLogFilter().filter(record)
    assert secret not in record.getMessage()
    assert "/api/chat/shared-reports/[redacted]?download=1" in record.getMessage()

    library_path = "/api/chat/library?search=Confidential%20Board%20Report&kind=table"
    assert redact_secret_path(library_path) == "/api/chat/library?[redacted]"


@pytest.mark.asyncio
async def test_postgres_concurrent_promotions_converge_on_one_report(db_session: AsyncSession) -> None:
    database_url = os.getenv("CHAT_REPORTS_TEST_DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL concurrency contract")
    await _seed_project(db_session)
    artifact = await _artifact(db_session, artifact_id="artifact-concurrent-save", value=700)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    async with factory() as first, factory() as second:
        results = await asyncio.gather(
            chat_reports.promote_artifact(
                first,
                org_id="org-a",
                user_id="user-a",
                artifact_id=artifact.id,
                title="Concurrent revenue A",
            ),
            chat_reports.promote_artifact(
                second,
                org_id="org-a",
                user_id="user-a",
                artifact_id=artifact.id,
                title="Concurrent revenue B",
            ),
        )

    assert {status for status, _report, _version in results} == {"created", "existing"}
    assert len({report.id for _status, report, _version in results}) == 1
    assert len({version.id for _status, _report, version in results}) == 1


@pytest.mark.asyncio
async def test_postgres_concurrent_updates_create_one_version_and_one_conflict(db_session: AsyncSession) -> None:
    database_url = os.getenv("CHAT_REPORTS_TEST_DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL concurrency contract")
    await _seed_project(db_session)
    base = await _artifact(db_session, artifact_id="artifact-concurrent-base", value=100)
    _, report, version_one = await chat_reports.promote_artifact(
        db_session,
        org_id="org-a",
        user_id="user-a",
        artifact_id=base.id,
        title="Concurrent update report",
    )
    first_candidate = await _artifact(db_session, artifact_id="artifact-concurrent-first", value=200)
    second_candidate = await _artifact(db_session, artifact_id="artifact-concurrent-second", value=300)
    await _refresh_candidate(
        db_session,
        report_id=report.id,
        base_version_id=version_one.id,
        artifact=first_candidate,
    )
    await _refresh_candidate(
        db_session,
        report_id=report.id,
        base_version_id=version_one.id,
        artifact=second_candidate,
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    async with factory() as first, factory() as second:
        results = await asyncio.gather(
            chat_reports.publish_version(
                first,
                org_id="org-a",
                user_id="user-a",
                report_id=report.id,
                artifact_id=first_candidate.id,
                expected_current_version_id=version_one.id,
            ),
            chat_reports.publish_version(
                second,
                org_id="org-a",
                user_id="user-a",
                report_id=report.id,
                artifact_id=second_candidate.id,
                expected_current_version_id=version_one.id,
            ),
            return_exceptions=True,
        )

    created = [result for result in results if isinstance(result, tuple)]
    conflicts = [result for result in results if isinstance(result, chat_reports.ReportConflictError)]
    assert len(created) == 1
    assert created[0][0] == "created"
    assert len(conflicts) == 1
    assert conflicts[0].actual_current_version_id == created[0][2].id

    versions = list(
        (
            await db_session.execute(
                select(GatewaySavedReportVersion)
                .where(GatewaySavedReportVersion.report_id == report.id)
                .order_by(GatewaySavedReportVersion.ordinal)
            )
        ).scalars()
    )
    assert [version.ordinal for version in versions] == [1, 2]
