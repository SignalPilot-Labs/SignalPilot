"""SP-26: a repo linked in two orgs is attributed to the org that owns the
webhook delivery's installation, not to whichever org linked it first."""

from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api import github_bot
from gateway.config.github_bot import GitHubBotSettings
from gateway.db.models import GatewayBase, GatewayGitHubInstallation, GatewayGitHubRepoLink
from gateway.store import github as gh_store

REPO = "acme/dbt"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed(db: AsyncSession, *, org: str, gh_install: int, created_at: float, inst_id: str | None = None):
    inst = GatewayGitHubInstallation(
        id=inst_id or f"inst-{org}-{gh_install}",
        org_id=org,
        github_installation_id=gh_install,
        github_account_login="acme",
        github_account_type="Organization",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(inst)
    link = GatewayGitHubRepoLink(
        id=f"link-{org}-{created_at}",
        org_id=org,
        project_id=f"proj-{org}-{created_at}",
        installation_id=inst.id,
        repo_full_name=REPO,
        repo_id=42,
        default_branch="main",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(link)
    await db.commit()
    return inst, link


@pytest.mark.asyncio
async def test_installation_id_selects_the_owning_org(db: AsyncSession) -> None:
    await _seed(db, org="org-first", gh_install=111, created_at=1.0)
    await _seed(db, org="org-second", gh_install=222, created_at=2.0)

    assert await gh_store.get_org_for_repo(db, repo_full_name=REPO, installation_id=222) == "org-second"
    assert await gh_store.get_org_for_repo(db, repo_full_name=REPO, installation_id=111) == "org-first"


@pytest.mark.asyncio
async def test_without_installation_id_oldest_link_wins_as_before(db: AsyncSession) -> None:
    await _seed(db, org="org-first", gh_install=111, created_at=1.0)
    await _seed(db, org="org-second", gh_install=222, created_at=2.0)
    assert await gh_store.get_org_for_repo(db, repo_full_name=REPO) == "org-first"
    # Unknown installation: no scoped match, deterministic fallback.
    assert await gh_store.get_org_for_repo(db, repo_full_name=REPO, installation_id=999) == "org-first"


@pytest.mark.asyncio
async def test_links_sharing_an_installation_keep_oldest_first(db: AsyncSession) -> None:
    inst, _ = await _seed(db, org="org-a", gh_install=111, created_at=1.0)
    # Second project in the same org linked to the same repo via the same installation row.
    db.add(
        GatewayGitHubRepoLink(
            id="link-newer", org_id="org-a", project_id="proj-newer", installation_id=inst.id,
            repo_full_name=REPO, repo_id=42, default_branch="main", status="active",
            created_at=5.0, updated_at=5.0,
        )
    )
    await db.commit()
    link = await gh_store._resolve_repo_link(db, REPO, 111)
    assert link is not None and link.project_id == "proj-org-a-1.0"


@pytest.mark.asyncio
async def test_token_lookup_uses_the_delivering_installation(db: AsyncSession, monkeypatch) -> None:
    await _seed(db, org="org-first", gh_install=111, created_at=1.0)
    await _seed(db, org="org-second", gh_install=222, created_at=2.0)
    monkeypatch.setattr(gh_store, "get_valid_token", AsyncMock(side_effect=lambda _s, inst: f"tok-{inst.org_id}"))
    assert await gh_store.get_token_for_repo(db, repo_full_name=REPO, installation_id=222) == "tok-org-second"
    assert await gh_store.get_token_for_repo(db, repo_full_name=REPO) == "tok-org-first"


@pytest.mark.asyncio
async def test_bot_token_prefers_the_attributed_org(db: AsyncSession, monkeypatch) -> None:
    import gateway.db.engine as engine_mod
    from gateway.github_bot import client as bot_client

    await _seed(db, org="org-first", gh_install=111, created_at=1.0)
    await _seed(db, org="org-second", gh_install=222, created_at=2.0)
    monkeypatch.setattr(gh_store, "get_valid_token", AsyncMock(side_effect=lambda _s, inst: f"tok-{inst.org_id}"))

    @asynccontextmanager
    async def _session():
        yield db

    monkeypatch.setattr(engine_mod, "get_session_factory", lambda: _session)
    assert await bot_client.resolve_bot_token(REPO, org_id="org-second") == "tok-org-second"
    assert await bot_client.resolve_bot_token(REPO) == "tok-org-first"


# ── Webhook route passes the delivery's installation id through ──────────────


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_forwards_installation_id_and_schedules_for_that_org(monkeypatch) -> None:
    import gateway.db.engine as engine_mod

    app = FastAPI()
    app.include_router(github_bot.router)
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setattr(github_bot, "get_github_bot_settings", lambda: GitHubBotSettings(SP_GITHUB_WEBHOOK_SECRET="s3cret"))
    scheduled: list[tuple] = []
    monkeypatch.setattr(github_bot, "schedule_scan", lambda *a: scheduled.append(a))
    monkeypatch.setattr(github_bot, "_log_trigger_errors", AsyncMock())

    @asynccontextmanager
    async def _session():
        yield object()

    monkeypatch.setattr(engine_mod, "get_session_factory", lambda: _session)
    seen: dict = {}

    async def _fake_org(session, *, repo_full_name, installation_id=None):
        seen.update(repo=repo_full_name, installation_id=installation_id)
        return "org-second" if installation_id == 222 else "org-first"

    monkeypatch.setattr(gh_store, "get_org_for_repo", _fake_org)

    body = json.dumps(
        {
            "action": "opened",
            "installation": {"id": 222},
            "repository": {"full_name": REPO},
            "pull_request": {"number": 7, "head": {"ref": "feature"}},
        }
    ).encode()
    with TestClient(app) as client:
        resp = client.post(
            "/api/github/webhook",
            content=body,
            headers={"x-github-event": "pull_request", "x-hub-signature-256": _sign("s3cret", body)},
        )
    assert resp.status_code == 200, resp.text
    assert seen == {"repo": REPO, "installation_id": 222}
    assert scheduled == [("org-second", REPO, 7)]
