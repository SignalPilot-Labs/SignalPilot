"""Self-heal for a drifted git mirror: the bare repo lives on an ephemeral
volume while the project + GitHub link are durable in the DB, so a linked
project can end up with no mirror. ensure_repo_mirror must reconcile it instead
of dead-ending readiness at "the production branch is not available"."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.git.repos as repos
import gateway.git.sync as sync
import gateway.store.github as gh


def _link():
    return SimpleNamespace(default_branch="main", installation_id="inst", repo_full_name="o/r")


@pytest.mark.asyncio
async def test_healthy_mirror_is_not_recloned(monkeypatch):
    monkeypatch.setattr(sync, "repo_exists", lambda pid: True)
    monkeypatch.setattr(repos, "branch_head_sha", lambda pid, br: "abc123")
    monkeypatch.setattr(gh, "get_repo_link_for_project", AsyncMock(return_value=_link()))
    clone = MagicMock()
    monkeypatch.setattr(repos, "clone_from_remote", clone)

    assert await sync.ensure_repo_mirror(MagicMock(), org_id="o", project_id="p") is True
    clone.assert_not_called()


@pytest.mark.asyncio
async def test_missing_mirror_is_recloned_from_link(monkeypatch):
    state = {"exists": False}
    monkeypatch.setattr(sync, "repo_exists", lambda pid: state["exists"])
    monkeypatch.setattr(repos, "branch_head_sha", lambda pid, br: "sha" if state["exists"] else None)
    monkeypatch.setattr(gh, "get_repo_link_for_project", AsyncMock(return_value=_link()))
    monkeypatch.setattr(gh, "get_installation", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(gh, "get_valid_token", AsyncMock(return_value="tok"))

    calls = {}

    def _clone(pid, url):
        calls["url"] = url
        state["exists"] = True

    monkeypatch.setattr(repos, "clone_from_remote", _clone)
    monkeypatch.setattr(repos, "materialize_local_branches", lambda pid, br: None)

    assert await sync.ensure_repo_mirror(MagicMock(), org_id="o", project_id="p") is True
    assert state["exists"] is True
    assert "x-access-token:tok@github.com/o/r" in calls["url"]  # authed remote


@pytest.mark.asyncio
async def test_missing_mirror_without_link_is_unhealable(monkeypatch):
    monkeypatch.setattr(sync, "repo_exists", lambda pid: False)
    monkeypatch.setattr(repos, "branch_head_sha", lambda pid, br: None)
    monkeypatch.setattr(gh, "get_repo_link_for_project", AsyncMock(return_value=None))
    clone = MagicMock()
    monkeypatch.setattr(repos, "clone_from_remote", clone)

    # No remote to rebuild from (managed/upload project) -> cannot heal, no clone.
    assert await sync.ensure_repo_mirror(MagicMock(), org_id="o", project_id="p") is False
    clone.assert_not_called()


@pytest.mark.asyncio
async def test_reclone_failure_returns_false_not_raise(monkeypatch):
    monkeypatch.setattr(sync, "repo_exists", lambda pid: False)
    monkeypatch.setattr(repos, "branch_head_sha", lambda pid, br: None)
    monkeypatch.setattr(gh, "get_repo_link_for_project", AsyncMock(return_value=_link()))
    monkeypatch.setattr(gh, "get_installation", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(gh, "get_valid_token", AsyncMock(return_value="tok"))

    def _boom(pid, url):
        raise RuntimeError("network down")

    monkeypatch.setattr(repos, "clone_from_remote", _boom)

    # A failed heal is surfaced as False, never an exception that would break
    # the readiness path it is called from.
    assert await sync.ensure_repo_mirror(MagicMock(), org_id="o", project_id="p") is False
