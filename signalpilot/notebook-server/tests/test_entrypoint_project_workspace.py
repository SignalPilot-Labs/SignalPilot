from __future__ import annotations

import importlib
import subprocess

from signalpilot._server.files.project_sync_boot import _checkout_frozen_commit

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


def test_checkout_frozen_commit_detaches_exact_revision(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "model.sql"
    tracked.write_text("select 1\n")
    subprocess.run(["git", "add", "model.sql"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=tmp_path, check=True)
    frozen = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    tracked.write_text("select 2\n")
    subprocess.run(["git", "commit", "-qam", "second"], cwd=tmp_path, check=True)

    assert _checkout_frozen_commit(tmp_path, frozen)
    assert tracked.read_text() == "select 1\n"
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip() == frozen


def test_checkout_frozen_commit_rejects_non_sha(tmp_path) -> None:
    assert not _checkout_frozen_commit(tmp_path, "main")
