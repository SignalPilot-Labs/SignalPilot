"""GitHub ↔ bare repo synchronization.

Two operations:
- fetch_from_github: pull latest from GitHub into the bare repo (GitHub wins on conflicts)
- mirror_to_github: push bare repo changes to GitHub (fast-forward or create PR)

Called by:
- git/http_server.py after a successful push (auto-mirror to GitHub)
- api/github.py sync endpoint (manual trigger)
- api/notebook_sessions.py on session creation (fetch before pod starts)
"""

from __future__ import annotations

import logging
import time

from .repos import repo_path, repo_exists, _run_git

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


def fetch_from_github(project_id: str, remote_url: str) -> dict:
    """Fetch all branches from GitHub into the bare repo.

    GitHub wins: local branches are force-updated to match GitHub.
    Agent branches (signalpilot-agent/*) are never touched.
    """
    if not repo_exists(project_id):
        return {"error": "Repo not found"}

    rp = repo_path(project_id)
    configure_github_remote(project_id, remote_url)

    rc, out, err = _run_git("fetch", GITHUB_REMOTE_NAME, "--prune", cwd=rp, timeout=120)
    if rc != 0:
        return {"error": f"Fetch failed: {err.strip()}"}

    # Force-update local branches to match github remote (GitHub wins).
    # Skip agent branches — those are local-only.
    rc2, branch_out, _ = _run_git(
        "for-each-ref", "--format=%(refname:short) %(upstream:short)",
        "refs/remotes/github/", cwd=rp,
    )
    updated = []
    if rc2 == 0:
        for line in branch_out.strip().split("\n"):
            if not line.strip():
                continue
            remote_branch = line.strip().split()[0]  # e.g. "github/main"
            local_name = remote_branch.removeprefix(f"{GITHUB_REMOTE_NAME}/")
            if local_name.startswith("signalpilot-agent/"):
                continue
            if local_name == "HEAD":
                continue
            # Update local branch ref to match remote
            remote_ref = f"refs/remotes/{GITHUB_REMOTE_NAME}/{local_name}"
            local_ref = f"refs/heads/{local_name}"
            rc3, _, err3 = _run_git(
                "update-ref", local_ref, remote_ref, cwd=rp,
            )
            if rc3 == 0:
                updated.append(local_name)

    return {
        "fetched": True,
        "updated_branches": updated,
        "output": out.strip(),
    }


def mirror_to_github(project_id: str, remote_url: str, branch: str = "main") -> dict:
    """Push a branch from the bare repo to GitHub.

    Skips agent branches. If fast-forward fails, creates a PR branch instead.
    Returns push result or PR branch name.
    """
    if not repo_exists(project_id):
        return {"error": "Repo not found"}
    if branch.startswith("signalpilot-agent/"):
        return {"skipped": True, "reason": "Agent branches are local-only"}

    rp = repo_path(project_id)
    configure_github_remote(project_id, remote_url)

    # Check if the branch exists locally
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

    # Fast-forward failed — push as a PR branch instead
    if "non-fast-forward" in err or "rejected" in err or "failed to push" in err:
        pr_branch = f"signalpilot/sync-{int(time.time())}"
        rc2, out2, err2 = _run_git(
            "push", GITHUB_REMOTE_NAME, f"refs/heads/{branch}:refs/heads/{pr_branch}",
            cwd=rp, timeout=120,
        )
        if rc2 == 0:
            return {
                "pushed": False,
                "pr_branch": pr_branch,
                "reason": "Fast-forward failed, pushed as PR branch",
                "output": err.strip(),
            }
        return {"error": f"Push failed (both direct and PR): {err2.strip()}"}

    return {"error": f"Push failed: {err.strip()}"}


async def sync_project_with_github(project_id: str, org_id: str) -> dict:
    """Full bidirectional sync: fetch from GitHub, then push local changes back.

    Fetches a fresh installation token from the DB, configures the remote,
    and runs fetch + push. Updates last_sync_at on success.
    """
    from ..db.engine import get_session_factory
    from ..store import github as gh_store

    factory = get_session_factory()
    async with factory() as session:
        link = await gh_store.get_repo_link_for_project(session, org_id=org_id, project_id=project_id)
        if not link:
            return {"error": "No GitHub repo linked to this project"}

        installation = await gh_store.get_installation(session, org_id=org_id, installation_id=link.installation_id)
        if not installation:
            return {"error": "GitHub installation not found"}

        token = await gh_store.get_valid_token(session, installation)
        remote_url = f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"

        # Fetch from GitHub (GitHub wins)
        fetch_result = fetch_from_github(project_id, remote_url)
        if "error" in fetch_result:
            return {"fetch": fetch_result}

        # Push local changes to GitHub
        default_branch = link.default_branch or "main"
        push_result = mirror_to_github(project_id, remote_url, branch=default_branch)

        # Update last_sync_at
        from sqlalchemy import update
        from ..db.models import GatewayGitHubRepoLink
        await session.execute(
            update(GatewayGitHubRepoLink)
            .where(GatewayGitHubRepoLink.id == link.id)
            .values(last_sync_at=time.time())
        )
        await session.commit()

        return {
            "synced": True,
            "fetch": fetch_result,
            "push": push_result,
            "last_sync_at": time.time(),
        }


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
        result = mirror_to_github(project_id, remote_url, branch=branch)

        if "error" not in result:
            from sqlalchemy import update
            from ..db.models import GatewayGitHubRepoLink
            await session.execute(
                update(GatewayGitHubRepoLink)
                .where(GatewayGitHubRepoLink.id == link.id)
                .values(last_sync_at=time.time())
            )
            await session.commit()

        if result.get("pr_branch"):
            logger.info("Mirror push created PR branch %s for project %s", result["pr_branch"], project_id)
        elif result.get("pushed"):
            logger.info("Mirrored %s to GitHub for project %s", branch, project_id)
        elif result.get("error"):
            logger.warning("Mirror push failed for project %s: %s", project_id, result["error"])

        return result
