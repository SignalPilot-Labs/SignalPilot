"""PUT /workspace-projects merges ``settings`` instead of replacing them.

Plan section H: a caller that sends one key (``dbt_project_dir``) must not wipe
watched branches, triggers or metadata bindings. Hermetic: moto S3 plus
aiosqlite, app composed locally per test (same seam as the detection tests,
replicated here, never imported).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase
from gateway.models.workspace import WorkspaceProjectSettings, WorkspaceProjectUpdate
from gateway.store.workspace_projects import merge_project_settings

ORG = "test-org"
BUCKET = "sp-workspace-test"


class TestMergeFunction:
    def test_absent_keys_are_kept(self):
        existing = {"watched_branches": ["main"], "auto_compile_on_push": True}
        assert merge_project_settings(existing, {"dbt_project_dir": "wh"}) == {
            "watched_branches": ["main"],
            "auto_compile_on_push": True,
            "dbt_project_dir": "wh",
        }

    def test_null_removes_a_key(self):
        existing = {"watched_branches": ["main"], "dbt_project_dir": "wh"}
        assert merge_project_settings(existing, {"dbt_project_dir": None}) == {"watched_branches": ["main"]}

    def test_null_for_missing_key_is_a_noop(self):
        assert merge_project_settings({"a": 1}, {"b": None}) == {"a": 1}

    def test_none_existing(self):
        assert merge_project_settings(None, {"a": 1}) == {"a": 1}

    def test_does_not_mutate_input(self):
        existing = {"a": 1}
        merge_project_settings(existing, {"a": 2})
        assert existing == {"a": 1}


class TestTypedSettingsModel:
    def test_patch_keeps_explicit_nulls_and_drops_unset(self):
        body = WorkspaceProjectUpdate.model_validate({"settings": {"dbt_project_dir": None, "compile_on_pr": True}})
        assert body.settings is not None
        assert body.settings.patch() == {"dbt_project_dir": None, "compile_on_pr": True}

    def test_unknown_keys_are_allowed(self):
        settings = WorkspaceProjectSettings.model_validate({"legacy_key": {"x": 1}})
        assert settings.patch() == {"legacy_key": {"x": 1}}

    def test_known_keys_are_typed(self):
        with pytest.raises(ValueError):
            WorkspaceProjectSettings.model_validate({"watched_branches": "main"})
        with pytest.raises(ValueError):
            WorkspaceProjectSettings.model_validate({"auto_compile_on_push": "sometimes"})


# ── Hermetic app ─────────────────────────────────────────────────────────────


@pytest.fixture
def storage():
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        from gateway.workspace_store.objects import WorkspaceObjectStorage

        yield WorkspaceObjectStorage(bucket=BUCKET, client=client)


def _workspace_app(storage, factory, audit_sink: list):
    from fastapi import FastAPI

    import gateway.api.workspace_files as wf
    from gateway.api.deps import require_billable_plan
    from gateway.api.workspace_files import router as files_router
    from gateway.api.workspace_projects import router as projects_router
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.db.engine import get_db
    from gateway.security.scope_guard import _resolve_user_id as scope_resolve_user_id
    from gateway.store import audit_log
    from gateway.workspace_store import WorkspaceStore

    app = FastAPI()
    app.include_router(projects_router)
    app.include_router(files_router)

    async def _get_db():
        async with factory() as session:
            yield session

    async def _user() -> str:
        return "test-user"

    async def _org() -> str:
        return ORG

    async def _no_gate() -> None:
        return None

    real_append = audit_log.append_audit

    async def _capture_audit(session, *, org_id, user_id, entry):
        audit_sink.append(entry)
        await real_append(session, org_id=org_id, user_id=user_id, entry=entry)

    audit_log.append_audit = _capture_audit  # type: ignore[assignment]

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    app.dependency_overrides[scope_resolve_user_id] = _user
    app.dependency_overrides[require_billable_plan] = _no_gate
    app.dependency_overrides[wf.get_workspace_store] = lambda: WorkspaceStore(storage)
    return app, real_append


@pytest.fixture
def api(storage):
    from fastapi.testclient import TestClient

    from gateway.store import audit_log

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)

    def _await(coro):
        # Private loop: asyncio.run() unsets the default loop, which the
        # get_event_loop()-based tests in test_security_hardening depend on.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    _await(_create_all())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    audit_sink: list = []
    app, real_append = _workspace_app(storage, factory, audit_sink)
    client = TestClient(app)
    client.audit_sink = audit_sink  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        audit_log.append_audit = real_append  # type: ignore[assignment]
        _await(engine.dispose())


def _create_project(api, settings: dict | None = None) -> str:
    payload = {"name": f"proj-{uuid.uuid4().hex[:10]}", "display_name": "Test project"}
    if settings is not None:
        payload["settings"] = settings
    response = api.post("/api/workspace-projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _put_settings(api, project: str, settings: dict) -> dict:
    response = api.put(f"/api/workspace-projects/{project}", json={"settings": settings})
    assert response.status_code == 200, response.text
    return response.json()["settings"]


class TestPutMergesSettings:
    def test_single_key_update_keeps_other_keys(self, api):
        project = _create_project(
            api,
            {"watched_branches": ["main", "dev"], "auto_compile_on_push": True, "pr_agent_trigger": False},
        )
        merged = _put_settings(api, project, {"dbt_project_dir": "warehouse"})
        assert merged == {
            "watched_branches": ["main", "dev"],
            "auto_compile_on_push": True,
            "pr_agent_trigger": False,
            "dbt_project_dir": "warehouse",
        }
        fetched = api.get(f"/api/workspace-projects/{project}").json()["settings"]
        assert fetched == merged

    def test_null_removes_key_and_keeps_the_rest(self, api):
        project = _create_project(api, {"watched_branches": ["main"], "dbt_project_dir": "wh"})
        merged = _put_settings(api, project, {"dbt_project_dir": None})
        assert merged == {"watched_branches": ["main"]}

    def test_full_payload_from_web_form_still_works(self, api):
        # components/projects/project-automation-settings.tsx sends every key it
        # owns plus the existing spread; a merge must leave that payload exact.
        project = _create_project(api, {"legacy": 1, "dbt_project_dir": "old"})
        merged = _put_settings(
            api,
            project,
            {
                "legacy": 1,
                "watched_branches": ["main"],
                "auto_compile_on_push": True,
                "compile_on_pr": False,
                "pr_agent_trigger": False,
                "dbt_project_dir": None,
            },
        )
        assert merged == {
            "legacy": 1,
            "watched_branches": ["main"],
            "auto_compile_on_push": True,
            "compile_on_pr": False,
            "pr_agent_trigger": False,
        }

    def test_unknown_keys_round_trip(self, api):
        project = _create_project(api)
        assert _put_settings(api, project, {"dbt_metadata_checksum": "abc", "custom_flag": {"x": 1}}) == {
            "dbt_metadata_checksum": "abc",
            "custom_flag": {"x": 1},
        }

    def test_typed_key_rejected_with_422(self, api):
        project = _create_project(api)
        response = api.put(f"/api/workspace-projects/{project}", json={"settings": {"watched_branches": "main"}})
        assert response.status_code == 422

    def test_other_fields_do_not_touch_settings(self, api):
        project = _create_project(api, {"watched_branches": ["main"]})
        response = api.put(f"/api/workspace-projects/{project}", json={"display_name": "Renamed"})
        assert response.status_code == 200, response.text
        assert response.json()["settings"] == {"watched_branches": ["main"]}
        assert not [e for e in api.audit_sink if e.event_type == "workspace_project_settings_update"]

    def test_settings_write_is_audited_with_key_sets(self, api):
        project = _create_project(api, {"watched_branches": ["main"], "dbt_project_dir": "old"})
        _put_settings(api, project, {"dbt_project_dir": None, "compile_on_pr": True})
        events = [e for e in api.audit_sink if e.event_type == "workspace_project_settings_update"]
        assert len(events) == 1
        metadata = events[0].metadata
        assert metadata["project_id"] == project
        assert metadata["before_keys"] == ["dbt_project_dir", "watched_branches"]
        assert metadata["after_keys"] == ["compile_on_pr", "watched_branches"]
        assert metadata["set_keys"] == ["compile_on_pr"]
        assert metadata["removed_keys"] == ["dbt_project_dir"]
        # Key names only: values never land in the audit row.
        assert "main" not in str(metadata)
