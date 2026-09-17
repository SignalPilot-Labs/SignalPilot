"""GitHub App installation model: live repository scope, webhooks, discover.

- complete_installation refuses cross-org claims (tenancy boundary).
- refresh_installation_repositories re-lists via the app and stores ids +
  names; the internal unrestricted token is never persisted.
- get_valid_token (cloud) refreshes a NULL scope instead of raising.
- installation / installation_repositories webhooks update existing rows
  and never create one.
- POST /installations/discover is admin-only; POST /{id}/refresh is write.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway import github_client
from gateway.db.models import GatewayBase, GatewayGitHubInstallation
from gateway.store import github as gh_store
from gateway.store import github_installs

GH_ID = 4242


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


class FakeGitHub:
    """Replaces the github_client coroutines used by the install flow."""

    def __init__(self, monkeypatch, *, repos: list[dict] | None = None, account: str = "acme"):
        self.repos = repos if repos is not None else [
            {"id": 1, "full_name": "acme/one"}, {"id": 2, "full_name": "acme/two"},
        ]
        self.account = account
        self.unrestricted_mints = 0
        self.scoped_mints: list[list[int]] = []
        self.list_calls = 0
        self.known: set[int] = {GH_ID}

        async def details(app_jwt, installation_id):
            if installation_id not in self.known:
                raise RuntimeError("404 Not Found")
            return {"account": {"login": self.account, "type": "Organization"}, "permissions": {"contents": "write"}}

        async def unrestricted(app_jwt, installation_id):
            self.unrestricted_mints += 1
            return {"token": "ghs_UNRESTRICTED", "expires_at": "2099-01-01T00:00:00Z"}

        async def scoped(app_jwt, installation_id, *, repository_ids):
            assert repository_ids, "scoped mint must carry repository ids"
            self.scoped_mints.append(list(repository_ids))
            return {"token": "ghs_SCOPED", "expires_at": "2099-01-01T00:00:00Z"}

        async def list_repos(token, per_page=100):
            assert token == "ghs_UNRESTRICTED"
            self.list_calls += 1
            return list(self.repos)

        monkeypatch.setattr(github_client, "get_installation_details", details)
        monkeypatch.setattr(github_client, "create_unrestricted_installation_token", unrestricted)
        monkeypatch.setattr(github_client, "create_installation_token", scoped)
        monkeypatch.setattr(github_client, "list_installation_repos", list_repos)
        monkeypatch.setattr(github_client, "generate_app_jwt", lambda app_id, key: "jwt")
        from gateway.config import github as github_config

        monkeypatch.setattr(
            github_config,
            "get_github_settings",
            lambda: SimpleNamespace(
                is_configured=True, sp_github_app_id="1", sp_github_app_private_key="pem", sp_web_url="https://app.test"
            ),
        )
        from gateway.store import crypto as store_crypto

        monkeypatch.setattr(store_crypto, "_encrypt", lambda v: b"enc:" + v.encode())
        monkeypatch.setattr(
            store_crypto, "_decrypt_with_migration", lambda blob: (blob.removeprefix(b"enc:").decode(), False)
        )


@pytest.fixture
def gh(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    return FakeGitHub(monkeypatch)


async def _row(db, org: str) -> GatewayGitHubInstallation | None:
    return (
        await db.execute(
            select(GatewayGitHubInstallation).where(
                GatewayGitHubInstallation.org_id == org, GatewayGitHubInstallation.github_installation_id == GH_ID
            )
        )
    ).scalar_one_or_none()


# complete_installation / refresh.


async def test_complete_installation_stores_scope_and_scoped_token(db, gh):
    info = await github_installs.complete_installation(db, org_id="org-a", github_installation_id=GH_ID)
    assert info.github_account_login == "acme"
    assert info.authorized_repository_count == 2
    assert info.repositories == ["acme/one", "acme/two"]
    row = await _row(db, "org-a")
    assert row.authorized_repository_ids == [1, 2]
    assert gh.scoped_mints == [[1, 2]]
    assert gh.unrestricted_mints == 1
    # The stored token is the scoped one; the unrestricted listing token is discarded.
    assert row.access_token_enc == b"enc:ghs_SCOPED"


async def test_cross_org_claim_is_rejected(db, gh):
    await github_installs.complete_installation(db, org_id="org-a", github_installation_id=GH_ID)
    with pytest.raises(github_installs.InstallationClaimedError):
        await github_installs.complete_installation(db, org_id="org-b", github_installation_id=GH_ID)
    assert await _row(db, "org-b") is None
    assert (await _row(db, "org-a")).status == "active"


async def test_same_org_reclaim_refreshes_row(db, gh):
    await github_installs.complete_installation(db, org_id="org-a", github_installation_id=GH_ID)
    gh.repos = [{"id": 1, "full_name": "acme/one"}, {"id": 3, "full_name": "acme/three"}]
    await github_installs.complete_installation(db, org_id="org-a", github_installation_id=GH_ID)
    rows = (await db.execute(select(GatewayGitHubInstallation))).scalars().all()
    assert len(rows) == 1
    assert rows[0].authorized_repository_ids == [1, 3]


async def test_unknown_installation_raises_not_found(db, gh):
    with pytest.raises(github_installs.InstallationNotFoundError):
        await github_installs.complete_installation(db, org_id="org-a", github_installation_id=999)
    assert gh.unrestricted_mints == 0


async def test_refresh_populates_ids_and_names(db, gh):
    db.add(
        GatewayGitHubInstallation(
            org_id="org-a", github_installation_id=GH_ID, github_account_login="acme",
            github_account_type="Organization", status="active", created_at=1.0, updated_at=1.0,
        )
    )
    await db.commit()
    row = await _row(db, "org-a")
    assert row.authorized_repository_ids is None
    repos = await github_installs.refresh_installation_repositories(db, row)
    assert [r["id"] for r in repos] == [1, 2]
    assert row.authorized_repository_ids == [1, 2]
    assert row.authorized_repositories == [{"id": 1, "full_name": "acme/one"}, {"id": 2, "full_name": "acme/two"}]
    # Refresh only lists; it never stores the unrestricted token.
    assert row.access_token_enc is None


async def test_refresh_invalidates_cached_token_when_scope_changes(db, gh):
    db.add(
        GatewayGitHubInstallation(
            org_id="org-a", github_installation_id=GH_ID, github_account_login="acme",
            github_account_type="Organization", status="active", authorized_repository_ids=[1],
            access_token_enc=b"enc:ghs_OLD", token_expires_at=4102444800.0, created_at=1.0, updated_at=1.0,
        )
    )
    await db.commit()
    row = await _row(db, "org-a")
    # Same set (order differs): the cached token stays valid.
    gh.repos = [{"id": 1, "full_name": "acme/one"}]
    await github_installs.refresh_installation_repositories(db, row)
    assert row.access_token_enc == b"enc:ghs_OLD"
    assert row.token_expires_at == 4102444800.0
    # A repository added on GitHub: the old token cannot reach it, so it is dropped
    # and the next get_valid_token re-mints with the new scope.
    gh.repos = [{"id": 1, "full_name": "acme/one"}, {"id": 2, "full_name": "acme/two"}]
    await github_installs.refresh_installation_repositories(db, row)
    assert row.access_token_enc is None
    assert row.token_expires_at is None
    token = await gh_store.get_valid_token(db, row)
    assert token == "ghs_SCOPED"
    assert gh.scoped_mints == [[1, 2]]
    assert row.access_token_enc == b"enc:ghs_SCOPED"


async def test_get_valid_token_refreshes_null_scope_in_cloud(db, gh):
    db.add(
        GatewayGitHubInstallation(
            org_id="org-a", github_installation_id=GH_ID, github_account_login="acme",
            github_account_type="Organization", status="active", created_at=1.0, updated_at=1.0,
        )
    )
    await db.commit()
    row = await _row(db, "org-a")
    token = await gh_store.get_valid_token(db, row)
    assert token == "ghs_SCOPED"
    assert gh.scoped_mints == [[1, 2]]
    assert row.authorized_repository_ids == [1, 2]


async def test_get_valid_token_empty_installation_raises_in_cloud(db, gh):
    gh.repos = []
    db.add(
        GatewayGitHubInstallation(
            org_id="org-a", github_installation_id=GH_ID, github_account_login="acme",
            github_account_type="Organization", status="active", created_at=1.0, updated_at=1.0,
        )
    )
    await db.commit()
    row = await _row(db, "org-a")
    with pytest.raises(ValueError):
        await gh_store.get_valid_token(db, row)
    assert gh.scoped_mints == []


# Webhooks.


async def _seed_active(db, org="org-a"):
    db.add(
        GatewayGitHubInstallation(
            org_id=org, github_installation_id=GH_ID, github_account_login="acme",
            github_account_type="Organization", status="active", authorized_repository_ids=[1],
            created_at=1.0, updated_at=1.0,
        )
    )
    await db.commit()


async def test_webhook_never_creates_rows(db, gh):
    result = await github_installs.apply_installation_webhook(
        db, event="installation", action="created", github_installation_id=GH_ID
    )
    assert result["ignored"]
    assert (await db.execute(select(GatewayGitHubInstallation))).scalars().all() == []
    assert gh.list_calls == 0


@pytest.mark.parametrize(
    ("action", "status"), [("deleted", "disconnected"), ("suspend", "suspended"), ("unsuspend", "active")]
)
async def test_webhook_installation_updates_status(db, gh, action, status):
    await _seed_active(db)
    await github_installs.apply_installation_webhook(
        db, event="installation", action=action, github_installation_id=GH_ID
    )
    assert (await _row(db, "org-a")).status == status


async def test_webhook_installation_repositories_refreshes_scope(db, gh):
    await _seed_active(db)
    gh.repos = [{"id": 1, "full_name": "acme/one"}, {"id": 9, "full_name": "acme/nine"}]
    result = await github_installs.apply_installation_webhook(
        db, event="installation_repositories", action="added", github_installation_id=GH_ID
    )
    row = await _row(db, "org-a")
    assert row.id in result["refreshed"]
    assert row.authorized_repository_ids == [1, 9]


async def test_webhook_ignores_disconnected_rows(db, gh):
    await _seed_active(db)
    (await _row(db, "org-a")).status = "disconnected"
    await db.commit()
    result = await github_installs.apply_installation_webhook(
        db, event="installation_repositories", action="added", github_installation_id=GH_ID
    )
    assert result.get("ignored")
    assert gh.list_calls == 0


def test_webhook_route_dispatches_installation_events(monkeypatch):
    from gateway.api import github_bot
    from gateway.config.github_bot import GitHubBotSettings
    from gateway.db import engine as db_engine

    monkeypatch.setattr(
        github_bot, "get_github_bot_settings", lambda: GitHubBotSettings(SP_GITHUB_WEBHOOK_SECRET="s3cret")
    )
    calls: list[dict] = []

    async def fake_apply(session, **kwargs):
        calls.append(kwargs)
        return {"updated": ["x"], "refreshed": []}

    monkeypatch.setattr(github_installs, "apply_installation_webhook", fake_apply)

    class _S:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(db_engine, "get_session_factory", lambda: _S)
    app = FastAPI()
    app.include_router(github_bot.router)
    body = json.dumps(
        {"action": "suspend", "installation": {"id": GH_ID, "permissions": {"contents": "write"}}}
    ).encode()
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    with TestClient(app) as c:
        resp = c.post(
            "/api/github/webhook", content=body,
            headers={"x-hub-signature-256": sig, "x-github-event": "installation", "content-type": "application/json"},
        )
    assert resp.status_code == 200, resp.text
    assert calls == [
        {"event": "installation", "action": "suspend", "github_installation_id": GH_ID, "permissions": {"contents": "write"}}
    ]


# REST: refresh + discover gating.

_AUTH: dict = {"auth_method": "api_key", "user_id": "u", "scopes": []}


@pytest.fixture
def api(monkeypatch):
    from gateway.api import github as github_api
    from gateway.api.deps import get_store
    from gateway.security import scope_guard

    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request: Request, call_next):
        request.state.auth = dict(_AUTH)
        return await call_next(request)

    app.include_router(github_api.router)
    app.dependency_overrides[scope_guard._resolve_user_id] = lambda: "u"
    from gateway.auth import user as auth_user

    app.dependency_overrides[auth_user.resolve_user_id] = lambda: "u"
    app.dependency_overrides[get_store] = lambda: SimpleNamespace(org_id="org-a", user_id="u", session=object())
    from gateway.config import github as github_config

    monkeypatch.setattr(github_config, "get_github_settings", lambda: SimpleNamespace(is_configured=True))
    with TestClient(app) as c:
        yield c


def _scopes(*scopes: str) -> None:
    _AUTH["scopes"] = list(scopes)


def test_discover_requires_admin_scope(api):
    _scopes("read", "write")
    assert api.post("/api/github/installations/discover?account=acme").status_code == 403


def test_discover_links_for_admin(api, monkeypatch):
    _scopes("read", "write", "admin")
    seen: list[dict] = []

    async def fake_discover(session, **kwargs):
        seen.append(kwargs)
        return []

    monkeypatch.setattr(github_installs, "discover_installations_for_account", fake_discover)
    resp = api.post("/api/github/installations/discover?account=acme")
    assert resp.status_code == 200, resp.text
    assert seen == [{"org_id": "org-a", "account_login": "acme", "created_by": "u"}]


@pytest.mark.parametrize(
    ("exc_name", "status"),
    [("InstallationClaimedError", 409), ("InstallationNotFoundError", 404), ("RepositoryListingError", 502)],
)
def test_discover_error_mapping(api, monkeypatch, exc_name, status):
    _scopes("read", "write", "admin")
    exc_type = getattr(github_installs, exc_name)

    async def fail(session, **kwargs):
        raise exc_type("x")

    monkeypatch.setattr(github_installs, "discover_installations_for_account", fail)
    assert api.post("/api/github/installations/discover?account=acme").status_code == status


def test_discover_rejects_bad_account_login(api):
    _scopes("read", "write", "admin")
    assert api.post("/api/github/installations/discover?account=../x").status_code == 422


def test_refresh_requires_write_scope(api):
    _scopes("read")
    assert api.post("/api/github/installations/inst-1/refresh").status_code == 403


def test_refresh_endpoint_refreshes_and_returns_counts(api, monkeypatch):
    _scopes("read", "write")
    row = GatewayGitHubInstallation(
        id="inst-1", org_id="org-a", github_installation_id=GH_ID, github_account_login="acme",
        github_account_type="Organization", status="active", created_at=1.0, updated_at=1.0,
    )
    monkeypatch.setattr(gh_store, "get_installation", AsyncMock(return_value=row))

    async def fake_refresh(session, r):
        r.authorized_repository_ids = [1, 2, 3]
        r.authorized_repositories = [{"id": i, "full_name": f"acme/r{i}"} for i in (1, 2, 3)]
        return []

    monkeypatch.setattr(github_installs, "refresh_installation_repositories", fake_refresh)
    resp = api.post("/api/github/installations/inst-1/refresh")
    assert resp.status_code == 200, resp.text
    assert resp.json()["authorized_repository_count"] == 3
    assert resp.json()["repositories"] == ["acme/r1", "acme/r2", "acme/r3"]


def test_list_repos_uses_live_refresh(api, monkeypatch):
    _scopes("read")
    row = GatewayGitHubInstallation(
        id="inst-1", org_id="org-a", github_installation_id=GH_ID, github_account_login="acme",
        github_account_type="Organization", status="active", created_at=1.0, updated_at=1.0,
    )
    monkeypatch.setattr(gh_store, "get_installation", AsyncMock(return_value=row))

    async def fake_refresh(session, r):
        return [{"id": 5, "full_name": "acme/new", "name": "new", "private": True, "html_url": "u"}]

    monkeypatch.setattr(github_installs, "refresh_installation_repositories", fake_refresh)
    resp = api.get("/api/github/installations/inst-1/repos")
    assert resp.status_code == 200, resp.text
    assert [r["full_name"] for r in resp.json()] == ["acme/new"]


# discover service.


async def test_discover_service_links_unclaimed_and_skips_claimed(db, gh, monkeypatch):
    gh.known = {GH_ID, 5151}

    async def fake_list(app_jwt, per_page=100):
        return [
            {"id": GH_ID, "account": {"login": "Acme"}},
            {"id": 5151, "account": {"login": "acme"}},
            {"id": 7, "account": {"login": "other"}},
        ]

    monkeypatch.setattr(github_client, "list_app_installations", fake_list)
    # 5151 already belongs to another org.
    db.add(
        GatewayGitHubInstallation(
            org_id="org-z", github_installation_id=5151, github_account_login="acme",
            github_account_type="Organization", status="active", created_at=1.0, updated_at=1.0,
        )
    )
    await db.commit()
    linked = await github_installs.discover_installations_for_account(db, org_id="org-a", account_login="acme")
    assert [i.github_installation_id for i in linked] == [GH_ID]

    with pytest.raises(github_installs.InstallationNotFoundError):
        await github_installs.discover_installations_for_account(db, org_id="org-a", account_login="nobody")
