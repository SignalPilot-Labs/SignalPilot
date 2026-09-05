"""Focused policy contracts for Getting Started and Demo Teams."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.demo import (
    Demo,
    DemoBootstrapCreate,
    DemoBootstrapResponse,
    _require_bootstrap_catalog_entry,
    _seed_demo_replay,
    authorize_demo_replay,
    cleanup_demo_team,
)
from gateway.db.models import (
    GatewayBase,
    GatewayChatMessage,
    GatewayChatRunEvent,
    GatewayConnection,
    GatewayWorkspaceProject,
)
from gateway.governance.plan_limits import PLAN_TIERS, check_feature
from gateway.standalone_chat.demo_limits import demo_request_usage, enforce_demo_request_limit
from gateway.store import standalone_chat as chat_store
from gateway.store.store import Store


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_free_tier_splits_projects_from_notebook_sessions() -> None:
    free = PLAN_TIERS["free"]
    assert free.projects is True
    assert free.notebook_sessions is False
    assert free.users == 2
    check_feature("projects", free)
    with pytest.raises(HTTPException) as exc:
        check_feature("notebook_sessions", free)
    assert exc.value.status_code == 403


def test_demo_bootstrap_only_accepts_the_allowlisted_catalog_slug() -> None:
    assert DemoBootstrapCreate(catalog_slug="parallax").catalog_slug == "parallax"
    with pytest.raises(ValueError):
        DemoBootstrapCreate(catalog_slug="anything-else")
    with pytest.raises(ValueError):
        DemoBootstrapCreate.model_validate({"catalog_slug": "parallax", "repo_url": "https://example.com"})


def test_bootstrap_catalog_pins_the_xata_project_and_public_repository() -> None:
    _require_bootstrap_catalog_entry(Demo(
        slug="parallax",
        project="prj_7r8eolv5c15q12os2k0m3lt408",
        title="Parallax",
        repo_url="https://github.com/kiwi0401/parallax-demo",
    ))
    with pytest.raises(HTTPException):
        _require_bootstrap_catalog_entry(Demo(
            slug="parallax",
            project="prj_untrusted",
            title="Parallax",
            repo_url="https://github.com/kiwi0401/parallax-demo",
        ))


def test_demo_bootstrap_response_never_has_credentials() -> None:
    payload = DemoBootstrapResponse(status="ready", phase="opening", created=False).model_dump()
    assert "xata_key" not in payload
    assert "credentials" not in payload


@pytest.mark.asyncio
async def test_demo_limit_counts_runs_but_not_seeded_replay(db_session: AsyncSession) -> None:
    project = GatewayWorkspaceProject(
        id="project-demo",
        org_id="org-demo",
        name="parallax-demo",
        display_name="Demo project",
        description="",
        connection_name="parallax-demo",
        source="github",
        status="active",
        settings={},
        tags=["sp-demo", "journey:demo-v1"],
        file_count=1,
        total_bytes=1,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db_session.add_all([
        project,
        GatewayConnection(
            org_id="org-demo",
            user_id="user-demo",
            name="parallax-demo",
            db_type="xata",
            status="connected",
            created_at=1.0,
            description="",
            tags=["sp-demo", "demo:parallax"],
            schema_filter_include=[],
            schema_filter_exclude=[],
        ),
    ])
    await db_session.commit()

    replay, _ = await chat_store.create_conversation_with_run(
        db_session,
        org_id="org-demo",
        user_id="user-demo",
        project=project,
        branch="main",
        message="seed",
        commit_sha="a" * 40,
        origin="demo_replay",
    )
    assert replay.origin == "demo_replay"
    for index in range(5):
        await chat_store.create_conversation_with_run(
            db_session,
            org_id="org-demo",
            user_id="user-demo",
            project=project,
            branch="main",
            message=f"live request {index}",
            commit_sha="b" * 40,
        )

    assert await demo_request_usage(db_session, org_id="org-demo") == (5, 5)
    with pytest.raises(HTTPException) as exc:
        await enforce_demo_request_limit(db_session, org_id="org-demo")
    assert exc.value.status_code == 429
    assert exc.value.detail == {"code": "demo_request_limit", "limit": 5, "used": 5}


@pytest.mark.asyncio
async def test_non_demo_teams_have_no_demo_allowance(db_session: AsyncSession) -> None:
    assert await demo_request_usage(db_session, org_id="org-production") is None
    await enforce_demo_request_limit(db_session, org_id="org-production")


@pytest.mark.asyncio
async def test_seeded_replay_is_versioned_idempotent_and_authorized(db_session: AsyncSession) -> None:
    project = GatewayWorkspaceProject(
        id="project-replay",
        org_id="org-demo",
        name="parallax-demo",
        display_name="Demo project",
        description="",
        source="github",
        status="active",
        settings={},
        tags=["sp-demo"],
        file_count=1,
        total_bytes=1,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db_session.add(project)
    await db_session.commit()
    store = Store(db_session, org_id="org-demo", user_id="user-demo")

    first = await _seed_demo_replay(store, project)
    assert await _seed_demo_replay(store, project) == first
    marker = (
        await db_session.execute(
            select(GatewayChatMessage).where(GatewayChatMessage.content.like("Identify the experiments%"))
        )
    ).scalar_one()
    assert marker.metadata_json == {
        "surface": "standalone",
        "demo_replay": True,
        "fixture_version": "experiments-v1",
    }
    events = list((await db_session.execute(select(GatewayChatRunEvent).order_by(GatewayChatRunEvent.sequence))).scalars())
    assert next(event for event in events if event.event_type == "text_delta").payload_json["delta"]
    assert await authorize_demo_replay(first[0], first[1], store) == {
        "authorized": True,
        "fixture_version": "experiments-v1",
    }
    with pytest.raises(HTTPException) as exc:
        await authorize_demo_replay(first[0], "wrong-run", store)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_demo_team_cleanup_orders_project_branch_then_connection(monkeypatch) -> None:
    calls: list[str] = []
    connection = SimpleNamespace(name="parallax-demo", tags=["sp-demo"])
    project = SimpleNamespace(id="project-demo", tags=["sp-demo"])
    result = SimpleNamespace(scalars=lambda: [project])
    store = SimpleNamespace(
        list_connections=AsyncMock(return_value=[connection]),
        session=SimpleNamespace(execute=AsyncMock(return_value=result)),
        _require_org_id=lambda: "org-demo",
        delete_workspace_project=AsyncMock(side_effect=lambda _id: calls.append("project") or True),
        delete_connection=AsyncMock(side_effect=lambda _name: calls.append("connection") or True),
    )

    async def delete_branch(_store, _name):
        calls.append("branch")

    monkeypatch.setattr("gateway.api.demo._delete_demo_branch_strict", delete_branch)
    assert await cleanup_demo_team(store, None) == {"demo": True, "cleaned": True}
    assert calls == ["project", "branch", "connection"]
