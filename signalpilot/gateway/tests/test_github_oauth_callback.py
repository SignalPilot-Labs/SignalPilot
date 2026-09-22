"""Verify the GitHub App installation callback (Vercel-style, no OAuth code).

The callback binds an installation to the org named by the signed state,
verifies the installation through the app JWT, lists the installation's own
repositories, and stores a repository-scoped token. It never exchanges an
OAuth code and never calls /user/installations.

Unit tests live in test_github_callback_unit.py. Integration tests here
replace the GitHub HTTP transport and run against an aiosqlite DB, so
pagination, installation details, token minting, RS256 signing, Fernet
encryption, and the cross-org claim refusal are exercised for real.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from gateway.api import github
from gateway.db.models import GatewayBase, GatewayGitHubInstallation

MINTED_TOKEN = "ghs_sentinel_minted_installation_token"
OWNED_INSTALLATION_ID = 222222
VICTIM_INSTALLATION_ID = 111111
ATTACKER_ORG = "org_attacker"
REPO_IDS = (5001, 5002)


# Integration tests: GitHub HTTP transport double + aiosqlite database.


@pytest.fixture(scope="module")
def rsa_private_key_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


class GitHubTransportMock:
    """Records every GitHub HTTP request and serves canned responses.

    ``known_installations`` maps installation id -> account login. Any other
    id is a 404 from /app/installations/{id}. ``repo_pages`` is a list of
    pages for /installation/repositories (per_page=100 pagination).
    """

    def __init__(
        self,
        *,
        known_installations: dict[int, str] | None = None,
        repo_pages: list[list[dict]] | None = None,
        repos_status: int = 200,
    ) -> None:
        self.known = known_installations or {OWNED_INSTALLATION_ID: "victim-corp"}
        self.repo_pages = repo_pages if repo_pages is not None else [
            [{"id": i, "full_name": f"victim-corp/repo-{i}"} for i in REPO_IDS]
        ]
        self.repos_status = repos_status
        self.requests: list[dict] = []

    @property
    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]

    @property
    def mint_bodies(self) -> list[dict | None]:
        return [r["json"] for r in self.requests if r["path"].endswith("/access_tokens")]

    @property
    def repo_list_calls(self) -> list[str]:
        return [p for p in self.paths if p.endswith("/installation/repositories")]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        body = None
        raw = request.read()
        if raw:
            import json as _json

            try:
                body = _json.loads(raw)
            except ValueError:
                body = {"__unparsed__": True}
        self.requests.append({"method": request.method, "path": f"{url.host}{url.path}", "json": body})

        if url.host == "api.github.com" and url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": MINTED_TOKEN, "expires_at": "2099-01-01T00:00:00Z"})
        if url.host == "api.github.com" and url.path.startswith("/app/installations/"):
            inst_id = int(url.path.split("/")[3])
            login = self.known.get(inst_id)
            if login is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(
                200,
                json={
                    "id": inst_id,
                    "account": {"login": login, "type": "Organization"},
                    "permissions": {"contents": "write", "pull_requests": "write"},
                },
            )
        if url.host == "api.github.com" and url.path == "/installation/repositories":
            if self.repos_status != 200:
                return httpx.Response(self.repos_status, json={"message": "nope"})
            page = int(url.params.get("page", "1"))
            items = self.repo_pages[page - 1] if 0 <= page - 1 < len(self.repo_pages) else []
            return httpx.Response(200, json={"total_count": len(items), "repositories": items})
        return httpx.Response(404, json={"message": "unexpected request in test"})


class CallbackHarness:
    def __init__(self, client: TestClient, http: GitHubTransportMock, factory) -> None:
        self.client = client
        self.http = http
        self.factory = factory

    def callback(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        return self.client.get(f"/auth/github/callback?{query}", follow_redirects=False)

    def rows(self) -> list[GatewayGitHubInstallation]:
        async def _read():
            async with self.factory() as session:
                result = await session.execute(select(GatewayGitHubInstallation))
                return list(result.scalars().all())

        return asyncio.run(_read())

    def seed(self, *, org_id: str, github_installation_id: int, status: str = "active") -> None:
        async def _write():
            async with self.factory() as session:
                session.add(
                    GatewayGitHubInstallation(
                        org_id=org_id,
                        github_installation_id=github_installation_id,
                        github_account_login="seeded",
                        github_account_type="Organization",
                        status=status,
                        created_at=1.0,
                        updated_at=1.0,
                    )
                )
                await session.commit()

        asyncio.run(_write())


@pytest.fixture()
def make_harness(monkeypatch: pytest.MonkeyPatch, rsa_private_key_pem: str, tmp_path):
    from cryptography.fernet import Fernet

    from gateway import github_client
    from gateway.api import _oauth_state
    from gateway.db import engine as db_engine
    from gateway.store import crypto as store_crypto

    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(store_crypto, "_CACHED_MULTIFERNET", None)
    monkeypatch.setattr(_oauth_state, "_HMAC_KEY", None)
    monkeypatch.setattr(_oauth_state, "_NONCE_STORE", _oauth_state._NonceStore())

    db_path = tmp_path / "callback.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)

    asyncio.run(_create())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_engine, "get_session_factory", lambda: factory)

    def _build(*, cloud: bool = True, configured: bool = True, **mock_kwargs) -> CallbackHarness:
        monkeypatch.setattr(
            github,
            "get_github_settings",
            lambda: SimpleNamespace(
                is_configured=configured,
                sp_web_url="https://app.test",
                sp_github_app_id="3786558",
                sp_github_app_client_id="Iv1.testclient",
                sp_github_app_client_secret="",
                sp_github_app_private_key=rsa_private_key_pem,
            ),
        )
        from gateway.config import github as github_config

        monkeypatch.setattr(github_config, "get_github_settings", github.get_github_settings)
        monkeypatch.setattr(github, "is_cloud_mode", lambda: cloud)
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud" if cloud else "local")

        http_mock = GitHubTransportMock(**mock_kwargs)
        real_async_client = httpx.AsyncClient

        def _factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(http_mock)
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(github_client.httpx, "AsyncClient", _factory)

        app = FastAPI()
        app.include_router(github.router)
        return CallbackHarness(TestClient(app, raise_server_exceptions=False), http_mock, factory)

    yield _build
    asyncio.run(engine.dispose())


def _signed_state(org_id: str) -> str:
    from gateway.api._oauth_state import make_state

    return make_state(org_id)


class TestCallbackSecurityMatrix:
    def test_owned_installation_succeeds_with_scoped_token_and_no_oauth_calls(self, make_harness) -> None:
        h = make_harness()
        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=_signed_state("org_legit")
        )
        assert response.status_code == 302
        assert response.headers["location"] == "https://app.test/settings/github?installed=true"

        # No OAuth code exchange, no /user/installations lookup.
        assert not any(p.startswith("github.com/login") for p in h.http.paths)
        assert not any("/user/" in p for p in h.http.paths)
        # Installation verified via the app JWT, repositories listed via the app.
        assert f"api.github.com/app/installations/{OWNED_INSTALLATION_ID}" in h.http.paths
        assert len(h.http.repo_list_calls) == 1
        # Two mints: one unrestricted for the internal listing (discarded),
        # one repository-scoped that is stored.
        assert h.http.mint_bodies == [None, {"repository_ids": list(REPO_IDS)}]

        rows = h.rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.org_id == "org_legit"
        assert row.github_installation_id == OWNED_INSTALLATION_ID
        assert row.github_account_login == "victim-corp"
        assert row.authorized_repository_ids == list(REPO_IDS)
        assert [r["full_name"] for r in row.authorized_repositories] == [
            f"victim-corp/repo-{i}" for i in REPO_IDS
        ]
        assert row.permissions == {"contents": "write", "pull_requests": "write"}
        assert row.access_token_enc and MINTED_TOKEN.encode() not in row.access_token_enc

    def test_unknown_installation_id_is_rejected_and_nothing_is_minted(self, make_harness) -> None:
        h = make_harness()
        response = h.callback(
            installation_id=VICTIM_INSTALLATION_ID, setup_action="install", state=_signed_state(ATTACKER_ORG)
        )
        assert response.headers["location"] == "https://app.test/settings/github?error=installation_not_found"
        assert h.http.mint_bodies == []
        assert h.rows() == []

    def test_installation_claimed_by_another_org_is_refused(self, make_harness) -> None:
        h = make_harness()
        h.seed(org_id="org_victim", github_installation_id=OWNED_INSTALLATION_ID)
        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=_signed_state(ATTACKER_ORG)
        )
        assert response.headers["location"] == "https://app.test/settings/github?error=installation_claimed"
        # Verified the installation exists, but never listed repos or minted.
        assert h.http.mint_bodies == []
        assert h.http.repo_list_calls == []
        rows = h.rows()
        assert [(r.org_id, r.status) for r in rows] == [("org_victim", "active")]

    def test_disconnected_row_in_another_org_does_not_block_claim(self, make_harness) -> None:
        h = make_harness()
        h.seed(org_id="org_old", github_installation_id=OWNED_INSTALLATION_ID, status="disconnected")
        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=_signed_state("org_new")
        )
        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert sorted((r.org_id, r.status) for r in h.rows()) == [("org_new", "active"), ("org_old", "disconnected")]

    def test_update_refreshes_same_org_row(self, make_harness) -> None:
        h = make_harness()
        h.seed(org_id="org_legit", github_installation_id=OWNED_INSTALLATION_ID)
        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="update", state=_signed_state("org_legit")
        )
        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        rows = h.rows()
        assert len(rows) == 1
        assert rows[0].github_account_login == "victim-corp"
        assert rows[0].authorized_repository_ids == list(REPO_IDS)

    def test_stateless_update_refreshes_single_existing_claim(self, make_harness) -> None:
        """Redirect-on-update: no state, installation held by one org -> refreshed."""
        h = make_harness()
        h.seed(org_id="org_legit", github_installation_id=OWNED_INSTALLATION_ID)
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="update")
        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        rows = h.rows()
        assert [(r.org_id, r.status) for r in rows] == [("org_legit", "active")]
        assert rows[0].authorized_repository_ids == list(REPO_IDS)
        assert rows[0].github_account_login == "victim-corp"
        assert h.http.mint_bodies == [None, {"repository_ids": list(REPO_IDS)}]

    def test_stateless_update_for_unclaimed_installation_is_rejected(self, make_harness) -> None:
        h = make_harness()
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="update")
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []
        assert h.rows() == []

    def test_stateless_update_with_two_holders_is_rejected(self, make_harness) -> None:
        h = make_harness()
        h.seed(org_id="org_a", github_installation_id=OWNED_INSTALLATION_ID)
        h.seed(org_id="org_b", github_installation_id=OWNED_INSTALLATION_ID, status="suspended")
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="update")
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []

    def test_stateless_disconnected_row_does_not_count_as_a_claim(self, make_harness) -> None:
        h = make_harness()
        h.seed(org_id="org_old", github_installation_id=OWNED_INSTALLATION_ID, status="disconnected")
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="update")
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert [(r.org_id, r.status) for r in h.rows()] == [("org_old", "disconnected")]

    def test_state_bound_org_cannot_take_over_via_update(self, make_harness) -> None:
        """A valid state for org B never moves org A's installation, even on update."""
        h = make_harness()
        h.seed(org_id="org_a", github_installation_id=OWNED_INSTALLATION_ID)
        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="update", state=_signed_state("org_b")
        )
        assert response.headers["location"] == "https://app.test/settings/github?error=installation_claimed"
        assert [(r.org_id, r.status) for r in h.rows()] == [("org_a", "active")]

    def test_org_id_cannot_be_overridden_by_a_query_param(self, make_harness) -> None:
        h = make_harness()
        h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_from_state"),
            org_id="org_injected_by_attacker",
        )
        assert [r.org_id for r in h.rows()] == ["org_from_state"]

    def test_repositories_on_second_page_are_captured(self, make_harness) -> None:
        page1 = [{"id": 900000 + i, "full_name": f"victim-corp/f{i}"} for i in range(100)]
        h = make_harness(repo_pages=[page1, [{"id": 7, "full_name": "victim-corp/last"}]])
        h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=_signed_state("org_legit"))
        assert len(h.http.repo_list_calls) == 2
        row = h.rows()[0]
        assert len(row.authorized_repository_ids) == 101
        assert 7 in row.authorized_repository_ids
        assert h.http.mint_bodies[-1] == {"repository_ids": row.authorized_repository_ids}

    def test_empty_installation_stores_row_without_token_in_cloud(self, make_harness) -> None:
        h = make_harness(repo_pages=[[]])
        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=_signed_state("org_legit")
        )
        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        # Only the internal listing mint; no scoped token can be minted for zero repos.
        assert h.http.mint_bodies == [None]
        row = h.rows()[0]
        assert row.authorized_repository_ids == []
        assert row.access_token_enc is None

    def test_repository_listing_failure_is_reported(self, make_harness) -> None:
        h = make_harness(repos_status=500)
        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=_signed_state("org_legit")
        )
        assert response.headers["location"] == "https://app.test/settings/github?error=repository_listing_failed"
        assert h.rows() == []

    def test_app_not_configured_short_circuits(self, make_harness) -> None:
        h = make_harness(configured=False)
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install")
        assert response.headers["location"] == "https://app.test/settings/github?error=github_app_not_configured"
        assert h.http.requests == []

    # State handling.

    def test_tampered_state_org_rejected(self, make_harness) -> None:
        h = make_harness()
        good = _signed_state("org_victim")
        tampered = good.replace("org_victim", "org_attacker", 1)
        assert tampered != good
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=tampered)
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []
        assert h.rows() == []

    def test_state_is_single_use_replay_rejected(self, make_harness) -> None:
        h = make_harness()
        state = _signed_state("org_legit")
        first = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=state)
        assert first.headers["location"] == "https://app.test/settings/github?installed=true"
        replay = h.callback(installation_id=VICTIM_INSTALLATION_ID, setup_action="install", state=state)
        assert replay.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert len(h.rows()) == 1

    def test_missing_state_in_cloud_mode_rejected(self, make_harness) -> None:
        h = make_harness()
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install")
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []

    def test_expired_state_rejected(self, make_harness, monkeypatch: pytest.MonkeyPatch) -> None:
        import gateway.api._oauth_state as _oauth_state

        h = make_harness()
        state = _signed_state("org_legit")
        monkeypatch.setattr(_oauth_state, "STATE_TTL_SECONDS", -1)
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=state)
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []

    # Local mode.

    def test_local_mode_links_under_local_org_without_state(self, make_harness) -> None:
        h = make_harness(cloud=False)
        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install")
        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert [r.org_id for r in h.rows()] == ["local"]
        # Scoped token still preferred when repositories exist.
        assert h.http.mint_bodies == [None, {"repository_ids": list(REPO_IDS)}]
