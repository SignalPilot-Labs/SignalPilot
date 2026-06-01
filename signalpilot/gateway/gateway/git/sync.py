"""GitHub ↔ bare repo synchronization.

Sync model:
1. Push local to GitHub (fast-forward)
2. If push rejected (remote has new commits), fetch + rebase local on remote
3. If rebase fails (real conflict), return error

Called by:
- git/http_server.py after a successful push (auto-mirror to GitHub)
- api/github.py sync endpoint (manual trigger)
- api/notebook_sessions.py on session creation (fetch before pod starts)
"""

from __future__ import annotations

import logging
import time

from ..store import workspace_projects as wp_store
from .repos import _run_git, list_branches, repo_exists, repo_path

logger = logging.getLogger(__name__)

GITHUB_REMOTE_NAME = "github"


def configure_github_remote(project_id: str, remote_url: str) -> None:
    """Add or update the 'github' remote on the bare repo."""
    rp = repo_path(project_id)
    rc, _, _ = _run_git("remote", "get-url", GITHUB_REMOTE_NAME, cwd=rp)
    if rc == 0:
        _run_git("remote", "set-url", GITHUB_REMOTE_NAME, remote_url, cwd=rp)
    else:
        _run_git("remote", "add", GITHUB_REMOTE_NAME, remote_url, cwd=rp)


def push_branch(project_id: str, remote_url: str, branch: str) -> dict:
    """Push a single branch to GitHub. Returns result dict.

    Skips agent branches. Attempts fast-forward push.
    If rejected, fetches remote and rebases local on top.
    If rebase fails, returns error (real conflict).
    """
    if branch.startswith("signalpilot-agent/"):
        return {"skipped": True, "reason": "Agent branches are local-only"}

    if not repo_exists(project_id):
        return {"error": "Repo not found"}

    rp = repo_path(project_id)
    configure_github_remote(project_id, remote_url)

    rc, _, _ = _run_git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=rp)
    if rc != 0:
        return {"error": f"Branch {branch} not found in bare repo"}

    # Try fast-forward push
    rc, out, err = _run_git(
        "push", GITHUB_REMOTE_NAME, f"refs/heads/{branch}:refs/heads/{branch}",
        cwd=rp, timeout=120,
    )
    if rc == 0:
        return {"pushed": True, "branch": branch, "output": out.strip() or err.strip()}

    # Push rejected — remote has new commits. Fetch + rebase.
    if "non-fast-forward" in err or "rejected" in err or "failed to push" in err:
        logger.info("Push rejected for %s, fetching + rebasing...", branch)

        frc, _, ferr = _run_git("fetch", GITHUB_REMOTE_NAME, branch, cwd=rp, timeout=120)
        if frc != 0:
            return {"error": f"Fetch failed during rebase: {ferr.strip()}"}

        # In a bare repo we can't rebase directly. Instead:
        # 1. Check if local is ancestor of remote (remote is ahead, just fast-forward local)
        # 2. Check if remote is ancestor of local (local is ahead, force isn't needed — shouldn't happen)
        # 3. Otherwise they diverged — update local ref to remote, local commits are lost
        #    (user chose "GitHub wins" for conflicts)

        local_ref = f"refs/heads/{branch}"
        remote_ref = f"refs/remotes/{GITHUB_REMOTE_NAME}/{branch}"

        # Is local an ancestor of remote? (remote has everything local has + more)
        rc_ancestor, _, _ = _run_git("merge-base", "--is-ancestor", local_ref, remote_ref, cwd=rp)
        if rc_ancestor == 0:
            # Remote is strictly ahead — fast-forward local to remote
            _run_git("update-ref", local_ref, remote_ref, cwd=rp)
            return {"pushed": False, "branch": branch, "fast_forwarded": True,
                    "reason": "Remote was ahead, local updated to match"}

        # Is remote an ancestor of local? (local has everything remote has + more)
        rc_ancestor2, _, _ = _run_git("merge-base", "--is-ancestor", remote_ref, local_ref, cwd=rp)
        if rc_ancestor2 == 0:
            # Local is strictly ahead — force push should work
            rc2, out2, err2 = _run_git(
                "push", "--force", GITHUB_REMOTE_NAME, f"{local_ref}:{local_ref}",
                cwd=rp, timeout=120,
            )
            if rc2 == 0:
                return {"pushed": True, "branch": branch, "force": True,
                        "output": out2.strip() or err2.strip()}
            return {"error": f"Force push failed: {err2.strip()}"}

        # Diverged — can't auto-resolve in a bare repo. Return error.
        return {
            "error": f"Branch {branch} has diverged from GitHub. "
                     f"Pull the latest changes in your notebook and resolve manually.",
            "diverged": True,
            "branch": branch,
        }

    return {"error": f"Push failed: {err.strip()}"}


def fetch_all(project_id: str, remote_url: str) -> dict:
    """Fetch all branches from GitHub into the bare repo.

    Updates remote tracking refs. Does NOT force-update local branches —
    that's handled by the push/rebase logic or explicit sync.
    """
    if not repo_exists(project_id):
        return {"error": "Repo not found"}

    rp = repo_path(project_id)
    configure_github_remote(project_id, remote_url)

    rc, out, err = _run_git("fetch", GITHUB_REMOTE_NAME, "--prune", cwd=rp, timeout=120)
    if rc != 0:
        return {"error": f"Fetch failed: {err.strip()}"}

    return {"fetched": True, "output": out.strip()}


