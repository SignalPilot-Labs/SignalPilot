"""Shared authenticated git runner.

All callers that need a remote git operation (fetch, push, pull, clone) MUST
use run_git_authed. Local-only operations (status, log, branch listing, checkout)
use run_git.

Auth headers are NEVER persisted into .git/config — they are passed per-invocation
via git -c http.extraHeader=... (in-process only, not written to disk).

purge_persisted_auth() is called at the start of sync_down and sync_up for
upgrade safety: repos cloned before this fix may carry a stale http.extraHeader
entry in .git/config. The purge is idempotent and best-effort.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Exceptions that can be raised by subprocess.run and that purge_persisted_auth
# should swallow (upgrade-safety step, not a critical path).
_PURGE_SWALLOWED_ERRORS = (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError)


def run_git(repo: Path, *args: str, timeout: int = 60) -> tuple[int, str, str]:
    """Non-authed git invocation. Use for status/log/local branch ops only."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_git_authed(
    repo: Path, project_id: str, *args: str, timeout: int = 60
) -> tuple[int, str, str]:
    """Authed git invocation.

    Resolves (clone_url, auth_header) for project_id, then runs git with
    -c http.extraHeader=<header> per invocation.

    # Auth header is per-process via -c; never persist into .git/config.

    If no auth_header is resolved (e.g. GitHub-linked projects where auth is
    in the URL — but note the C3 invariant: URLs must never embed credentials),
    falls back to run_git.
    """
    from signalpilot._server.files.project_sync import _get_clone_url_and_auth

    _, auth_header = _get_clone_url_and_auth(project_id)
    if not auth_header:
        return run_git(repo, *args, timeout=timeout)

    # Auth header is per-process via -c; never persist into .git/config.
    result = subprocess.run(
        ["git", "-c", f"http.extraHeader=Authorization: {auth_header}", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def purge_persisted_auth(repo: Path) -> None:
    """Best-effort: remove any persisted http.extraHeader from .git/config.

    Idempotent — runs `git config --local --unset-all http.extraHeader`.
    Swallows errors (exit code 5 = key not found; any other error is also
    swallowed because this is an upgrade-safety step, not a critical path).

    Call at the start of sync_down and sync_up so that repos cloned before
    the F-9 fix have their stale persisted headers removed on next sync.
    """
    git_config = repo / ".git" / "config"
    if not git_config.exists():
        return
    try:
        subprocess.run(
            ["git", "config", "--local", "--unset-all", "http.extraHeader"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except _PURGE_SWALLOWED_ERRORS:
        pass
