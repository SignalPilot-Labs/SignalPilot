"""Tests for the GitHub App OAuth install callback (SP-SEC-004).

Two layers:

1. Unit-ish tests (top of file) that monkeypatch ``gateway.github_client``
   coroutines directly.
2. Integration tests (``TestCallbackSecurityMatrix``) that mock GitHub at the
   **HTTP transport** layer, so the real ``github_client`` code —
   ``exchange_code_for_token``, ``list_user_installations`` (including its
   pagination loop), ``get_installation_details``, ``create_installation_token``
   — executes for real, real RS256 app JWTs are signed with a throwaway RSA
   key, and real Fernet encryption runs. Those tests can therefore assert on
   *which GitHub endpoints were hit*, which is what proves the SP-SEC-004 fix:
   the installation-token mint must never be reached for a foreign
   installation_id.

No real credentials are used here; see ``test_github_live.py`` for the
real-network coverage.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.api import github


def _client(monkeypatch, client_secret: str = "secret") -> TestClient:
    monkeypatch.setattr(
        github,
        "get_github_settings",
        lambda: SimpleNamespace(
            is_configured=True,
            sp_web_url="https://app.test",
            sp_github_app_id="12345",
            sp_github_app_client_id="Iv1.client",
            sp_github_app_client_secret=client_secret,
            sp_github_app_private_key="fake-pem",
        ),
    )
    monkeypatch.setattr(github, "is_cloud_mode", lambda: True)

    app = FastAPI()
    app.include_router(github.router)
    return TestClient(app, raise_server_exceptions=False)


def test_github_callback_missing_state_redirects_to_settings_error(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"


def test_github_callback_missing_code_rejected_in_cloud_mode(monkeypatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=good",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_code_missing"


def test_github_callback_missing_client_secret_rejected_in_cloud_mode(monkeypatch) -> None:
    client = _client(monkeypatch, client_secret="")
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=good&code=abc",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=github_app_not_configured"


def test_github_callback_foreign_installation_rejected(monkeypatch) -> None:
    from gateway import github_client

    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")

    async def fake_exchange(client_id, client_secret, code):
        return {"access_token": "user-token"}

    async def fake_user_installations(user_token, per_page=100):
        return [{"id": 456}, {"id": 789}]

    monkeypatch.setattr(github_client, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(github_client, "list_user_installations", fake_user_installations)

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=good&code=abc",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=installation_not_authorized"


def test_github_callback_code_exchange_failure_rejected(monkeypatch) -> None:
    from gateway import github_client

    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")

    async def fake_exchange(client_id, client_secret, code):
        return {"error": "bad_verification_code"}

    monkeypatch.setattr(github_client, "exchange_code_for_token", fake_exchange)

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=good&code=abc",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_verification_failed"


def test_github_callback_owned_installation_succeeds(monkeypatch) -> None:
    from gateway import github_client
    from gateway.db import engine as db_engine
    from gateway.store import crypto as store_crypto
    from gateway.store import github as gh_store

    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")

    async def fake_exchange(client_id, client_secret, code):
        return {"access_token": "user-token"}

    async def fake_user_installations(user_token, per_page=100):
        return [{"id": 123}]

    async def fake_details(app_jwt, installation_id):
        return {"account": {"login": "acme", "type": "Organization"}, "permissions": {}}

    async def fake_user_repos(user_token, installation_id, per_page=100):
        return [{"id": 5001}]

    async def fake_create_token(app_jwt, installation_id, *, repository_ids):
        assert repository_ids == [5001]
        return {"token": "ghs_installtoken", "expires_at": "2099-01-01T00:00:00Z"}

    monkeypatch.setattr(github_client, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(github_client, "list_user_installations", fake_user_installations)
    monkeypatch.setattr(github_client, "list_user_installation_repositories", fake_user_repos)
    monkeypatch.setattr(github_client, "get_installation_details", fake_details)
    monkeypatch.setattr(github_client, "create_installation_token", fake_create_token)
    monkeypatch.setattr(github_client, "generate_app_jwt", lambda app_id, key: "fake-jwt")
    monkeypatch.setattr(store_crypto, "_encrypt", lambda v: b"enc")

    upserts: list[dict] = []

    async def fake_upsert(session, **kwargs):
        upserts.append(kwargs)

    monkeypatch.setattr(gh_store, "upsert_installation", fake_upsert)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(db_engine, "get_session_factory", lambda: _FakeSession)

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=good&code=abc",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?installed=true"
    assert len(upserts) == 1
    assert upserts[0]["org_id"] == "org_abc"
    assert upserts[0]["github_installation_id"] == 123


def test_github_callback_invalid_state_redirects_to_settings_error(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=bad-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"


# ─────────────────────────────────────────────────────────────────────────────
# SP-SEC-004 security matrix — GitHub mocked at the HTTP transport layer
# ─────────────────────────────────────────────────────────────────────────────

# Sentinel secrets. These are fake, but they stand in for the real ones so the
# "nothing leaks into a response body or a log line" assertions are meaningful.
FAKE_CLIENT_SECRET = "sentinel-client-secret-must-never-be-echoed"
FAKE_USER_TOKEN = "ghu_sentinel_user_token"
MINTED_TOKEN = "ghs_sentinel_minted_installation_token"

OAUTH_TOKEN_PATH = "/login/oauth/access_token"
USER_INSTALLATIONS_PATH = "/user/installations"

VICTIM_INSTALLATION_ID = 111111  # belongs to another tenant; the attacker target
ATTACKER_ORG = "org_attacker"
OWNED_INSTALLATION_ID = 222222  # genuinely accessible to the authorizing user

# SP-SEC-005: repo the authorizing user can actually open, vs. sibling repos
# that live in the same installation but are off-limits to that user.
USER_REPO_ID = 5001
SIBLING_REPO_IDS = (5002, 5003)


@pytest.fixture(scope="module")
def rsa_private_key_pem() -> str:
    """A throwaway RSA-2048 private key so ``generate_app_jwt`` runs for real."""
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

    ``installation_pages`` is a list of pages; ``list_user_installations``
    paginates until a page comes back shorter than ``per_page`` (100), so a
    two-element list with a full first page exercises the pagination loop.
    """

    def __init__(
        self,
        *,
        installation_pages: list[list[dict]] | None = None,
        user_repo_pages: list[list[dict]] | None = None,
        token_response: dict | None = None,
        user_installations_status: int = 200,
        user_repos_status: int = 200,
    ) -> None:
        self.installation_pages = installation_pages or [[]]
        # Default: the authorizing user can reach exactly one repo.
        self.user_repo_pages = user_repo_pages if user_repo_pages is not None else [[{"id": USER_REPO_ID}]]
        self.token_response = token_response if token_response is not None else {"access_token": FAKE_USER_TOKEN}
        self.user_installations_status = user_installations_status
        self.user_repos_status = user_repos_status
        self.requests: list[dict] = []  # {method, path, json}

    # ── request log helpers ──────────────────────────────────────────────
    @property
    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]

    @property
    def mint_calls(self) -> list[str]:
        return [p for p in self.paths if p.endswith("/access_tokens")]

    @property
    def mint_bodies(self) -> list[dict | None]:
        return [r["json"] for r in self.requests if r["path"].endswith("/access_tokens")]

    @property
    def user_installations_calls(self) -> list[str]:
        return [p for p in self.paths if p.endswith(USER_INSTALLATIONS_PATH)]

    @property
    def user_repo_calls(self) -> list[str]:
        return [p for p in self.paths if p.endswith("/repositories") and p.startswith("api.github.com/user/")]

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

        if url.host == "github.com" and url.path == OAUTH_TOKEN_PATH:
            return httpx.Response(200, json=self.token_response)

        if url.host == "api.github.com" and url.path == USER_INSTALLATIONS_PATH:
            if self.user_installations_status != 200:
                return httpx.Response(self.user_installations_status, json={"message": "Bad credentials"})
            page = int(url.params.get("page", "1"))
            items = self.installation_pages[page - 1] if 0 <= page - 1 < len(self.installation_pages) else []
            return httpx.Response(200, json={"total_count": len(items), "installations": items})

        if (
            url.host == "api.github.com"
            and url.path.startswith("/user/installations/")
            and url.path.endswith("/repositories")
        ):
            if self.user_repos_status != 200:
                return httpx.Response(self.user_repos_status, json={"message": "Not accessible"})
            page = int(url.params.get("page", "1"))
            items = self.user_repo_pages[page - 1] if 0 <= page - 1 < len(self.user_repo_pages) else []
            return httpx.Response(200, json={"total_count": len(items), "repositories": items})

        if url.host == "api.github.com" and url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": MINTED_TOKEN, "expires_at": "2099-01-01T00:00:00Z"})

        if url.host == "api.github.com" and url.path.startswith("/app/installations/"):
            return httpx.Response(
                200,
                json={
                    "id": int(url.path.rsplit("/", 1)[-1]),
                    "account": {"login": "victim-corp", "type": "Organization"},
                    "permissions": {"contents": "write"},
                },
            )

        return httpx.Response(404, json={"message": "unexpected request in test"})


