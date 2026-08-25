"""Every filesystem parameter the dbt runner takes must stay in the workspace.

The runner is confined in addition to the HTTP handlers because it has
in-process callers (``_server/ai/claude_agent.py``) that never cross the API
boundary, and because dbt itself executes project-supplied Jinja and run
hooks -- the tree it is pointed at is a code-execution surface, not just a
read surface.

Escape assertions check that no subprocess was spawned and that nothing was
written outside the root, not merely that an error came back.

Runs anywhere the package imports -- no server, no dbt, no network.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

runner = pytest.importorskip("signalpilot._dbt.runner")

from signalpilot._server.files.path_confinement import (  # noqa: E402
    WORKSPACE_ROOT_ENV,
)
from signalpilot._utils.http import HTTPException  # noqa: E402

DBT_PROJECT_YML = "name: demo\nprofile: demo\nconfig-version: 2\n"


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "workspace-evil").mkdir()
    (tmp_path / "outside-workspace").mkdir()
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(root))
    monkeypatch.chdir(root)
    return root


@pytest.fixture()
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Any subprocess spawn is a hard failure; records attempts."""
    calls: list[object] = []

    def _explode(*args: object, **kwargs: object) -> None:
        calls.append(args[0] if args else kwargs.get("args"))
        raise AssertionError(f"a subprocess was spawned: {args!r}")

    monkeypatch.setattr(runner.subprocess, "run", _explode)
    return calls


def _escapes(tmp_path: Path, root: Path) -> list[str]:
    cases = [
        "/tmp/outside-workspace",
        str(tmp_path / "outside-workspace"),
        str(root) + "-evil",
        "../../etc",
        "workspace/../../etc",
        "nested\x00/etc",
    ]
    cases.append("C:\\Windows\\Temp" if os.name == "nt" else "/etc")
    return cases


def _ids(cases: list[str]) -> list[str]:
    return [c.replace("\x00", "NUL") for c in cases]


ESCAPES = _escapes(Path("/t"), Path("/t/workspace"))


@pytest.fixture()
def escapes(tmp_path: Path, workspace: Path) -> list[str]:
    return _escapes(tmp_path, workspace)


@pytest.mark.parametrize("index", range(len(ESCAPES)), ids=_ids(ESCAPES))
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda path: runner.find_dbt_project(path), id="find_dbt_project"
        ),
        pytest.param(
            lambda path: runner.parse_dbt_project_yml(path),
            id="parse_dbt_project_yml",
        ),
        pytest.param(
            lambda path: runner.discover_dbt_projects(path),
            id="discover_dbt_projects",
        ),
        pytest.param(
            lambda path: runner.get_manifest(path), id="get_manifest"
        ),
        pytest.param(
            lambda path: runner.get_run_results(path), id="get_run_results"
        ),
        pytest.param(
            lambda path: runner.get_graph_summary(path), id="get_graph_summary"
        ),
        pytest.param(lambda path: runner.list_models(path), id="list_models"),
        pytest.param(
            lambda path: runner.run_dbt_command_sync("run", project_dir=path),
            id="run_dbt_command_sync.project_dir",
        ),
        pytest.param(
            lambda path: runner.run_dbt_command_sync(
                "run", project_dir=None, profiles_dir=path
            ),
            id="run_dbt_command_sync.profiles_dir",
        ),
        pytest.param(
            lambda path: runner.scaffold_dbt_project("demo", parent_dir=path),
            id="scaffold_dbt_project.parent_dir",
        ),
        pytest.param(
            lambda path: runner.compile_model("m", project_dir=path),
            id="compile_model.project_dir",
        ),
        pytest.param(
            lambda path: runner.preview_model("m", project_dir=path),
            id="preview_model.project_dir",
        ),
    ],
)
def test_runner_rejects_escaping_path(
    call: object,
    index: int,
    escapes: list[str],
    no_subprocess: list[object],
) -> None:
    with pytest.raises(HTTPException) as excinfo:
        call(escapes[index])  # type: ignore[operator]

    assert excinfo.value.status_code == 400
    assert no_subprocess == []


@pytest.mark.parametrize(
    "project_name",
    ["../evil", "../../etc/evil", "nested/../../evil"],
)
def test_scaffold_rejects_traversing_project_name(
    project_name: str, workspace: Path, tmp_path: Path
) -> None:
    """``project_name`` is a path component, so it traverses on its own."""
    with pytest.raises(HTTPException) as excinfo:
        runner.scaffold_dbt_project(project_name, parent_dir=str(workspace))

    assert excinfo.value.status_code == 400
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "etc").exists()


