from __future__ import annotations

import subprocess


def test_init_bare_repo_creates_branchable_default(monkeypatch, tmp_path) -> None:
    from gateway.git import repos

    project_id = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr(repos, "REPOS_ROOT", tmp_path)

    repos.init_bare_repo(project_id)

    main_sha = repos.branch_head_sha(project_id, "main")
    assert main_sha
    assert repos.ensure_branch_from(project_id, "analysis/slack/test", "main") == main_sha
    assert repos.branch_head_sha(project_id, "analysis/slack/test") == main_sha


def test_init_bare_repo_repairs_existing_empty_repo(monkeypatch, tmp_path) -> None:
    from gateway.git import repos

    project_id = "00000000-0000-0000-0000-000000000002"
    monkeypatch.setattr(repos, "REPOS_ROOT", tmp_path)
    path = tmp_path / f"{project_id}.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    repos.init_bare_repo(project_id)

    main_sha = repos.branch_head_sha(project_id, "main")
    assert main_sha
    assert repos.ensure_branch_from(project_id, "analysis/slack/test", "main") == main_sha
