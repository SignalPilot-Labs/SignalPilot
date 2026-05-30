"""Pod entrypoint. Boot-time JWT extraction, then exec `sp edit`.

Reads the JWT from the emptyDir tmpfs, places it in os.environ, destroys
the file (writable tmpfs — no EROFS), then exec-replaces itself with `sp edit`.
This process runs as pid 1 in the pod; after execvp the new Python interpreter
takes over and `_server.start` pops SP_SESSION_JWT from os.environ at
import time, before the HTTP listener binds and before any kernel is spawned.
"""
from __future__ import annotations

import os
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


def main() -> int:
    _load_and_destroy_jwt()
    os.execvp("sp", ["sp", "edit", *sys.argv[1:]])
    return 0  # unreachable after execvp; satisfies type checker


if __name__ == "__main__":
    sys.exit(main())
