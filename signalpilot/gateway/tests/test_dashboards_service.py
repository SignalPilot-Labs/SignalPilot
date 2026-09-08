"""Publish, versions, settings, restore, share tokens, and the edit message."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from gateway.dashboards import service, store
from gateway.dashboards.serializers import RefreshSettingsIn, UpdateDashboardRequest
from tests.dashboards_support import (
    MONTHLY_CSV,
    ORG,
    OTHER_USER,
    USER,
    db,
    fake_manifest,
    fake_storage,
    publish_body,
    session_factory,
    spec_json,
)


async def _publish(db, storage, rows, **overrides):
    return await service.publish(
        db,
        storage,
        org_id=ORG,
        user_id=USER,
        is_admin=False,
        conversation_id="conv-1",
        file_row=rows[0],
        manifest=rows,
        body=publish_body(**overrides),
        project_id="project-a",
    )


class TestPublish:
    async def test_happy_path_creates_dashboard_and_version_one(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        dashboard, version = await _publish(db, storage, rows)

        assert dashboard.slug == "revenue"
        assert dashboard.current_version_id == version.id
        assert version.version_no == 1
        assert version.produced_by == "publish"
        assert version.producer_ref == USER
        assert dashboard.chart_count == 3
        assert dashboard.source_conversation_id == "conv-1"
        assert dashboard.source_file_id == "file-dash"
        assert dashboard.next_refresh_at is not None
        assert set(version.dataset_keys) == {"monthly", "regions"}
        assert version.dataset_meta["monthly"] == {"row_count": 2, "byte_size": len(MONTHLY_CSV), "filename": "monthly.csv"}
        assert version.dataset_meta["regions"]["row_count"] == 2
        assert version.spec_key.endswith(f"/dashboards/{dashboard.id}/versions/{version.id}/spec.json")
        assert version.dataset_keys["monthly"].endswith("/datasets/monthly.csv")
        assert json.loads(backend.objects[version.spec_key])["title"] == "Revenue"
        assert backend.objects[version.dataset_keys["regions"]] == backend.objects["chat/artifacts/regions.csv"]

    async def test_missing_dataset_file_is_422_with_names(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        rows = [row for row in rows if not row.path.endswith("regions.csv")]
        with pytest.raises(service.DashboardError) as excinfo:
            await _publish(db, storage, rows)
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["missing_datasets"] == ["regions"]

    async def test_invalid_spec_is_422(self, db) -> None:
        storage, backend = fake_storage()
        spec = spec_json()
        spec["charts"] = []
        rows = fake_manifest(backend, spec)
        with pytest.raises(service.DashboardError) as excinfo:
            await _publish(db, storage, rows)
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["errors"]

    async def test_non_dashboard_file_is_422(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        with pytest.raises(service.DashboardError) as excinfo:
            await service.publish(
                db, storage, org_id=ORG, user_id=USER, is_admin=False, conversation_id="c",
                file_row=rows[1], manifest=rows, body=publish_body(), project_id=None,
            )
        assert excinfo.value.status_code == 422

    async def test_slug_is_deduplicated(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        first, _ = await _publish(db, storage, rows)
        second, _ = await _publish(db, storage, rows)
        third, _ = await _publish(db, storage, rows, slug="revenue")
        assert (first.slug, second.slug, third.slug) == ("revenue", "revenue-2", "revenue-3")

    async def test_slug_from_messy_name(self, db) -> None:
        assert store.slugify("  Q3 Revenue -- EMEA!  ") == "q3-revenue-emea"
        assert store.slugify("???") == "dashboard"
        assert len(store.slugify("x" * 100)) == 64

    async def test_update_existing_adds_version_and_settings(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        dashboard, v1 = await _publish(db, storage, rows)
        updated, v2 = await _publish(
            db, storage, rows,
            name="Revenue v2", target_dashboard_id=dashboard.id, visibility="link",
            refresh=RefreshSettingsIn(interval_minutes=None, timezone="UTC", mode="agent"),
        )
        assert updated.id == dashboard.id
        assert updated.name == "Revenue v2"
        assert updated.slug == "revenue"
        assert v2.version_no == 2
        assert updated.current_version_id == v2.id
        assert updated.visibility == "link"
        assert updated.share_token and len(updated.share_token) == 32
        assert updated.refresh_interval_minutes is None
        assert updated.next_refresh_at is None
        assert updated.refresh_mode == "agent"

    async def test_update_existing_follows_the_new_source(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        dashboard, _ = await _publish(db, storage, rows)
        second_rows = fake_manifest(backend, run_id="run-2")
        second_rows[0].id = "file-dash-2"
        updated, _ = await service.publish(
            db, storage, org_id=ORG, user_id=USER, is_admin=False, conversation_id="conv-2",
            file_row=second_rows[0], manifest=second_rows,
            body=publish_body(target_dashboard_id=dashboard.id), project_id="project-b",
        )
        assert updated.id == dashboard.id
        assert (updated.project_id, updated.source_conversation_id, updated.source_file_id) == ("project-b", "conv-2", "file-dash-2")

    async def test_update_existing_rejects_archived_target(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        dashboard, v1 = await _publish(db, storage, rows)
        await service.set_archived(db, dashboard, True)
        with pytest.raises(service.DashboardError) as excinfo:
            await _publish(db, storage, rows, target_dashboard_id=dashboard.id)
        assert excinfo.value.status_code == 409
        assert dashboard.current_version_id == v1.id
        assert len(await store.list_versions(db, dashboard.id)) == 1

    async def test_update_existing_requires_edit_rights(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        dashboard, _ = await _publish(db, storage, rows)
        with pytest.raises(service.DashboardError) as excinfo:
            await service.publish(
                db, storage, org_id=ORG, user_id=OTHER_USER, is_admin=False, conversation_id="c",
                file_row=rows[0], manifest=rows, body=publish_body(target_dashboard_id=dashboard.id), project_id=None,
            )
        assert excinfo.value.status_code == 403


class TestLifecycle:
    async def test_restore_points_at_old_objects(self, db) -> None:
        storage, backend = fake_storage()
        rows = fake_manifest(backend)
        dashboard, v1 = await _publish(db, storage, rows)
        _, v2 = await _publish(db, storage, rows, target_dashboard_id=dashboard.id)
        restored = await service.restore_version(db, storage, dashboard, v1, user_id=USER)
        assert restored.version_no == 3
        assert restored.produced_by == "restore"
        assert restored.dataset_keys == v1.dataset_keys
        assert restored.spec_key != v1.spec_key
        assert dashboard.current_version_id == restored.id
        assert [v.version_no for v in await store.list_versions(db, dashboard.id)] == [3, 2, 1]

    async def test_update_settings_recomputes_schedule_and_mints_token(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _publish(db, storage, fake_manifest(backend))
        before = dashboard.next_refresh_at
        await service.update_settings(
            db,
            dashboard,
            UpdateDashboardRequest(
                visibility="link",
                description="  ",
                refresh=RefreshSettingsIn(interval_minutes=60, anchor_time="06:30", timezone="Europe/Berlin", mode="sql"),
            ),
        )
        assert dashboard.share_token is not None
        assert dashboard.description is None
        assert dashboard.refresh_timezone == "Europe/Berlin"
        assert dashboard.next_refresh_at != before
        assert dashboard.next_refresh_at.minute == 30
        token = dashboard.share_token
        await service.update_settings(db, dashboard, UpdateDashboardRequest(visibility="org"))
        assert dashboard.share_token == token  # stable once minted

    async def test_archive_pauses_and_unarchive_reschedules(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _publish(db, storage, fake_manifest(backend))
        await service.set_archived(db, dashboard, True)
        assert dashboard.archived_at is not None
        assert await store.list_due_dashboards(db, datetime(2100, 1, 1, tzinfo=UTC)) == []
        await service.set_archived(db, dashboard, False)
        assert dashboard.archived_at is None
        assert dashboard.next_refresh_at is not None

    async def test_delete_removes_rows_and_objects(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, version = await _publish(db, storage, fake_manifest(backend))
        await service.delete(db, storage, dashboard)
        assert await store.get_dashboard(db, org_id=ORG, id_or_slug="revenue") is None
        assert not any(key.startswith("organizations/") and "/dashboards/" in key for key in backend.objects)

    async def test_visibility_and_edit_rules(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _publish(db, storage, fake_manifest(backend), visibility="private")
        assert store.is_visible(dashboard, USER)
        assert not store.is_visible(dashboard, OTHER_USER)
        assert store.can_edit(dashboard, OTHER_USER, is_admin=True)
        assert not store.can_edit(dashboard, OTHER_USER, is_admin=False)
        assert await store.list_dashboards(db, org_id=ORG, user_id=OTHER_USER, include_archived=False) == []

    async def test_bundle_datasets_include_inline_rows(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, version = await _publish(db, storage, fake_manifest(backend))
        spec = await storage.get_spec(version.spec_key)
        datasets = await service.load_bundle_datasets(storage, spec, version)
        assert datasets["inline"] == [{"k": "a", "v": 1}]
        assert datasets["monthly"][0] == {"month": "2026-01-01", "revenue": 100}
        assert datasets["regions"][1] == {"region": "south", "total": None}


class TestEditMessage:
    async def test_message_inlines_spec_and_datasets_under_cap(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _publish(db, storage, fake_manifest(backend))
        big = b"a,b\n" + b"1,2\n" * 60_000
        message = service.edit_message(
            dashboard, spec_json(), {"monthly": ("artifacts/monthly.csv", b"month,revenue\n2026-01-01,1\n"), "big": ("artifacts/big.csv", big)}
        )
        assert message.startswith('Edit the dashboard "Revenue".')
        assert "artifacts/revenue.dashboard.json" in message
        assert "```json" in message and '"title": "Revenue"' in message
        assert "Dataset `monthly` at `artifacts/monthly.csv`" in message
        assert "big (artifacts/big.csv)" in message
        assert len(message.encode()) < service.EDIT_MESSAGE_CAP_BYTES + 2_000
        assert "—" not in message