class CallbackHarness:
    """Bundles the TestClient, the HTTP mock, and the recorded store writes."""

    def __init__(self, client: TestClient, http: GitHubTransportMock, upserts: list[dict]) -> None:
        self.client = client
        self.http = http
        self.upserts = upserts

    def callback(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        return self.client.get(f"/auth/github/callback?{query}", follow_redirects=False)


@pytest.fixture()
def make_harness(monkeypatch: pytest.MonkeyPatch, rsa_private_key_pem: str):
    """Factory building a CallbackHarness with GitHub mocked at the transport layer."""
    from cryptography.fernet import Fernet

    from gateway import github_client
    from gateway.api import _oauth_state
    from gateway.db import engine as db_engine
    from gateway.store import crypto as store_crypto
    from gateway.store import github as gh_store

    # Real Fernet encryption with a throwaway raw key (no PBKDF2, no salt file).
    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(store_crypto, "_CACHED_MULTIFERNET", None)

    # Real HMAC state signing, fresh nonce store per test (replay isolation).
    monkeypatch.setattr(_oauth_state, "_HMAC_KEY", None)
    monkeypatch.setattr(_oauth_state, "_NONCE_STORE", _oauth_state._NonceStore())

    upserts: list[dict] = []

    async def fake_upsert(session, **kwargs):
        upserts.append(kwargs)

    monkeypatch.setattr(gh_store, "upsert_installation", fake_upsert)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(db_engine, "get_session_factory", lambda: _FakeSession)

    def _build(
        *,
        cloud: bool = True,
        client_secret: str = FAKE_CLIENT_SECRET,
        configured: bool = True,
        **mock_kwargs,
    ) -> CallbackHarness:
        monkeypatch.setattr(
            github,
            "get_github_settings",
            lambda: SimpleNamespace(
                is_configured=configured,
                sp_web_url="https://app.test",
                sp_github_app_id="3786558",
                sp_github_app_client_id="Iv1.testclient",
                sp_github_app_client_secret=client_secret,
                sp_github_app_private_key=rsa_private_key_pem,
            ),
        )
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
        return CallbackHarness(TestClient(app, raise_server_exceptions=False), http_mock, upserts)

    return _build


def _signed_state(org_id: str) -> str:
    from gateway.api._oauth_state import make_state

    return make_state(org_id)


def _full_page(count: int = 100, start_id: int = 900000) -> list[dict]:
    return [{"id": start_id + i, "account": {"login": f"filler-{i}"}} for i in range(count)]


class TestCallbackSecurityMatrix:
    # ── THE exploit ──────────────────────────────────────────────────────

    def test_foreign_installation_id_is_rejected_and_no_token_is_minted(self, make_harness) -> None:
        """SP-SEC-004: the original cross-tenant exploit.

        The attacker holds a *validly signed* state for their OWN org and a
        legitimate OAuth code for their OWN GitHub user, then swaps in the
        installation_id of a victim tenant. Before the fix this minted a real
        installation token for the victim repos and stored it under the
        attacker org (private-repo read AND write).

        The assertions that matter are the negative ones: the
        ``/access_tokens`` mint endpoint must never be requested, and nothing
        may be written to the store.
        """
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])

        response = h.callback(
            installation_id=VICTIM_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state(ATTACKER_ORG),
            code="attacker-own-valid-code",
        )

        assert response.status_code == 302
        assert response.headers["location"] == "https://app.test/settings/github?error=installation_not_authorized"

        # The fix: ownership was actually checked against GitHub...
        assert h.http.user_installations_calls, "user-authorization leg was never performed"
        # ...and the privileged mint never happened.
        assert h.http.mint_calls == [], "installation token was minted for a foreign installation"
        assert not any(p.startswith("api.github.com/app/installations/") for p in h.http.paths), (
            "app-JWT installation endpoints were reached for a foreign installation"
        )
        # ...and nothing was persisted under the attacker org.
        assert h.upserts == []

    def test_owned_installation_succeeds_and_upserts_under_state_org(self, make_harness) -> None:
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}, {"id": 333333}]])

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert response.status_code == 302
        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert len(h.http.mint_calls) == 1
        assert len(h.upserts) == 1
        # org_id comes from the signed state, never from a caller-supplied param.
        assert h.upserts[0]["org_id"] == "org_legit"
        assert h.upserts[0]["github_installation_id"] == OWNED_INSTALLATION_ID
        assert h.upserts[0]["github_account_login"] == "victim-corp"

    def test_org_id_cannot_be_overridden_by_a_query_param(self, make_harness) -> None:
        """A caller-supplied ``org_id`` query param must be ignored entirely."""
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_from_state"),
            code="legit-code",
            org_id="org_injected_by_attacker",
        )

        assert response.status_code == 302
        assert h.upserts[0]["org_id"] == "org_from_state"

    # ── pagination ───────────────────────────────────────────────────────

    def test_installation_on_second_page_is_accepted(self, make_harness) -> None:
        """Proves list_user_installations paginates instead of trusting page 1."""
        h = make_harness(installation_pages=[_full_page(), [{"id": OWNED_INSTALLATION_ID}]])

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert len(h.http.user_installations_calls) == 2, "second page was never fetched"
        assert len(h.http.mint_calls) == 1

    def test_absent_from_all_pages_is_rejected(self, make_harness) -> None:
        h = make_harness(installation_pages=[_full_page(), _full_page(start_id=800000)])

        response = h.callback(
            installation_id=VICTIM_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state(ATTACKER_ORG),
            code="attacker-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=installation_not_authorized"
        # Two full pages then an empty third page terminates the loop.
        assert len(h.http.user_installations_calls) == 3
        assert h.http.mint_calls == []

    def test_empty_user_installations_is_rejected(self, make_harness) -> None:
        """Valid user token, but the user can see no installations at all."""
        h = make_harness(installation_pages=[[]])

        response = h.callback(
            installation_id=VICTIM_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state(ATTACKER_ORG),
            code="attacker-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=installation_not_authorized"
        assert h.http.mint_calls == []
        assert h.upserts == []

    # ── code / secret preconditions ──────────────────────────────────────

    def test_missing_code_rejected_without_any_github_call(self, make_harness) -> None:
        h = make_harness()

        response = h.callback(
            installation_id=VICTIM_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state(ATTACKER_ORG),
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_code_missing"
        assert h.http.requests == []
        assert h.upserts == []

    def test_unconfigured_client_secret_fails_closed_with_no_github_call(self, make_harness) -> None:
        """If SP_GITHUB_APP_CLIENT_SECRET is missing we must fail closed, not skip the check."""
        h = make_harness(client_secret="")

        response = h.callback(
            installation_id=VICTIM_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state(ATTACKER_ORG),
            code="attacker-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=github_app_not_configured"
        assert h.http.requests == [], "a GitHub call was made despite the missing client secret"
        assert h.upserts == []

    def test_app_not_configured_short_circuits(self, make_harness) -> None:
        h = make_harness(configured=False)

        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install")

        assert response.headers["location"] == "https://app.test/settings/github?error=github_app_not_configured"
        assert h.http.requests == []

    def test_code_exchange_error_response_rejected(self, make_harness) -> None:
        h = make_harness(token_response={"error": "bad_verification_code"})

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="stale-or-forged-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_verification_failed"
        assert h.http.user_installations_calls == []
        assert h.http.mint_calls == []

    def test_code_exchange_without_access_token_rejected(self, make_harness) -> None:
        h = make_harness(token_response={"token_type": "bearer"})

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="weird-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_verification_failed"
        assert h.http.mint_calls == []

    def test_user_installations_401_rejected_not_crashed(self, make_harness) -> None:
        """A revoked/invalid user token must fail closed, not 500."""
        h = make_harness(user_installations_status=401)

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert response.status_code == 302
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_verification_failed"
        assert h.http.mint_calls == []
        assert h.upserts == []

    # ── state handling ───────────────────────────────────────────────────

    def test_tampered_state_org_rejected(self, make_harness) -> None:
        """Rewriting the org inside a signed state breaks the HMAC."""
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])
        good = _signed_state("org_victim")
        tampered = good.replace("org_victim", "org_attacker", 1)
        assert tampered != good

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=tampered,
            code="legit-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []
        assert h.upserts == []

    def test_state_is_single_use_replay_rejected(self, make_harness) -> None:
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])
        state = _signed_state("org_legit")

        first = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=state, code="code-1"
        )
        assert first.headers["location"] == "https://app.test/settings/github?installed=true"

        replay = h.callback(
            installation_id=VICTIM_INSTALLATION_ID, setup_action="install", state=state, code="code-2"
        )
        assert replay.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"

        # Only the first (authorized) flow minted a token.
        assert len(h.http.mint_calls) == 1
        assert len(h.upserts) == 1
        assert h.upserts[0]["github_installation_id"] == OWNED_INSTALLATION_ID

    def test_missing_state_in_cloud_mode_rejected(self, make_harness) -> None:
        h = make_harness()

        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install", code="c")

        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []

    def test_garbage_state_rejected(self, make_harness) -> None:
        h = make_harness()

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state="not-a-state", code="c"
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []

    def test_expired_state_rejected(self, make_harness, monkeypatch: pytest.MonkeyPatch) -> None:
        import gateway.api._oauth_state as _oauth_state

        h = make_harness()
        state = _signed_state("org_legit")
        monkeypatch.setattr(_oauth_state, "STATE_TTL_SECONDS", -1)

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID, setup_action="install", state=state, code="c"
        )

        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
        assert h.http.requests == []

    # ── local-mode regression guard ──────────────────────────────────────

    def test_local_mode_unchanged_no_user_authorization_check(self, make_harness) -> None:
        """Local mode has no tenant boundary: no code, no /user/installations call."""
        h = make_harness(cloud=False, installation_pages=[[]])

        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install")

        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert h.http.user_installations_calls == []
        assert len(h.http.mint_calls) == 1
        assert len(h.upserts) == 1
        assert h.upserts[0]["org_id"] == "local"

    def test_local_mode_unverifiable_state_falls_back_to_local_org(self, make_harness) -> None:
        h = make_harness(cloud=False)

        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install", state="junk")

        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert h.upserts[0]["org_id"] == "local"

    # ── no secret leakage (requirement C) ────────────────────────────────

    @pytest.mark.parametrize(
        ("scenario", "expected_error"),
        [
            ("foreign", "installation_not_authorized"),
            ("exchange_failed", "oauth_verification_failed"),
            ("no_secret", "github_app_not_configured"),
        ],
    )
    def test_failure_paths_leak_no_secrets_and_no_exception_detail(
        self, make_harness, caplog, scenario: str, expected_error: str, rsa_private_key_pem: str
    ) -> None:
        import logging

        caplog.set_level(logging.DEBUG)

        if scenario == "foreign":
            h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])
            installation_id = VICTIM_INSTALLATION_ID
        elif scenario == "exchange_failed":
            h = make_harness(token_response={"error": "bad_verification_code"})
            installation_id = OWNED_INSTALLATION_ID
        else:
            h = make_harness(client_secret="")
            installation_id = OWNED_INSTALLATION_ID

        response = h.callback(
            installation_id=installation_id,
            setup_action="install",
            state=_signed_state(ATTACKER_ORG),
            code="some-code",
        )

        assert response.status_code == 302
        location = response.headers["location"]
        assert location == f"https://app.test/settings/github?error={expected_error}"

        body_and_logs = response.text + "\n" + location + "\n" + caplog.text
        pem_body = "".join(rsa_private_key_pem.splitlines()[1:-1])[:64]
        for secret in (FAKE_CLIENT_SECRET, FAKE_USER_TOKEN, MINTED_TOKEN, pem_body):
            assert secret not in body_and_logs, "a secret value appeared in a response or log line"

        # No exception detail / stack noise leaked to the user.
        assert "Traceback" not in response.text
        for noisy in ("httpx", "MockTransport", "asyncio"):
            assert noisy not in location

    def test_stored_token_is_encrypted_not_plaintext(self, make_harness) -> None:
        """The minted installation token must never be persisted in the clear."""
        from gateway.store.crypto import _decrypt

        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])

        h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        enc = h.upserts[0]["access_token_enc"]
        assert isinstance(enc, bytes)
        assert MINTED_TOKEN.encode() not in enc
        assert _decrypt(enc) == MINTED_TOKEN

    def test_success_redirect_carries_no_token(self, make_harness) -> None:
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert MINTED_TOKEN not in response.headers["location"]
        assert MINTED_TOKEN not in response.text
        assert FAKE_USER_TOKEN not in response.headers["location"]


