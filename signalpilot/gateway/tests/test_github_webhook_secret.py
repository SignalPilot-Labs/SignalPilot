"""Tests that /api/github/webhook is closed unless a webhook secret is set.

The route is auth-exempt, so the HMAC signature is the only sender
authentication it has — in every deployment mode.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.api import github_bot
from gateway.config.github_bot import GitHubBotSettings

_PING_BODY = json.dumps({"zen": "keep it logically awesome"}).encode()


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(github_bot.router)
    monkeypatch.setattr(github_bot, "schedule_scan", lambda *a, **k: None)
    with TestClient(app) as c:
        yield c


def _set_secret(monkeypatch, secret: str) -> None:
    monkeypatch.setattr(
        github_bot,
        "get_github_bot_settings",
        lambda: GitHubBotSettings(SP_GITHUB_WEBHOOK_SECRET=secret),
    )


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestSecretRequired:
    @pytest.mark.parametrize("mode", ["local", "cloud"])
    def test_route_disabled_without_secret(self, client, monkeypatch, mode: str) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", mode)
        _set_secret(monkeypatch, "")
        resp = client.post(
            "/api/github/webhook",
            content=_PING_BODY,
            headers={"x-github-event": "ping"},
        )
        assert resp.status_code == 503

    def test_unsigned_delivery_rejected_in_local_mode(self, client, monkeypatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        _set_secret(monkeypatch, "s3cret")
        resp = client.post(
            "/api/github/webhook",
            content=_PING_BODY,
            headers={"x-github-event": "ping"},
        )
        assert resp.status_code == 401

    def test_pull_request_scan_not_scheduled_without_signature(self, client, monkeypatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        _set_secret(monkeypatch, "s3cret")
        scheduled: list[tuple] = []
        monkeypatch.setattr(github_bot, "schedule_scan", lambda *a: scheduled.append(a))

        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/dbt"},
                "pull_request": {"number": 7},
            }
        ).encode()
        resp = client.post(
            "/api/github/webhook",
            content=body,
            headers={"x-github-event": "pull_request"},
        )
        assert resp.status_code == 401
        assert scheduled == []

    def test_wrong_signature_rejected(self, client, monkeypatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        _set_secret(monkeypatch, "s3cret")
        resp = client.post(
            "/api/github/webhook",
            content=_PING_BODY,
            headers={
                "x-github-event": "ping",
                "x-hub-signature-256": _sign("wrong-secret", _PING_BODY),
            },
        )
        assert resp.status_code == 401

    def test_signed_ping_accepted(self, client, monkeypatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        _set_secret(monkeypatch, "s3cret")
        resp = client.post(
            "/api/github/webhook",
            content=_PING_BODY,
            headers={
                "x-github-event": "ping",
                "x-hub-signature-256": _sign("s3cret", _PING_BODY),
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "pong": True}


class TestConstantTimeComparison:
    def test_verify_signature_uses_compare_digest(self) -> None:
        import inspect

        assert "compare_digest" in inspect.getsource(github_bot._verify_signature)
