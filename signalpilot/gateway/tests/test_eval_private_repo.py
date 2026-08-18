"""Verify private GitHub repository binding for evaluation sets."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from gateway.api.eval_runs import EvalConfig, _verify_private_eval_repo
from gateway.evals import runner
from gateway.store import github as github_store


def _config(**updates) -> EvalConfig:
    values = {
        "repo_url": "https://github.com/acme/private-evals",
        "repo_installation_id": "installation-1",
        "repo_id": 42,
        "connection": "warehouse",
    }
    values.update(updates)
    return EvalConfig(**values)


def test_private_binding_requires_both_identifiers() -> None:
    with pytest.raises(ValidationError):
        _config(repo_id=None)


@pytest.mark.asyncio
async def test_private_binding_verifies_repo_and_canonicalizes_url(monkeypatch) -> None:
    installation = SimpleNamespace(status="active")

    async def get_installation(*args, **kwargs):
        return installation

    async def get_valid_token(*args, **kwargs):
        return "installation-token"

    async def get_repos(token):
        assert token == "installation-token"
        return [{"id": 42, "full_name": "acme/private-evals"}]

    monkeypatch.setattr(github_store, "get_installation", get_installation)
    monkeypatch.setattr(github_store, "get_valid_token", get_valid_token)
    monkeypatch.setattr("gateway.github_client.list_installation_repos", get_repos)
    store = SimpleNamespace(session=object(), org_id="org-a")

    verified = await _verify_private_eval_repo(store, _config())

    assert verified.repo_url == "https://github.com/acme/private-evals.git"


@pytest.mark.asyncio
async def test_private_binding_rejects_repo_outside_installation(monkeypatch) -> None:
    installation = SimpleNamespace(status="active")

    async def get_installation(*args, **kwargs):
        return installation

    async def get_valid_token(*args, **kwargs):
        return "installation-token"

    async def get_repos(token):
        return [{"id": 99, "full_name": "acme/other"}]

    monkeypatch.setattr(github_store, "get_installation", get_installation)
    monkeypatch.setattr(github_store, "get_valid_token", get_valid_token)
    monkeypatch.setattr("gateway.github_client.list_installation_repos", get_repos)
    store = SimpleNamespace(session=object(), org_id="org-a")

    with pytest.raises(HTTPException) as exc:
        await _verify_private_eval_repo(store, _config())

    assert exc.value.status_code == 422


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_clone_uses_only_the_bound_org_installation(monkeypatch) -> None:
    installation = SimpleNamespace(status="active", authorized_repository_ids=[42])

    async def get_installation(*args, **kwargs):
        assert kwargs == {"org_id": "org-a", "installation_id": "installation-1"}
        return installation

    async def get_valid_token(*args, **kwargs):
        return "bound-token"

    monkeypatch.setattr(runner, "get_session_factory", lambda: lambda: _SessionContext())
    monkeypatch.setattr(github_store, "get_installation", get_installation)
    monkeypatch.setattr(github_store, "get_valid_token", get_valid_token)

    clone_url = await runner._authed_clone_url(
        "org-a",
        "https://github.com/acme/private-evals.git",
        repo_installation_id="installation-1",
        repo_id=42,
    )

    assert clone_url == "https://x-access-token:bound-token@github.com/acme/private-evals.git"


@pytest.mark.asyncio
async def test_clone_rejects_repo_outside_captured_scope(monkeypatch) -> None:
    installation = SimpleNamespace(status="active", authorized_repository_ids=[99])

    async def get_installation(*args, **kwargs):
        return installation

    monkeypatch.setattr(runner, "get_session_factory", lambda: lambda: _SessionContext())
    monkeypatch.setattr(github_store, "get_installation", get_installation)

    with pytest.raises(runner.RepoRefused):
        await runner._authed_clone_url(
            "org-a",
            "https://github.com/acme/private-evals.git",
            repo_installation_id="installation-1",
            repo_id=42,
        )
