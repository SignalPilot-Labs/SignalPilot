"""Unit tests for the GitHub App installation callback (no OAuth code).

The store coroutines are replaced; the transport-level matrix lives in
test_github_oauth_callback.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.api import github


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        github,
        "get_github_settings",
        lambda: SimpleNamespace(
            is_configured=True,
            sp_web_url="https://app.test",
            sp_github_app_id="12345",
            sp_github_app_client_id="Iv1.client",
            sp_github_app_client_secret="",
            sp_github_app_private_key="fake-pem",
        ),
    )
    monkeypatch.setattr(github, "is_cloud_mode", lambda: True)

    app = FastAPI()
    app.include_router(github.router)
    return TestClient(app, raise_server_exceptions=False)


def _fake_factory(monkeypatch):
    from gateway.db import engine as db_engine

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(db_engine, "get_session_factory", lambda: _FakeSession)



# Unit tests.


def _no_claim_owners(monkeypatch) -> None:
    """Unclaimed installation: a missing/invalid state is a new claim and is refused."""
    from gateway.store import github_installs

    _fake_factory(monkeypatch)

    async def owners(session, github_installation_id):
        return []

    monkeypatch.setattr(github_installs, "active_claim_owners", owners)


def test_missing_state_redirects_to_settings_error(monkeypatch) -> None:
    client = _client(monkeypatch)
    _no_claim_owners(monkeypatch)
    response = client.get("/auth/github/callback?installation_id=123&setup_action=install", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"


def test_invalid_state_redirects_to_settings_error(monkeypatch) -> None:
    client = _client(monkeypatch)
    _no_claim_owners(monkeypatch)
    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=bad-state",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"


def test_code_is_not_required_and_ignored(monkeypatch) -> None:
    """The OAuth ``code`` leg is gone: a callback without it succeeds."""
    from gateway.store import github_installs

    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")
    _fake_factory(monkeypatch)
    calls: list[dict] = []

    async def fake_complete(session, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(github_account_login="acme")

    monkeypatch.setattr(github_installs, "complete_installation", fake_complete)

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=good",
        follow_redirects=False,
    )
    assert response.headers["location"] == "https://app.test/settings/github?installed=true"
    assert calls == [{"org_id": "org_abc", "github_installation_id": 123}]


def test_missing_client_secret_is_not_an_error(monkeypatch) -> None:
    """The client secret is no longer part of the flow."""
    from gateway.config.github import GitHubAppSettings

    settings = GitHubAppSettings(
        SP_GITHUB_APP_ID="1", SP_GITHUB_APP_CLIENT_ID="Iv1.x", SP_GITHUB_APP_PRIVATE_KEY="pem",
        SP_GITHUB_APP_CLIENT_SECRET="",
    )
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    assert settings.is_configured is True


def test_missing_state_with_single_claim_owner_refreshes_that_org(monkeypatch) -> None:
    """GitHub's redirect-on-update carries no state: refresh the existing claim."""
    from gateway.store import github_installs

    client = _client(monkeypatch)
    _fake_factory(monkeypatch)
    calls: list[dict] = []

    async def owners(session, github_installation_id):
        return ["org_holder"]

    async def fake_complete(session, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(github_account_login="acme")

    monkeypatch.setattr(github_installs, "active_claim_owners", owners)
    monkeypatch.setattr(github_installs, "complete_installation", fake_complete)
    response = client.get("/auth/github/callback?installation_id=123&setup_action=update", follow_redirects=False)
    assert response.headers["location"] == "https://app.test/settings/github?installed=true"
    assert calls == [{"org_id": "org_holder", "github_installation_id": 123}]


@pytest.mark.parametrize("owners_list", [[], ["org_a", "org_b"]])
def test_missing_state_without_single_owner_is_rejected(monkeypatch, owners_list) -> None:
    from gateway.store import github_installs

    client = _client(monkeypatch)
    _fake_factory(monkeypatch)

    async def owners(session, github_installation_id):
        return owners_list

    async def never(session, **kwargs):
        raise AssertionError("must not claim without state")

    monkeypatch.setattr(github_installs, "active_claim_owners", owners)
    monkeypatch.setattr(github_installs, "complete_installation", never)
    response = client.get("/auth/github/callback?installation_id=123&setup_action=update", follow_redirects=False)
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"


def test_setup_action_request_redirects_pending(monkeypatch) -> None:
    from gateway.store import github_installs

    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")

    async def never(*a, **k):
        raise AssertionError("no installation must be linked for a pending request")

    monkeypatch.setattr(github_installs, "complete_installation", never)
    response = client.get("/auth/github/callback?setup_action=request&state=good", follow_redirects=False)
    assert response.headers["location"] == "https://app.test/settings/github?pending=true"


@pytest.mark.parametrize(
    ("exc_name", "error_code"),
    [
        ("InstallationClaimedError", "installation_claimed"),
        ("InstallationNotFoundError", "installation_not_found"),
        ("RepositoryListingError", "repository_listing_failed"),
    ],
)
def test_service_errors_map_to_distinct_codes(monkeypatch, exc_name, error_code) -> None:
    from gateway.store import github_installs

    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")
    _fake_factory(monkeypatch)
    exc_type = getattr(github_installs, exc_name)

    async def fail(session, **kwargs):
        raise exc_type("nope")

    monkeypatch.setattr(github_installs, "complete_installation", fail)
    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=good",
        follow_redirects=False,
    )
    assert response.headers["location"] == f"https://app.test/settings/github?error={error_code}"


def test_setup_action_update_refreshes(monkeypatch) -> None:
    from gateway.store import github_installs

    client = _client(monkeypatch)
    monkeypatch.setattr(github, "verify_state", lambda s: "org_abc")
    _fake_factory(monkeypatch)
    calls: list[dict] = []

    async def fake_complete(session, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(github_account_login="acme")

    monkeypatch.setattr(github_installs, "complete_installation", fake_complete)
    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=update&state=good",
        follow_redirects=False,
    )
    assert response.headers["location"] == "https://app.test/settings/github?installed=true"
    assert calls[0]["github_installation_id"] == 123
