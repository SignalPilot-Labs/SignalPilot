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


def _make_github_style_remote(tmp_path, files: dict[str, str]) -> str:
    """A local 'GitHub' repo with real content on main."""
    src = tmp_path / "github-src"
    src.mkdir()
    subprocess.run(["git", "init", "--initial-branch", "main", str(src)], check=True, capture_output=True)
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    env_args = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", *env_args, "-C", str(src), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", *env_args, "-C", str(src), "commit", "-m", "real content"], check=True, capture_output=True)
    return str(src)


def test_linking_repo_to_fresh_project_adopts_remote_content(monkeypatch, tmp_path) -> None:
    """The pristine 'Initial empty project' scaffold must not block the import.

    Regression: the scaffold commit shares no ancestor with the fetched
    history, materialize refused to touch the existing local head, and the
    sync path refuses diverged branches — so a repo linked to a fresh project
    imported nothing, forever (demo-dumpsters, 2026-08-19).
    """
    from gateway.git import repos

    project_id = "00000000-0000-0000-0000-000000000003"
    monkeypatch.setattr(repos, "REPOS_ROOT", tmp_path)

    repos.init_bare_repo(project_id)  # scaffold: one empty commit on main
    remote = _make_github_style_remote(tmp_path, {"models/orders.sql": "select 1"})

    repos.clone_from_remote(project_id, remote)

    path = tmp_path / f"{project_id}.git"
    out = subprocess.run(
        ["git", "-C", str(path), "ls-tree", "-r", "main", "--name-only"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "models/orders.sql" in out
    out = subprocess.run(
        ["git", "-C", str(path), "log", "--oneline", "main"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "real content" in out


def test_local_branch_with_user_content_is_never_overwritten(monkeypatch, tmp_path) -> None:
    from gateway.git import repos

    project_id = "00000000-0000-0000-0000-000000000004"
    monkeypatch.setattr(repos, "REPOS_ROOT", tmp_path)

    repos.init_bare_repo(project_id)
    # Simulate user work: push a real file onto main via a working clone.
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(tmp_path / f"{project_id}.git"), str(work)], check=True, capture_output=True)
    (work / "notebook.py").write_text("x = 1", encoding="utf-8")
    env_args = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", *env_args, "-C", str(work), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", *env_args, "-C", str(work), "commit", "-m", "user work"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "main"], check=True, capture_output=True)

    remote = _make_github_style_remote(tmp_path, {"models/orders.sql": "select 1"})
    repos.clone_from_remote(project_id, remote)

    out = subprocess.run(
        ["git", "-C", str(tmp_path / f"{project_id}.git"), "log", "--oneline", "main"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "user work" in out  # local content preserved, not clobbered