def test_scaffold_writes_nothing_outside_the_root(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-workspace"

    with pytest.raises(HTTPException):
        runner.scaffold_dbt_project("demo", parent_dir=str(outside))

    assert list(outside.iterdir()) == []


def test_find_dbt_project_stops_at_the_workspace_boundary(
    workspace: Path, tmp_path: Path
) -> None:
    """The upward walk must not surface a project from above the root."""
    (tmp_path / "dbt_project.yml").write_text(DBT_PROJECT_YML, encoding="utf-8")
    deep = workspace / "a" / "b"
    deep.mkdir(parents=True)

    assert runner.find_dbt_project(str(deep)) is None


def test_discover_skips_symlinks_out_of_the_workspace(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-workspace"
    (outside / "sneaky").mkdir()
    (outside / "sneaky" / "dbt_project.yml").write_text(
        DBT_PROJECT_YML, encoding="utf-8"
    )
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks in this environment: {exc}")

    found = runner.discover_dbt_projects(str(workspace))

    assert found == []


def test_symlinked_project_dir_is_rejected(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-workspace"
    (outside / "dbt_project.yml").write_text(DBT_PROJECT_YML, encoding="utf-8")
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks in this environment: {exc}")

    for call in (
        runner.find_dbt_project,
        runner.parse_dbt_project_yml,
        runner.get_manifest,
    ):
        with pytest.raises(HTTPException) as excinfo:
            call(str(link))
        assert excinfo.value.status_code == 400, call.__name__


# ── Regression guards: legitimate in-workspace use must keep working ──


def test_scaffold_in_workspace_still_works(workspace: Path) -> None:
    project_dir, created = runner.scaffold_dbt_project(
        "demo", parent_dir=str(workspace)
    )

    assert Path(project_dir) == (workspace / "demo").resolve()
    assert (workspace / "demo" / "dbt_project.yml").is_file()
    assert any(f.endswith("profiles.yml") for f in created)


def test_scaffold_in_place_still_works(workspace: Path) -> None:
    project_dir, _ = runner.scaffold_dbt_project(
        ".", parent_dir=str(workspace / "inplace")
    )

    assert Path(project_dir) == (workspace / "inplace").resolve()
    assert (workspace / "inplace" / "dbt_project.yml").is_file()


def test_scaffold_accepts_relative_parent_dir(workspace: Path) -> None:
    project_dir, _ = runner.scaffold_dbt_project("demo", parent_dir="sub/dir")

    assert Path(project_dir) == (workspace / "sub" / "dir" / "demo").resolve()


def test_find_dbt_project_finds_nested_project(workspace: Path) -> None:
    nested = workspace / "team" / "analytics"
    nested.mkdir(parents=True)
    (nested / "dbt_project.yml").write_text(DBT_PROJECT_YML, encoding="utf-8")

    assert runner.find_dbt_project(str(nested / "models" / "staging")) == str(
        nested.resolve()
    )


def test_discover_finds_nested_projects(workspace: Path) -> None:
    nested = workspace / "team" / "analytics"
    nested.mkdir(parents=True)
    (nested / "dbt_project.yml").write_text(DBT_PROJECT_YML, encoding="utf-8")

    found = runner.discover_dbt_projects(str(workspace))

    assert [p.project_dir for p in found] == [str(nested.resolve())]


def test_discover_defaults_to_the_workspace_root(workspace: Path) -> None:
    nested = workspace / "analytics"
    nested.mkdir()
    (nested / "dbt_project.yml").write_text(DBT_PROJECT_YML, encoding="utf-8")

    found = runner.discover_dbt_projects()

    assert [p.project_dir for p in found] == [str(nested.resolve())]




def test_run_dbt_command_accepts_in_workspace_dirs(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    class _Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd: list[str], **kwargs: object) -> _Result:
        seen["cmd"] = cmd
        seen["cwd"] = kwargs.get("cwd")
        return _Result()

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/dbt")
    monkeypatch.setattr(runner.subprocess, "run", _fake_run)

    project = workspace / "demo"
    project.mkdir()
    result = runner.run_dbt_command_sync(
        "run", project_dir=str(project), profiles_dir=str(project)
    )

    assert result.success is True
    assert "--project-dir" in seen["cmd"]  # type: ignore[operator]
    assert "--profiles-dir" in seen["cmd"]  # type: ignore[operator]
    assert Path(str(seen["cwd"])) == project.resolve()
