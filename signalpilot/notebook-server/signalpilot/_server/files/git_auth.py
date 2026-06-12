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
        # Detach git from any inherited stdin (e.g. the kubectl-exec WS channel) so
        # a credential prompt fails fast instead of blocking until the exec times out.
        stdin=subprocess.DEVNULL,
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
        # Detach git from any inherited stdin (the exec WS channel we read the JWT
        # from) so it never blocks waiting on stdin.
        stdin=subprocess.DEVNULL,
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


def _main() -> int:
    """CLI: `python -m signalpilot._server.files.git_auth <repo> <project_id> <git-args...>`.

    Runs an authed git invocation (auth header per-process, never persisted).
    Used by the gateway's run_notebook push-back so it doesn't rely on a
    credential persisted in .git/config (removed by F-9).

    The session JWT is read from stdin when SP_SESSION_JWT is absent from the
    environment. Under F-6 the JWT is no longer in the pod spec env, so a
    kubectl-exec'd process (this CLI) cannot inherit it — the gateway pipes a
    short-lived session JWT over stdin instead (never on argv, so it does not
    appear in /proc/<pid>/cmdline).
    """
    import os
    import sys

    if len(sys.argv) < 4:
        sys.stderr.write("usage: git_auth <repo> <project_id> <git-args...>\n")
        return 2

    # Prime the JWT from stdin if the environment does not carry it (F-6).
    # load_session_jwt() (called inside run_git_authed) pops SP_SESSION_JWT from
    # os.environ, so setting it here makes the authed header resolve correctly.
    # Use readline(), not read(): the gateway terminates the JWT with a newline, so
    # readline returns at the delimiter without waiting for stdin EOF (the k8s exec
    # stdin channel does not deliver a reliable EOF, so read() would block/time out).
    if not os.environ.get("SP_SESSION_JWT") and not sys.stdin.isatty():
        piped = sys.stdin.readline().strip()
        if piped:
            os.environ["SP_SESSION_JWT"] = piped

    repo = Path(sys.argv[1])
    project_id = sys.argv[2]
    rc, out, err = run_git_authed(repo, project_id, *sys.argv[3:])
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return rc


if __name__ == "__main__":
    import sys

    sys.exit(_main())
