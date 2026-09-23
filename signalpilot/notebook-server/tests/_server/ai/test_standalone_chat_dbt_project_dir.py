"""Which dbt project a chat reads: the org's configured directory wins.

A repo can hold several dbt projects (dumpsters_dbt and
dumpsters_dbt_simplified). The filesystem scan picks the alphabetically first
one, which is how a chat ended up reading a project whose models were never
built. The configured directory — the same one the dbt map compile and
dbt run use — takes precedence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from signalpilot._server.ai import standalone_chat_dbt as mod

if TYPE_CHECKING:
    from pathlib import Path


def _project(root: Path, name: str) -> Path:
    d = root / name
    (d / "models").mkdir(parents=True)
    (d / "dbt_project.yml").write_text(f"name: {name}\nprofile: {name}\n", encoding="utf-8")
    return d


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _project(tmp_path, "dumpsters_dbt")
    _project(tmp_path, "dumpsters_dbt_simplified")
    return tmp_path


def _configured(monkeypatch, value, raises: Exception | None = None):
    from signalpilot._dbt import materialize

    def fake(**_kw: object) -> str | None:
        if raises is not None:
            raise raises
        return value

    monkeypatch.setattr(materialize, "resolve_dbt_project_dir", fake)


def test_configured_dir_wins_over_the_alphabetical_scan(repo, monkeypatch) -> None:
    _configured(monkeypatch, "dumpsters_dbt_simplified")
    assert mod._resolve_dbt_project_dir(repo) == (repo / "dumpsters_dbt_simplified").resolve()


def test_scan_picks_the_wrong_project_without_a_setting(repo, monkeypatch) -> None:
    """Documents the fallback: shallowest-then-alphabetical, hence dumpsters_dbt."""
    _configured(monkeypatch, None)
    assert mod._resolve_dbt_project_dir(repo) == repo / "dumpsters_dbt"


def test_empty_string_means_the_repo_root(tmp_path, monkeypatch) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: root\n", encoding="utf-8")
    _project(tmp_path, "nested")
    _configured(monkeypatch, "")
    assert mod._resolve_dbt_project_dir(tmp_path) == tmp_path.resolve()


def test_gateway_failure_falls_back_to_the_scan(repo, monkeypatch) -> None:
    _configured(monkeypatch, None, raises=RuntimeError("no gateway session"))
    assert mod._resolve_dbt_project_dir(repo) == repo / "dumpsters_dbt"


def test_stale_setting_falls_back_instead_of_failing(repo, monkeypatch) -> None:
    """A setting naming a directory that is not in this checkout must not
    break the chat: the map compile behaves the same way."""
    _configured(monkeypatch, "dumpsters_dbt_deleted")
    assert mod._resolve_dbt_project_dir(repo) == repo / "dumpsters_dbt"


def test_setting_escaping_the_checkout_is_refused(repo, monkeypatch) -> None:
    _configured(monkeypatch, "../../etc")
    assert mod._resolve_dbt_project_dir(repo) == repo / "dumpsters_dbt"


def test_no_dbt_project_anywhere_returns_none(tmp_path, monkeypatch) -> None:
    _configured(monkeypatch, None)
    assert mod._resolve_dbt_project_dir(tmp_path) is None


# --- the agent prompt names the directory too ---------------------------------
#
# inspect_dbt resolving correctly is not enough: the agent also reads files
# with Read/Glob/Bash, so the prompt has to say which folder is the project.


def test_prompt_names_the_configured_dbt_directory(monkeypatch) -> None:
    from signalpilot._dbt import materialize
    from signalpilot._server.api.endpoints import (
        standalone_chat_prompt as prompt_mod,
    )

    monkeypatch.setattr(materialize, "resolve_dbt_project_dir", lambda **_k: "dumpsters_dbt_simplified")
    line = prompt_mod._dbt_project_dir_line()
    assert "dbt project directory: dumpsters_dbt_simplified" in line
    assert "other folders in this repo may hold" in line


def test_prompt_calls_the_repo_root_by_name(monkeypatch) -> None:
    from signalpilot._dbt import materialize
    from signalpilot._server.api.endpoints import (
        standalone_chat_prompt as prompt_mod,
    )

    monkeypatch.setattr(materialize, "resolve_dbt_project_dir", lambda **_k: "")
    assert "dbt project directory: the repository root" in prompt_mod._dbt_project_dir_line()


@pytest.mark.parametrize("outcome", ["unset", "unreachable"])
def test_prompt_omits_the_line_rather_than_failing(monkeypatch, outcome: str) -> None:
    from signalpilot._dbt import materialize
    from signalpilot._server.api.endpoints import (
        standalone_chat_prompt as prompt_mod,
    )

    def fake(**_kw: object) -> str | None:
        if outcome == "unreachable":
            raise RuntimeError("no gateway session")
        return None

    monkeypatch.setattr(materialize, "resolve_dbt_project_dir", fake)
    assert prompt_mod._dbt_project_dir_line() == ""
