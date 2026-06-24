from __future__ import annotations

from types import SimpleNamespace

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


def test_github_callback_invalid_state_redirects_to_settings_error(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get(
        "/auth/github/callback?installation_id=123&setup_action=install&state=bad-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.test/settings/github?error=oauth_state_invalid"