# ─────────────────────────────────────────────────────────────────────────────
# SP-SEC-005 — installation-token permission amplification
#
# Seeing an installation is not the same as being able to reach every repo in
# it. A body-less POST to /access_tokens mints a token with the installation's
# full permissions on ALL its repositories, discarding the user∩app
# intersection GitHub's user-access-token model would enforce. The token must be
# restricted to the repositories the authorizing user can actually access.
# ─────────────────────────────────────────────────────────────────────────────


def _repo_page(ids) -> list[dict]:
    return [{"id": i, "full_name": f"acme/repo-{i}", "private": True} for i in ids]


class TestInstallationTokenRepositoryScoping:
    def test_token_is_scoped_to_only_the_repos_the_user_can_access(self, make_harness) -> None:
        """CORE REGRESSION TEST.

        The installation contains repo A plus two siblings, but the authorizing
        user can only reach A. The minted token must carry
        ``repository_ids == [A]`` and must not mention the siblings.
        """
        h = make_harness(
            installation_pages=[[{"id": OWNED_INSTALLATION_ID}]],
            user_repo_pages=[_repo_page([USER_REPO_ID])],
        )

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert len(h.http.mint_calls) == 1
        body = h.http.mint_bodies[0]
        assert body is not None, "the token mint POST had no body — the restriction was dropped"
        assert body["repository_ids"] == [USER_REPO_ID]
        for sibling in SIBLING_REPO_IDS:
            assert sibling not in body["repository_ids"]
        # ...and the scope is persisted so refresh can stay narrow.
        assert h.upserts[0]["authorized_repository_ids"] == [USER_REPO_ID]

    def test_mint_post_body_always_declares_repository_ids(self, make_harness) -> None:
        """Guard: a future refactor that drops the body must fail the suite."""
        h = make_harness(
            installation_pages=[[{"id": OWNED_INSTALLATION_ID}]],
            user_repo_pages=[_repo_page([USER_REPO_ID, *SIBLING_REPO_IDS])],
        )

        h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        (body,) = h.http.mint_bodies
        assert isinstance(body, dict)
        assert "repository_ids" in body
        assert body["repository_ids"] == [USER_REPO_ID, *SIBLING_REPO_IDS]

    def test_empty_user_repo_list_rejected_without_minting(self, make_harness) -> None:
        """User can see the installation but reach none of its repos → refuse."""
        h = make_harness(
            installation_pages=[[{"id": OWNED_INSTALLATION_ID}]],
            user_repo_pages=[[]],
        )

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert response.status_code == 302
        assert response.headers["location"] == "https://app.test/settings/github?error=no_accessible_repositories"
        assert h.http.mint_calls == [], "an unrestricted token was minted for a user with no accessible repos"
        assert h.upserts == []

    def test_per_installation_repositories_endpoint_is_paginated(self, make_harness) -> None:
        first_page = _repo_page(range(6000, 6100))  # exactly per_page → loop continues
        assert len(first_page) == 100
        h = make_harness(
            installation_pages=[[{"id": OWNED_INSTALLATION_ID}]],
            user_repo_pages=[first_page, _repo_page([USER_REPO_ID])],
        )

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert len(h.http.user_repo_calls) == 2, "second page of user repositories was never fetched"
        body = h.http.mint_bodies[0]
        assert len(body["repository_ids"]) == 101
        assert USER_REPO_ID in body["repository_ids"], "page-2 repo missing from the token scope"

    def test_user_repositories_call_uses_the_installation_specific_path(self, make_harness) -> None:
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])

        h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert h.http.user_repo_calls == [
            f"api.github.com/user/installations/{OWNED_INSTALLATION_ID}/repositories"
        ]

    def test_user_repositories_error_rejects_without_minting(self, make_harness) -> None:
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]], user_repos_status=403)

        response = h.callback(
            installation_id=OWNED_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state("org_legit"),
            code="legit-code",
        )

        assert response.status_code == 302
        assert response.headers["location"] == "https://app.test/settings/github?error=oauth_verification_failed"
        assert h.http.mint_calls == []
        assert h.upserts == []

    def test_foreign_installation_never_reaches_the_repo_enumeration(self, make_harness) -> None:
        """The SP-SEC-004 gate still short-circuits ahead of SP-SEC-005."""
        h = make_harness(installation_pages=[[{"id": OWNED_INSTALLATION_ID}]])

        h.callback(
            installation_id=VICTIM_INSTALLATION_ID,
            setup_action="install",
            state=_signed_state(ATTACKER_ORG),
            code="attacker-code",
        )

        assert h.http.user_repo_calls == []
        assert h.http.mint_calls == []

    def test_local_mode_mints_installation_wide_token_by_design(self, make_harness) -> None:
        """Local/single-tenant: no user token exists, so no intersection to take.

        Documented, explicit exception — it goes through
        ``create_unrestricted_installation_token`` and sends no body.
        """
        h = make_harness(cloud=False)

        response = h.callback(installation_id=OWNED_INSTALLATION_ID, setup_action="install")

        assert response.headers["location"] == "https://app.test/settings/github?installed=true"
        assert h.http.user_repo_calls == []
        assert h.http.mint_bodies == [None]
        assert h.upserts[0]["authorized_repository_ids"] is None