def pull_branch(project_id: str, remote_url: str, branch: str) -> dict:
    """Pull a branch from GitHub: fetch + fast-forward local ref.

    If local branch doesn't exist, creates it from remote.
    If local has unpushed commits, does NOT overwrite — returns error.
    """
    if not repo_exists(project_id):
        return {"error": "Repo not found"}

    rp = repo_path(project_id)
    configure_github_remote(project_id, remote_url)

    # Fetch the specific branch
    rc, _, err = _run_git("fetch", GITHUB_REMOTE_NAME, branch, cwd=rp, timeout=120)
    if rc != 0:
        return {"error": f"Fetch failed: {err.strip()}"}

    remote_ref = f"refs/remotes/{GITHUB_REMOTE_NAME}/{branch}"
    local_ref = f"refs/heads/{branch}"

    # Check if local branch exists
    rc_local, _, _ = _run_git("rev-parse", "--verify", local_ref, cwd=rp)
    if rc_local != 0:
        # Local branch doesn't exist — create from remote
        _run_git("update-ref", local_ref, remote_ref, cwd=rp)
        return {"pulled": True, "branch": branch, "created": True}

    # Local exists — check if fast-forward is possible
    rc_ancestor, _, _ = _run_git("merge-base", "--is-ancestor", local_ref, remote_ref, cwd=rp)
    if rc_ancestor == 0:
        # Local is ancestor of remote — safe to fast-forward
        _run_git("update-ref", local_ref, remote_ref, cwd=rp)
        return {"pulled": True, "branch": branch}

    # Check if already up-to-date (remote is ancestor of local)
    rc_ancestor2, _, _ = _run_git("merge-base", "--is-ancestor", remote_ref, local_ref, cwd=rp)
    if rc_ancestor2 == 0:
        return {"pulled": True, "branch": branch, "already_ahead": True}

    return {
        "error": f"Branch {branch} has diverged. Push your changes first or resolve manually.",
        "diverged": True,
        "branch": branch,
    }


async def sync_project_with_github(project_id: str, org_id: str) -> dict:
    """Sync all branches with GitHub.

    For each non-agent branch: push to GitHub (with fetch+rebase on rejection).
    Then fetch any new remote branches.
    """
    from ..db.engine import get_session_factory
    from ..store import github as gh_store

    factory = get_session_factory()
    async with factory() as session:
        proj = await wp_store.get_project(session, org_id=org_id, project_id=project_id)
        if proj is None:
            return {"error": "Project not found"}
        link = await gh_store.get_repo_link_for_project(session, org_id=org_id, project_id=project_id)
        if not link:
            return {"error": "No GitHub repo linked to this project"}

        installation = await gh_store.get_installation(session, org_id=org_id, installation_id=link.installation_id)
        if not installation:
            return {"error": "GitHub installation not found"}

        token = await gh_store.get_valid_token(session, installation)
        remote_url = f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"

        # Push all non-agent local branches
        branches = list_branches(project_id)
        push_results = {}
        errors = []
        for branch in branches:
            if branch.startswith("signalpilot-agent/"):
                continue
            result = push_branch(project_id, remote_url, branch)
            push_results[branch] = result
            if result.get("error"):
                errors.append(f"{branch}: {result['error']}")

        # Fetch any new remote branches
        fetch_result = fetch_all(project_id, remote_url)

        # Mirror fetched remote-tracking refs into local heads so the bare repo
        # (which serves refs/heads/* to the notebook pod) reflects GitHub state.
        from .repos import materialize_local_branches
        materialize_local_branches(project_id, link.default_branch or "main")

        # Update last_sync_at
        from sqlalchemy import update
        from ..db.models import GatewayGitHubRepoLink
        await session.execute(
            update(GatewayGitHubRepoLink)
            .where(GatewayGitHubRepoLink.id == link.id)
            .values(last_sync_at=time.time())
        )
        await session.commit()

        result = {
            "synced": True,
            "push": push_results,
            "fetch": fetch_result,
            "last_sync_at": time.time(),
        }
        if errors:
            result["errors"] = errors
        return result


async def mirror_push_to_github(project_id: str, org_id: str, branch: str) -> dict | None:
    """Fire-and-forget mirror after a bare repo push. Returns None if no GitHub link."""
    from ..db.engine import get_session_factory
    from ..store import github as gh_store

    if branch.startswith("signalpilot-agent/"):
        return None

    factory = get_session_factory()
    async with factory() as session:
        link = await gh_store.get_repo_link_for_project(session, org_id=org_id, project_id=project_id)
        if not link:
            return None

        installation = await gh_store.get_installation(session, org_id=org_id, installation_id=link.installation_id)
        if not installation:
            logger.warning("GitHub installation %s not found for project %s", link.installation_id, project_id)
            return None

        try:
            token = await gh_store.get_valid_token(session, installation)
        except Exception as e:
            logger.warning("Failed to get GitHub token for mirror push: %s", e)
            return None

        remote_url = f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"
        result = push_branch(project_id, remote_url, branch)

        if not result.get("error") and not result.get("skipped"):
            from sqlalchemy import update
            from ..db.models import GatewayGitHubRepoLink
            await session.execute(
                update(GatewayGitHubRepoLink)
                .where(GatewayGitHubRepoLink.id == link.id)
                .values(last_sync_at=time.time())
            )
            await session.commit()

        if result.get("pushed"):
            logger.info("Mirrored %s to GitHub for project %s", branch, project_id)
        elif result.get("diverged"):
            logger.warning("Branch %s diverged for project %s — manual resolution needed", branch, project_id)
        elif result.get("error"):
            logger.warning("Mirror push failed for project %s/%s: %s", project_id, branch, result["error"])

        return result
