"""Dashboard routes: auth, visibility, 409 on double refresh, share token, serializer shape."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from gateway.api import dashboards as routes
from gateway.api.chat_routes import publish_dashboard as publish_routes
from gateway.dashboards import service
from gateway.dashboards.serializers import (
    DashboardRefreshOut,
    DashboardVersionOut,
    PublishedDashboardOut,
    UpdateDashboardRequest,
)
from tests.dashboards_support import (
    ORG,
    OTHER_USER,
    USER,
    add_conversation_with_files,
    api_store,
    db,
    fake_manifest,
    fake_storage,
    publish_body,
    session_factory,
)

TS_CONTRACT = Path(__file__).parents[3] / "signalpilot/web/lib/api/dashboards.ts"


@pytest.fixture
def storage(monkeypatch):
    storage, backend = fake_storage()
    monkeypatch.setattr(routes, "storage", lambda: storage)
    monkeypatch.setattr(publish_routes, "dashboard_storage", lambda: storage)
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "1")
    return storage, backend


@pytest.fixture
def launched(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(routes, "launch_refresh", calls.append)
    return calls


async def _publish_via_route(db, backend, **overrides):
    conversation, _run, rows = await add_conversation_with_files(db, backend)
    return await publish_routes.publish_dashboard(
        conversation.id, "file-dash", publish_body(**overrides), api_store(db), "basic_member"
    )


class TestPublishRoute:
    async def test_publish_returns_201_shape(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend)
        dashboard = result["dashboard"]
        assert dashboard.slug == "revenue" and dashboard.can_edit and dashboard.current_version_no == 1
        assert dashboard.project_id == "project-a"
        assert result["version"].version_no == 1

    async def test_publish_unknown_file_is_404(self, db, storage) -> None:
        _, backend = storage
        conversation, _run, _rows = await add_conversation_with_files(db, backend)
        with pytest.raises(HTTPException) as excinfo:
            await publish_routes.publish_dashboard(conversation.id, "nope", publish_body(), api_store(db), "basic_member")
        assert excinfo.value.status_code == 404

    async def test_publish_other_users_conversation_is_404(self, db, storage) -> None:
        _, backend = storage
        conversation, _run, _rows = await add_conversation_with_files(db, backend)
        with pytest.raises(HTTPException) as excinfo:
            await publish_routes.publish_dashboard(
                conversation.id, "file-dash", publish_body(), api_store(db, OTHER_USER), "basic_member"
            )
        assert excinfo.value.status_code == 404

    async def test_publish_service_error_maps_to_422(self, db, storage) -> None:
        _, backend = storage
        conversation, _run, rows = await add_conversation_with_files(db, backend)
        from gateway.store import standalone_chat as chat_store

        await chat_store.mark_conversation_file_deleted(
            db, org_id=ORG, user_id=USER, conversation_id=conversation.id, path="artifacts/regions.csv"
        )
        with pytest.raises(HTTPException) as excinfo:
            await publish_routes.publish_dashboard(conversation.id, "file-dash", publish_body(), api_store(db), "basic_member")
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["missing_datasets"] == ["regions"]


class TestVisibility:
    async def test_private_dashboard_hidden_from_others_and_listed_for_owner(self, db, storage) -> None:
        _, backend = storage
        await _publish_via_route(db, backend, visibility="private")
        mine = await routes.list_dashboards(api_store(db), "basic_member", include_archived=False)
        theirs = await routes.list_dashboards(api_store(db, OTHER_USER), "basic_member", include_archived=False)
        assert len(mine["dashboards"]) == 1 and theirs["dashboards"] == []
        with pytest.raises(HTTPException) as excinfo:
            await routes.get_dashboard("revenue", api_store(db, OTHER_USER), "basic_member")
        assert excinfo.value.status_code == 404

    async def test_org_dashboard_visible_but_not_editable_by_member(self, db, storage) -> None:
        _, backend = storage
        await _publish_via_route(db, backend, visibility="org")
        detail = await routes.get_dashboard("revenue", api_store(db, OTHER_USER), "basic_member")
        assert detail["dashboard"].can_edit is False
        assert detail["dashboard"].share_token is None
        assert len(detail["versions"]) == 1 and detail["refreshes"] == []
        with pytest.raises(HTTPException) as excinfo:
            await routes.update_dashboard(
                detail["dashboard"].id, UpdateDashboardRequest(name="x"), api_store(db, OTHER_USER), "basic_member"
            )
        assert excinfo.value.status_code == 403

    async def test_admin_can_edit(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend, visibility="org")
        updated = await routes.update_dashboard(
            result["dashboard"].id, UpdateDashboardRequest(name="Renamed"), api_store(db, OTHER_USER), "org:admin"
        )
        assert updated["dashboard"].name == "Renamed" and updated["dashboard"].can_edit

    async def test_archived_hidden_unless_requested(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend)
        await routes.archive_dashboard(result["dashboard"].id, api_store(db), "basic_member")
        assert (await routes.list_dashboards(api_store(db), "basic_member", include_archived=False))["dashboards"] == []
        listed = await routes.list_dashboards(api_store(db), "basic_member", include_archived=True)
        assert listed["dashboards"][0].archived_at is not None
        await routes.unarchive_dashboard(result["dashboard"].id, api_store(db), "basic_member")
        assert len((await routes.list_dashboards(api_store(db), "basic_member", include_archived=False))["dashboards"]) == 1


class TestRefreshRoutes:
    async def test_manual_refresh_is_202_then_409(self, db, storage, launched) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend)
        dashboard_id = result["dashboard"].id
        first = await routes.refresh_now(dashboard_id, api_store(db), "basic_member")
        assert first["refresh"].status == "queued" and first["refresh"].trigger == "manual"
        assert launched == [first["refresh"].id]
        with pytest.raises(HTTPException) as excinfo:
            await routes.refresh_now(dashboard_id, api_store(db), "basic_member")
        assert excinfo.value.status_code == 409
        listed = await routes.list_refreshes(dashboard_id, api_store(db), limit=20)
        assert [r.id for r in listed["refreshes"]] == [first["refresh"].id]

    async def test_refresh_on_archived_is_409(self, db, storage, launched) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend)
        await routes.archive_dashboard(result["dashboard"].id, api_store(db), "basic_member")
        with pytest.raises(HTTPException) as excinfo:
            await routes.refresh_now(result["dashboard"].id, api_store(db), "basic_member")
        assert excinfo.value.status_code == 409

    async def test_restore_and_bundle(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend)
        dashboard_id, v1 = result["dashboard"].id, result["version"].id
        restored = await routes.restore_version(dashboard_id, v1, api_store(db), "basic_member")
        assert restored["version"].version_no == 2 and restored["dashboard"].current_version_no == 2
        bundle = await routes.get_bundle(dashboard_id, restored["version"].id, api_store(db), "basic_member")
        assert bundle["spec"]["title"] == "Revenue"
        assert set(bundle["datasets"]) == {"monthly", "regions", "inline"}
        assert bundle["datasets"]["monthly"][1] == {"month": "2026-02-01", "revenue": 120}

    async def test_dataset_download(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend)
        response = await routes.download_dataset(result["dashboard"].id, result["version"].id, "monthly", api_store(db))
        assert response.media_type == "text/csv"
        assert response.headers["content-disposition"].startswith('attachment; filename="monthly.csv"')
        assert response.body.startswith(b"month,revenue")
        with pytest.raises(HTTPException):
            await routes.download_dataset(result["dashboard"].id, result["version"].id, "inline", api_store(db))

    async def test_delete_is_owner_or_admin(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend, visibility="org")
        with pytest.raises(HTTPException) as excinfo:
            await routes.delete_dashboard(result["dashboard"].id, api_store(db, OTHER_USER), "basic_member")
        assert excinfo.value.status_code == 403
        response = await routes.delete_dashboard(result["dashboard"].id, api_store(db), "basic_member")
        assert response.status_code == 204
        with pytest.raises(HTTPException):
            await routes.get_dashboard(result["dashboard"].id, api_store(db), "basic_member")


class TestSharedRoute:
    async def test_shared_bundle_by_token(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend, visibility="link")
        token = result["dashboard"].share_token
        assert token
        bundle = await routes.get_shared_dashboard(token, api_store(db, "anyone"))
        assert bundle["dashboard"].id == result["dashboard"].id
        assert bundle["spec"]["title"] == "Revenue"
        assert bundle["version"].version_no == 1

    async def test_shared_view_is_reduced(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend, visibility="link", description="Monthly revenue")
        full = result["dashboard"]
        shared = (await routes.get_shared_dashboard(full.share_token, api_store(db, "anyone")))["dashboard"]
        assert type(shared) is PublishedDashboardOut
        populated = {
            "id": full.id,
            "slug": full.slug,
            "name": "Revenue",
            "description": "Monthly revenue",
            "chart_count": 3,
            "visibility": "link",
            "current_version_id": full.current_version_id,
            "current_version_no": 1,
            "created_at": full.created_at,
            "updated_at": full.updated_at,
            "last_refresh_at": None,
            "last_refresh_status": None,
        }
        assert {key: getattr(shared, key) for key in populated} == populated
        assert shared.can_edit is False and shared.share_token is None
        assert shared.refresh.model_dump() == {"interval_minutes": None, "anchor_time": None, "timezone": "UTC", "mode": "sql"}
        assert (shared.created_by_label, shared.created_by_user_id, shared.notify_on_failure) == ("", "", False)
        assert shared.project_id is None and shared.source_conversation_id is None and shared.source_file_id is None
        assert shared.next_refresh_at is None and shared.archived_at is None

    async def test_shared_route_rejects_non_link_and_archived(self, db, storage) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend, visibility="link")
        token = result["dashboard"].share_token
        await routes.update_dashboard(result["dashboard"].id, UpdateDashboardRequest(visibility="org"), api_store(db), "basic_member")
        with pytest.raises(HTTPException) as excinfo:
            await routes.get_shared_dashboard(token, api_store(db))
        assert excinfo.value.status_code == 404
        await routes.update_dashboard(result["dashboard"].id, UpdateDashboardRequest(visibility="link"), api_store(db), "basic_member")
        await routes.archive_dashboard(result["dashboard"].id, api_store(db), "basic_member")
        with pytest.raises(HTTPException):
            await routes.get_shared_dashboard(token, api_store(db))
        with pytest.raises(HTTPException):
            await routes.get_shared_dashboard("bogus", api_store(db))


class TestEditChat:
    async def test_edit_chat_seeds_conversation(self, db, storage, monkeypatch) -> None:
        _, backend = storage
        result = await _publish_via_route(db, backend)
        from types import SimpleNamespace

        async def ready(db_, *, org_id, user_id, project, branch_override=None):
            return SimpleNamespace(ready=True, branch="main", code="ok", message="")

        monkeypatch.setattr("gateway.standalone_chat.projects.evaluate_project_readiness", ready)
        monkeypatch.setattr("gateway.git.repos.branch_head_sha", lambda project_id, branch: "b" * 40)
        response = await routes.open_edit_chat(result["dashboard"].id, api_store(db), "basic_member")
        from gateway.store import standalone_chat as chat_store

        conversation = await chat_store.get_owned_conversation(
            db, org_id=ORG, user_id=USER, conversation_id=response["conversation_id"]
        )
        assert conversation is not None and conversation.title == "Edit dashboard: Revenue"


# ── Serializer shape against the TypeScript contract ──────────────────────


def _ts_fields(type_name: str) -> set[str]:
    text = TS_CONTRACT.read_text(encoding="utf-8")
    match = re.search(rf"export type {type_name} = \{{(.*?)\n\}};", text, re.DOTALL)
    assert match, f"{type_name} not found in {TS_CONTRACT}"
    body = re.sub(r"/\*\*.*?\*/", "", match.group(1), flags=re.DOTALL)
    return set(re.findall(r"^\s*([a-z_]+)\??:", body, flags=re.MULTILINE))


@pytest.mark.skipif(not TS_CONTRACT.exists(), reason="web checkout absent")
@pytest.mark.parametrize(
    ("ts_type", "model"),
    [
        ("PublishedDashboard", PublishedDashboardOut),
        ("DashboardVersion", DashboardVersionOut),
        ("DashboardRefresh", DashboardRefreshOut),
    ],
)
def test_serializer_keys_match_ts_contract(ts_type: str, model) -> None:
    assert set(model.model_fields) == _ts_fields(ts_type)


def test_refresh_settings_keys_match_ts_contract() -> None:
    if not TS_CONTRACT.exists():
        pytest.skip("web checkout absent")
    from gateway.dashboards.serializers import RefreshSettingsOut

    assert set(RefreshSettingsOut.model_fields) == _ts_fields("DashboardRefreshSettings")


async def test_serialized_dashboard_matches_contract_end_to_end(db, storage) -> None:
    _, backend = storage
    result = await _publish_via_route(db, backend)
    payload = result["dashboard"].model_dump()
    assert payload["refresh"] == {"interval_minutes": 1440, "anchor_time": "06:00", "timezone": "UTC", "mode": "sql"}
    assert payload["created_by_label"] == USER
    assert payload["next_refresh_at"].endswith("Z")
    assert payload["last_refresh_status"] is None
    assert service.DashboardError  # the service error type is the API's only exception bridge
