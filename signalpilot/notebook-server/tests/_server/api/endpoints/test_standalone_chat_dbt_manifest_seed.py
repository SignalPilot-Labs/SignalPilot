"""Seeding target/manifest.json: which directory it lands in.

The dbt-map row records the directory it compiled, but rows from before that
column existed carry NULL. Guessing from the tree only works when the repo
holds exactly one dbt project; the dumpsters repo holds five, so a NULL used
to skip the seed silently and the agent fell back to bare `dbt parse`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from signalpilot._server.api.endpoints import (
    standalone_chat_dbt_manifest as mod,
)

if TYPE_CHECKING:
    from pathlib import Path

PROJECTS = ("dumpsters_dbt", "dumpsters_dbt_broken", "dumpsters_dbt_exec", "dumpsters_dbt_simplified")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    for name in PROJECTS:
        (tmp_path / name).mkdir()
        (tmp_path / name / "dbt_project.yml").write_text("name: x\n", encoding="utf-8")
    return tmp_path


def test_row_directory_is_used_when_present(checkout: Path) -> None:
    assert mod._dbt_project_directory(checkout, "dumpsters_dbt_simplified") == (
        checkout / "dumpsters_dbt_simplified"
    ).resolve()


def test_tree_guess_gives_up_with_several_projects(checkout: Path) -> None:
    """The reason the fallback below exists."""
    assert mod._dbt_project_directory(checkout, None) is None


def test_tree_guess_still_works_for_a_single_project(tmp_path: Path) -> None:
    (tmp_path / "only").mkdir()
    (tmp_path / "only" / "dbt_project.yml").write_text("name: x\n", encoding="utf-8")
    assert mod._dbt_project_directory(tmp_path, None) == tmp_path / "only"


def test_empty_string_means_the_repo_root(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: root\n", encoding="utf-8")
    assert mod._dbt_project_directory(tmp_path, "") == tmp_path


def test_directory_escaping_the_checkout_is_refused(checkout: Path) -> None:
    assert mod._dbt_project_directory(checkout, "../elsewhere") is None


def test_configured_dir_is_read_from_the_gateway(monkeypatch) -> None:
    calls: list[str] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"dbt_project_dir": "dumpsters_dbt_simplified"}

    def fake_get(url: str, **_kw: object) -> _Resp:
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(mod.httpx, "get", fake_get)
    got = mod._configured_dbt_project_dir(
        project_id="p1", branch="main", gateway_url="http://gw", gateway_token="t"
    )
    assert got == "dumpsters_dbt_simplified"
    assert calls == ["http://gw/api/workspace-projects/p1/dbt-project-dir"]


def test_configured_dir_failure_is_swallowed(monkeypatch) -> None:
    def boom(*_a: object, **_kw: object) -> None:
        raise RuntimeError("gateway down")

    monkeypatch.setattr(mod.httpx, "get", boom)
    assert (
        mod._configured_dbt_project_dir(
            project_id="p1", branch="main", gateway_url="http://gw", gateway_token="t"
        )
        is None
    )
