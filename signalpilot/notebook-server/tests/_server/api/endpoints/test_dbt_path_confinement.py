"""Every dbt endpoint that takes a path must answer 400 on an escape.

Auth (covered in ``test_dbt_agent_auth_e2e.py``) bounds *who* may call these
routes; it does not bound *where* they may point. ``POST
/api/dbt/scaffold_project`` with ``parentDir: "/tmp/outside-workspace"``
previously returned ``success: true`` and wrote ``dbt_project.yml``,
``profiles.yml`` and model files outside the workspace.

Handlers are invoked in-process with a real ``starlette.requests.Request``
(``requires()`` asserts the type) carrying the ``edit`` scope, so the
confinement check is what is being measured rather than the auth gate. No
event-loop plugin required.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

starlette_requests = pytest.importorskip("starlette.requests")
endpoints = pytest.importorskip("signalpilot._server.api.endpoints.dbt")

from starlette.authentication import (  # noqa: E402
    AuthCredentials,
    SimpleUser,
)

from signalpilot._server.files.path_confinement import (  # noqa: E402
    WORKSPACE_ROOT_ENV,
)
from signalpilot._utils.http import HTTPException  # noqa: E402


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
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a subprocess was spawned: {args!r}")

    monkeypatch.setattr(subprocess, "run", _explode)


def _request(body: dict[str, Any]) -> Any:
    payload = json.dumps(body).encode()

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return starlette_requests.Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/dbt/test",
            "raw_path": b"/api/dbt/test",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "auth": AuthCredentials(["read", "edit"]),
            "user": SimpleUser("tester"),
        },
        receive,
    )


def _call(handler: Callable[..., Any], body: dict[str, Any]) -> Any:
    return asyncio.run(handler(request=_request(body)))


def _call_json(
    handler: Callable[..., Any], body: dict[str, Any]
) -> dict[str, Any]:
    """Handlers return msgspec structs wrapped by the router into a Response."""
    response = _call(handler, body)
    return json.loads(bytes(response.body))


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


ESCAPES = _escapes(Path("/t"), Path("/t/workspace"))
ESCAPE_IDS = [c.replace("\x00", "NUL") for c in ESCAPES]

# (endpoint handler, request-body key holding the path)
PATH_PARAMETERS = [
    pytest.param(
        endpoints.run_dbt_command,
        {"command": "run"},
        "projectDir",
        id="command.projectDir",
    ),
    pytest.param(
        endpoints.run_dbt_command,
        {"command": "run"},
        "profilesDir",
        id="command.profilesDir",
    ),
    pytest.param(
        endpoints.get_project_info, {}, "projectDir", id="project_info.projectDir"
    ),
    pytest.param(endpoints.get_models, {}, "projectDir", id="models.projectDir"),
    pytest.param(
        endpoints.get_artifact,
        {"artifact": "manifest"},
        "projectDir",
        id="artifact.projectDir",
    ),
    pytest.param(
        endpoints.discover_projects, {}, "rootDir", id="discover.rootDir"
    ),
    pytest.param(
        endpoints.scaffold_project,
        {"projectName": "demo"},
        "parentDir",
        id="scaffold.parentDir",
    ),
    pytest.param(
        endpoints.compile_model_endpoint,
        {"modelName": "m"},
        "projectDir",
        id="compile_model.projectDir",
    ),
    pytest.param(
        endpoints.preview_model_endpoint,
        {"modelName": "m"},
        "projectDir",
        id="preview_model.projectDir",
    ),
]


@pytest.mark.parametrize("handler,base_body,key", PATH_PARAMETERS)
@pytest.mark.parametrize("index", range(len(ESCAPES)), ids=ESCAPE_IDS)
def test_endpoint_rejects_escaping_path(
    handler: Callable[..., Any],
    base_body: dict[str, Any],
    key: str,
    index: int,
    workspace: Path,
    tmp_path: Path,
    no_subprocess: None,
) -> None:
    body = {**base_body, key: _escapes(tmp_path, workspace)[index]}

    with pytest.raises(HTTPException) as excinfo:
        _call(handler, body)

    assert excinfo.value.status_code == 400


@pytest.mark.parametrize(
    "project_name", ["../evil", "../../etc/evil", "nested/../../evil"]
)
def test_scaffold_endpoint_rejects_traversing_project_name(
    project_name: str, workspace: Path, tmp_path: Path
) -> None:
    with pytest.raises(HTTPException) as excinfo:
        _call(
            endpoints.scaffold_project,
            {"projectName": project_name, "parentDir": str(workspace)},
        )

    assert excinfo.value.status_code == 400
    assert not (tmp_path / "evil").exists()


def test_scaffold_endpoint_writes_nothing_outside_the_workspace(
    workspace: Path, tmp_path: Path
) -> None:
    """The proven exploit: a 200 ``success: true`` write outside /workspace."""
    outside = tmp_path / "outside-workspace"

    with pytest.raises(HTTPException):
        _call(
            endpoints.scaffold_project,
            {"projectName": "demo", "parentDir": str(outside)},
        )

    assert list(outside.iterdir()) == []


def test_scaffold_endpoint_rejects_symlink_escape(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-workspace"
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks in this environment: {exc}")

    with pytest.raises(HTTPException) as excinfo:
        _call(
            endpoints.scaffold_project,
            {"projectName": "demo", "parentDir": str(link)},
        )

    assert excinfo.value.status_code == 400
    assert list(outside.iterdir()) == []


# ── Regression guards ────────────────────────────────────────────


def test_scaffold_endpoint_accepts_in_workspace_parent(
    workspace: Path,
) -> None:
    response = _call_json(
        endpoints.scaffold_project,
        {"projectName": "demo", "parentDir": str(workspace / "team")},
    )

    assert response["success"] is True, response.get("error")
    assert (workspace / "team" / "demo" / "dbt_project.yml").is_file()


def test_scaffold_endpoint_accepts_relative_parent(workspace: Path) -> None:
    response = _call_json(
        endpoints.scaffold_project,
        {"projectName": "demo", "parentDir": "team/sub"},
    )

    assert response["success"] is True, response.get("error")
    assert (workspace / "team" / "sub" / "demo" / "dbt_project.yml").is_file()


def test_project_info_endpoint_accepts_nested_project(
    workspace: Path,
) -> None:
    nested = workspace / "team" / "analytics"
    nested.mkdir(parents=True)
    (nested / "dbt_project.yml").write_text(
        "name: demo\nprofile: demo\nconfig-version: 2\n", encoding="utf-8"
    )

    response = _call_json(
        endpoints.get_project_info, {"projectDir": str(nested / "models")}
    )

    assert response["found"] is True
    assert Path(response["projectDir"]) == nested.resolve()
    assert response["projectName"] == "demo"


def test_discover_endpoint_accepts_workspace_root(workspace: Path) -> None:
    nested = workspace / "analytics"
    nested.mkdir()
    (nested / "dbt_project.yml").write_text(
        "name: demo\nprofile: demo\nconfig-version: 2\n", encoding="utf-8"
    )

    response = _call_json(
        endpoints.discover_projects, {"rootDir": str(workspace)}
    )

    assert response["success"] is True
    assert [Path(p["projectDir"]) for p in response["projects"]] == [
        nested.resolve()
    ]


def test_discover_endpoint_defaults_to_the_workspace_root(
    workspace: Path,
) -> None:
    response = _call_json(endpoints.discover_projects, {})

    assert response["success"] is True
    assert Path(response["rootDir"]) == workspace.resolve()
