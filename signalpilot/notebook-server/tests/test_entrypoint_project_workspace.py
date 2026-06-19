from __future__ import annotations

import importlib


entrypoint = importlib.import_module("signalpilot._server.entrypoint")


def test_synced_project_workspace_finds_cloned_project(tmp_path, monkeypatch) -> None:
    project_id = "ba67f74b-370d-4200-82b0-863b2bc764eb"
    project_root = tmp_path / ".sp" / "projects" / project_id / "demo-project"
    (project_root / ".git").mkdir(parents=True)

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SP_PROJECT_ID", project_id)

    assert entrypoint._synced_project_workspace() == str(project_root)


def test_rewrite_workspace_args_replaces_default_workspace() -> None:
    args = [
        "--host",
        "0.0.0.0",
        "--port",
        "2718",
        "/workspace",
    ]

    assert entrypoint._rewrite_workspace_args(args, "/home/notebook/.sp/projects/p/demo") == [
        "--host",
        "0.0.0.0",
        "--port",
        "2718",
        "/home/notebook/.sp/projects/p/demo",
    ]

