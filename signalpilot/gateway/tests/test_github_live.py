"""Live (real-network) tests for the GitHub App integration — SP-SEC-004.

These tests talk to real GitHub using the real dev GitHub App credentials.
They are skipped automatically when the credentials or the network are absent,
so CI without secrets stays green.

Credentials are read from the environment by NAME only:

    SP_GITHUB_APP_ID
    SP_GITHUB_APP_PRIVATE_KEY      (may contain literal \\n escapes)
    SP_GITHUB_APP_CLIENT_ID
    SP_GITHUB_APP_CLIENT_SECRET

If they are not already exported, the module makes a best-effort attempt to
load the repo-root ``.env``. No credential value is ever printed, logged,
asserted against a literal, or written to disk by these tests.

WHAT IS *NOT* COVERED HERE (requires a human):
  The browser consent leg — visiting the GitHub App install/authorize page,
  approving it, and having GitHub redirect back with a real single-use ``code``.
  A real ``code`` cannot be obtained non-interactively, so the success half of
  the callback is covered only by the mocked matrix in
  ``test_github_oauth_callback.py``. See the report / HUMAN-TASKS notes.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CRED_VARS = (
    "SP_GITHUB_APP_ID",
    "SP_GITHUB_APP_PRIVATE_KEY",
    "SP_GITHUB_APP_CLIENT_ID",
    "SP_GITHUB_APP_CLIENT_SECRET",
)


def _load_repo_env() -> None:
    """Best-effort: populate missing credential vars from the repo-root .env.

    Never overrides an already-exported value; never echoes anything.
    """
    if all(os.getenv(name) for name in CRED_VARS):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a gateway dependency
        return
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            if all(os.getenv(name) for name in CRED_VARS):
                return


_load_repo_env()


def _creds_present() -> bool:
    return all(os.getenv(name) for name in CRED_VARS)


def _network_ok() -> bool:
    try:
        httpx.get("https://api.github.com/zen", timeout=8)
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not (_creds_present() and _network_ok()),
    reason="GitHub App dev credentials (see CRED_VARS) or network access unavailable",
)


def _private_key() -> str:
    raw = os.environ["SP_GITHUB_APP_PRIVATE_KEY"]
    return raw.replace("\\n", "\n")


class TestGitHubAppJWTLive:
    def test_app_jwt_authenticates_and_app_id_matches(self) -> None:
        """generate_app_jwt produces a token GitHub accepts on GET /app."""
        from gateway.github_client import generate_app_jwt

        app_id = os.environ["SP_GITHUB_APP_ID"]
        app_jwt = generate_app_jwt(app_id, _private_key())

        resp = httpx.get(
            "https://api.github.com/app",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
            timeout=20,
        )

        assert resp.status_code == 200, f"GET /app returned {resp.status_code}"
        body = resp.json()
        assert str(body["id"]) == str(app_id)
        assert body["slug"], "app slug missing from GET /app response"

    def test_app_jwt_can_enumerate_its_own_installations(self) -> None:
        """The app JWT can list installations — this is the privilege the fix gates."""
        from gateway.github_client import generate_app_jwt

        app_jwt = generate_app_jwt(os.environ["SP_GITHUB_APP_ID"], _private_key())

        resp = httpx.get(
            "https://api.github.com/app/installations",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
            timeout=20,
        )

        assert resp.status_code == 200
        installations = resp.json()
        assert isinstance(installations, list)
        # The app JWT sees every tenant installation regardless of who is calling
        # the OAuth callback. That is exactly why installation_id must be bound to
        # the authorizing user before create_installation_token is reached.
        assert all("id" in inst for inst in installations)


class TestCodeExchangeLive:
    async def test_real_client_credentials_are_accepted_by_github(self) -> None:
        """End-to-end proof of the code-exchange leg without a browser.

        GitHub distinguishes the two failure modes:
          - ``incorrect_client_credentials`` → our client id/secret are wrong.
          - ``bad_verification_code``        → credentials fine, the *code* is bad.

        A dummy code must therefore yield ``bad_verification_code``.
        """
        from gateway.github_client import exchange_code_for_token

        result = await exchange_code_for_token(
            os.environ["SP_GITHUB_APP_CLIENT_ID"],
            os.environ["SP_GITHUB_APP_CLIENT_SECRET"],
            "definitely-not-a-real-oauth-code",
        )

        assert result.get("error") == "bad_verification_code", (
            "expected bad_verification_code; got error="
            f"{result.get('error')!r} (incorrect_client_credentials means the "
            "SP_GITHUB_APP_CLIENT_ID / SP_GITHUB_APP_CLIENT_SECRET pair is wrong)"
        )
        assert "access_token" not in result

    async def test_exchange_response_contains_no_client_secret(self) -> None:
        """Sanity: GitHub never echoes the secret back, so nothing to leak downstream."""
        from gateway.github_client import exchange_code_for_token

        secret = os.environ["SP_GITHUB_APP_CLIENT_SECRET"]
        result = await exchange_code_for_token(
            os.environ["SP_GITHUB_APP_CLIENT_ID"], secret, "definitely-not-a-real-oauth-code"
        )
        assert secret not in str(result)


class TestRepositoryScopedMintLive:
    """SP-SEC-005: prove GitHub actually honours the repository_ids body.

    We deliberately request a repository id the installation cannot access, so
    GitHub rejects the mint (422) and NO usable token is ever produced. A
    body-less POST would have returned 201 with a full-installation token —
    which is precisely the amplification being fixed, so this asserts the body
    reaches GitHub and is enforced there, not just in our code.
    """

    async def test_scoped_mint_body_is_enforced_by_github(self) -> None:
        from gateway.github_client import generate_app_jwt

        app_jwt = generate_app_jwt(os.environ["SP_GITHUB_APP_ID"], _private_key())
        headers = {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get("https://api.github.com/app/installations", headers=headers)
            resp.raise_for_status()
            installations = resp.json()
            if not installations:
                pytest.skip("no live installations to test against")
            installation_id = installations[0]["id"]

            scoped = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers=headers,
                json={"repository_ids": [1]},  # id 1 is not in any of our installations
            )

        assert scoped.status_code == 422, (
            "GitHub accepted a scoped mint for an inaccessible repository id; "
            "repository_ids may not be enforced as assumed"
        )
        assert "repository" in scoped.json().get("message", "").lower()
        assert "token" not in scoped.json()

    async def test_create_installation_token_refuses_empty_scope_before_any_network_call(self) -> None:
        """The client-side guard fires before a request is ever sent."""
        from gateway.github_client import create_installation_token

        with pytest.raises(ValueError, match="non-empty repository_ids"):
            await create_installation_token("unused-jwt", 1, repository_ids=[])


class TestUserInstallationsLive:
    async def test_invalid_user_token_cannot_enumerate_installation_repositories(self) -> None:
        """list_user_installation_repositories fails closed on a bad user token."""
        from gateway.github_client import list_user_installation_repositories

        with pytest.raises(httpx.HTTPStatusError) as exc:
            await list_user_installation_repositories("ghu_this_token_is_not_valid_at_all", 1)

        assert exc.value.response.status_code == 401

    async def test_invalid_user_token_raises_auth_error_not_crash(self) -> None:
        """list_user_installations against a bogus token: clean 401, no crash."""
        from gateway.github_client import list_user_installations

        with pytest.raises(httpx.HTTPStatusError) as exc:
            await list_user_installations("ghu_this_token_is_not_valid_at_all")

        assert exc.value.response.status_code == 401

    async def test_callback_rejects_when_user_token_is_invalid(self) -> None:
        """The 401 above must surface as a redirect rejection, not a 500.

        Real network on the ``/user/installations`` leg; the code-exchange leg is
        stubbed because a real single-use code needs a browser.
        """
        from gateway import github_client
        from gateway.api import _oauth_state, github
        from gateway.api._oauth_state import make_state

        monkey = pytest.MonkeyPatch()
        try:
            monkey.setenv("SP_ENCRYPTION_KEY", "live-test-state-signing-key")
            monkey.setattr(_oauth_state, "_HMAC_KEY", None)
            monkey.setattr(_oauth_state, "_NONCE_STORE", _oauth_state._NonceStore())
            monkey.setattr(
                github,
                "get_github_settings",
                lambda: SimpleNamespace(
                    is_configured=True,
                    sp_web_url="https://app.test",
                    sp_github_app_id=os.environ["SP_GITHUB_APP_ID"],
                    sp_github_app_client_id=os.environ["SP_GITHUB_APP_CLIENT_ID"],
                    sp_github_app_client_secret=os.environ["SP_GITHUB_APP_CLIENT_SECRET"],
                    sp_github_app_private_key=_private_key(),
                ),
            )
            monkey.setattr(github, "is_cloud_mode", lambda: True)

            async def stub_exchange(client_id, client_secret, code):
                return {"access_token": "ghu_this_token_is_not_valid_at_all"}

            monkey.setattr(github_client, "exchange_code_for_token", stub_exchange)

            minted: list[int] = []

            async def spy_create(app_jwt, installation_id, *, repository_ids):
                minted.append(installation_id)
                raise AssertionError("must not be reached")

            async def spy_create_unrestricted(app_jwt, installation_id):
                minted.append(installation_id)
                raise AssertionError("must not be reached")

            monkey.setattr(github_client, "create_installation_token", spy_create)
            monkey.setattr(
                github_client, "create_unrestricted_installation_token", spy_create_unrestricted
            )

            app = FastAPI()
            app.include_router(github.router)
            client = TestClient(app, raise_server_exceptions=False)

            response = client.get(
                "/auth/github/callback?installation_id=1&setup_action=install"
                f"&state={make_state('org_live_test')}&code=dummy",
                follow_redirects=False,
            )

            assert response.status_code == 302
            assert response.headers["location"] == (
                "https://app.test/settings/github?error=oauth_verification_failed"
            )
            assert minted == [], "an installation token was minted despite an unusable user token"
        finally:
            monkey.undo()