class TestCreateInstallationTokenContract:
    async def test_empty_repository_ids_raises_rather_than_minting_wide(self) -> None:
        from gateway.github_client import create_installation_token

        for bad in ([], None):
            with pytest.raises(ValueError, match="non-empty repository_ids"):
                await create_installation_token("jwt", 1, repository_ids=bad)

    async def test_repository_ids_is_keyword_only_and_required(self) -> None:
        import inspect

        from gateway.github_client import create_installation_token

        sig = inspect.signature(create_installation_token)
        param = sig.parameters["repository_ids"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty


class TestTokenRefreshKeepsRepositoryScope:
    """The refresh path must not widen a scoped token an hour after install."""

    @staticmethod
    def _row(**kw):
        from gateway.db.models import GatewayGitHubInstallation

        defaults = {
            "id": "inst-row-1",
            "org_id": "org_legit",
            "github_installation_id": OWNED_INSTALLATION_ID,
            "github_account_login": "acme",
            "github_account_type": "Organization",
            "access_token_enc": b"enc",
            "token_expires_at": 0.0,  # expired → forces a refresh
            "authorized_repository_ids": None,
            "status": "active",
            "created_at": 0.0,
            "updated_at": 0.0,
        }
        defaults.update(kw)
        return GatewayGitHubInstallation(**defaults)

    @staticmethod
    def _session(linked_repo_ids: list[int]):
        class _Scalars:
            def __init__(self, values):
                self._values = values

            def all(self):
                return list(self._values)

        class _Result:
            def __init__(self, values):
                self._values = values

            def scalars(self):
                return _Scalars(self._values)

        class _Session:
            async def execute(self, *_args, **_kw):
                return _Result(linked_repo_ids)

            async def commit(self):
                return None

        return _Session()

    @pytest.fixture(autouse=True)
    def _patch_crypto_and_jwt(self, monkeypatch: pytest.MonkeyPatch):
        from gateway import github_client
        from gateway.store import crypto as store_crypto

        monkeypatch.setattr(store_crypto, "_decrypt_with_migration", lambda b: ("stale-token", False))
        monkeypatch.setattr(store_crypto, "_encrypt", lambda v: b"enc")
        monkeypatch.setattr(github_client, "generate_app_jwt", lambda app_id, key: "fake-jwt")

        self.restricted: list[list[int]] = []
        self.unrestricted: list[int] = []

        async def spy_restricted(app_jwt, installation_id, *, repository_ids):
            self.restricted.append(list(repository_ids))
            return {"token": MINTED_TOKEN, "expires_at": "2099-01-01T00:00:00Z"}

        async def spy_unrestricted(app_jwt, installation_id):
            self.unrestricted.append(installation_id)
            return {"token": MINTED_TOKEN, "expires_at": "2099-01-01T00:00:00Z"}

        monkeypatch.setattr(github_client, "create_installation_token", spy_restricted)
        monkeypatch.setattr(github_client, "create_unrestricted_installation_token", spy_unrestricted)
        yield

    async def test_refresh_reuses_stored_authorized_repository_ids(self, monkeypatch) -> None:
        from gateway.store import github as gh_store

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        row = self._row(authorized_repository_ids=[USER_REPO_ID])

        token = await gh_store.get_valid_token(self._session([*SIBLING_REPO_IDS]), row)

        assert token == MINTED_TOKEN
        assert self.restricted == [[USER_REPO_ID]], "refresh did not reuse the stored repository scope"
        assert self.unrestricted == []

    async def test_legacy_row_refresh_falls_back_to_linked_repos(self, monkeypatch) -> None:
        from gateway.store import github as gh_store

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        row = self._row(authorized_repository_ids=None)

        await gh_store.get_valid_token(self._session([USER_REPO_ID]), row)

        assert self.restricted == [[USER_REPO_ID]]
        assert self.unrestricted == []

    async def test_legacy_row_with_no_scope_refuses_in_cloud_mode(self, monkeypatch) -> None:
        from gateway.store import github as gh_store

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        row = self._row(authorized_repository_ids=None)

        with pytest.raises(ValueError, match="no repository scope is recorded"):
            await gh_store.get_valid_token(self._session([]), row)

        assert self.restricted == []
        assert self.unrestricted == [], "cloud mode fell back to an installation-wide token"

    async def test_local_mode_refresh_may_be_installation_wide(self, monkeypatch) -> None:
        from gateway.store import github as gh_store

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        row = self._row(authorized_repository_ids=None)

        await gh_store.get_valid_token(self._session([]), row)

        assert self.unrestricted == [OWNED_INSTALLATION_ID]
        assert self.restricted == []

    async def test_unexpired_token_is_returned_without_minting(self, monkeypatch) -> None:
        import time as _time

        from gateway.store import github as gh_store

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        row = self._row(token_expires_at=_time.time() + 3600)

        token = await gh_store.get_valid_token(self._session([]), row)

        assert token == "stale-token"
        assert self.restricted == []
        assert self.unrestricted == []
