"""Webhook fallback: reconcile_watched_branches + repo_sync_loop config."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.background import loops as loops_module
from gateway.dbt_map import triggers
from gateway.workspace_store.github_sync import ImportResult


def _link(project_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"link-{project_id}", org_id="org", project_id=project_id,
        installation_id="inst", repo_full_name=f"acme/{project_id}", default_branch="main",
    )


def _project(project_id: str, *, settings: dict | None = None, status: str = "active") -> SimpleNamespace:
    return SimpleNamespace(id=project_id, status=status, default_branch="main", settings=settings)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    """Stub the DB, link listing, project lookup, import, and compile scheduler."""
    state: dict = {"links": [], "projects": {}, "imports": {}, "compiles": []}

    @asynccontextmanager
    async def _session():
        yield object()

    monkeypatch.setattr(triggers, "_load_project", AsyncMock(side_effect=lambda s, org, pid: state["projects"].get(pid)))
    monkeypatch.setattr(
        "gateway.db.engine.get_session_factory", lambda: _session, raising=False
    )
    monkeypatch.setattr(
        "gateway.store.github.list_all_active_repo_links", AsyncMock(side_effect=lambda s: list(state["links"]))
    )

    async def _pull(session, link, branch):
        return state["imports"].get((link.project_id, branch))

    monkeypatch.setattr(triggers, "_pull_and_import", _pull)
    monkeypatch.setattr(
        triggers, "schedule_compile",
        lambda org, pid, branch, *, trigger: state["compiles"].append((pid, branch, trigger)),
    )
    return state


@pytest.mark.asyncio
async def test_only_changed_branches_compile(wired) -> None:
    wired["links"] = [_link("p1"), _link("p2")]
    wired["projects"] = {"p1": _project("p1"), "p2": _project("p2")}
    wired["imports"] = {
        ("p1", "main"): ImportResult(imported=True, revision=3, commit_sha="abc"),
        ("p2", "main"): ImportResult(imported=False, revision=0, commit_sha="abc"),
    }
    summary = await triggers.reconcile_watched_branches()
    assert summary == {"checked": 2, "imported": 1, "compiles_triggered": 1, "failed": 0}
    assert wired["compiles"] == [("p1", "main", "sync")]


@pytest.mark.asyncio
async def test_watched_branches_and_compile_flag_are_respected(wired) -> None:
    wired["links"] = [_link("p1")]
    wired["projects"] = {
        "p1": _project("p1", settings={"watched_branches": ["main", "release"], "auto_compile_on_push": False}),
    }
    wired["imports"] = {
        ("p1", "main"): ImportResult(imported=True, revision=1, commit_sha="a"),
        ("p1", "release"): ImportResult(imported=True, revision=1, commit_sha="b"),
    }
    summary = await triggers.reconcile_watched_branches()
    # Both branches imported (workspace kept fresh) but no compile when the flag is off.
    assert summary == {"checked": 1, "imported": 2, "compiles_triggered": 0, "failed": 0}
    assert wired["compiles"] == []


@pytest.mark.asyncio
async def test_failures_and_inactive_projects_do_not_stop_the_sweep(wired) -> None:
    wired["links"] = [_link("dead"), _link("broken"), _link("ok")]
    wired["projects"] = {
        "dead": _project("dead", status="archived"),
        "broken": _project("broken"),
        "ok": _project("ok"),
    }
    wired["imports"] = {
        # "broken" has no entry -> _pull_and_import returns None (failure)
        ("ok", "main"): ImportResult(imported=True, revision=7, commit_sha="z"),
    }
    summary = await triggers.reconcile_watched_branches()
    assert summary == {"checked": 2, "imported": 1, "compiles_triggered": 1, "failed": 1}
    assert wired["compiles"] == [("ok", "main", "sync")]


def test_interval_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SP_REPO_SYNC_INTERVAL_SECONDS", raising=False)
    assert loops_module._repo_sync_interval_seconds() == 900
    monkeypatch.setenv("SP_REPO_SYNC_INTERVAL_SECONDS", "0")
    assert loops_module._repo_sync_interval_seconds() == 0
    monkeypatch.setenv("SP_REPO_SYNC_INTERVAL_SECONDS", "-5")
    assert loops_module._repo_sync_interval_seconds() == 0
    monkeypatch.setenv("SP_REPO_SYNC_INTERVAL_SECONDS", "junk")
    assert loops_module._repo_sync_interval_seconds() == 900


@pytest.mark.asyncio
async def test_loop_exits_immediately_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SP_REPO_SYNC_INTERVAL_SECONDS", "0")
    await loops_module.repo_sync_loop()  # returns instead of sleeping forever
