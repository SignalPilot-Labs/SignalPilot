"""Pod entrypoint. Boot-time JWT extraction, workspace clone, then exec `sp edit`.

Flow (R4 F-6 / F-14):
  1. Read the per-session JWT from the emptyDir tmpfs the jwt-stager initContainer
     populated, place it in os.environ, then unlink the file (writable tmpfs — no
     EROFS). The JWT is never present in the pod spec / etcd; only in this process's
     in-memory environ.
  2. Run project_sync_boot as a SUBPROCESS. It inherits os.environ (so it can read
     SP_SESSION_JWT to authenticate the git clone) and pops its own copy; because it
     is a child process, that pop does not affect this process's environ.
  3. execvp `sp edit`, which inherits this process's environ (still holding
     SP_SESSION_JWT). `_server.start` pops SP_SESSION_JWT at import time, before the
     HTTP listener binds and before any kernel is spawned, so the kernel never sees it.

project_sync_boot MUST run in a subprocess, not in-process: load_session_jwt() pops
SP_SESSION_JWT from os.environ into a module cache, and execvp starts a fresh
interpreter that would lose that cache — so the JWT has to still be in os.environ at
execvp time for the server to load it.
"""
from __future__ import annotations

import os
import subprocess
import sys

# Must match gateway/orchestrator/kubernetes.py SP_SESSION_JWT_MOUNT_FILE.
_JWT_PATH = "/var/run/sp/session_jwt/session_jwt"


def _load_and_destroy_jwt() -> None:
    """Read JWT from the emptyDir mount and remove the file.

    Tolerates FileNotFoundError (local-mode / dev: no JWT mount).
    All other OSError (including PermissionError, EROFS) propagates and
    kills the pod — a destroy-after-read failure must not be silenced.
    """
    try:
        with open(_JWT_PATH, "rb") as f:
            jwt = f.read().decode("utf-8").strip()
    except FileNotFoundError:
        # Local-mode / dev: no JWT mount. Whatever env was set wins.
        return
    os.environ["SP_SESSION_JWT"] = jwt
    # emptyDir tmpfs is writable for the file owner (uid 10001 via initContainer chown).
    # No silent except: if unlink fails, surface it — that means the destroy-after-read
    # contract is broken and the file would persist for pod lifetime (v1 hole).
    os.unlink(_JWT_PATH)


def _run_project_sync_boot() -> int:
    """Clone the workspace before the editor starts. Returns the boot exit code.

    Runs as a subprocess so its load_session_jwt() env-pop does not strip
    SP_SESSION_JWT from this process — the server (after execvp) still needs it.
    """
    return subprocess.run(
        [sys.executable, "-m", "signalpilot._server.files.project_sync_boot"],
        check=False,
    ).returncode


def main() -> int:
    _load_and_destroy_jwt()
    rc = _run_project_sync_boot()
    if rc != 0:
        # Boot clone failed — exit non-zero so :2718 never binds and the gateway's
        # readiness probe times out (surfaces as a clear "failed to start" error).
        return rc
    os.execvp("sp", ["sp", "edit", *sys.argv[1:]])
    return 0  # unreachable after execvp; satisfies type checker


if __name__ == "__main__":
    sys.exit(main())
