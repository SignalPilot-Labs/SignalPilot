"""Self-provisioning auth-token file for container boots outside Kubernetes.

Cloud pods receive a per-pod token from the orchestrator's Secret, staged into a
tmpfs and read via ``sp edit --token-password-file``. A plain ``docker run`` /
``docker compose up`` has no such orchestrator, so the container mints its own on
first boot and persists it to ``path`` — which keeps local parity with the
deployed config (auth ON) without a manual step or a secret in a tracked file.

``SP_NOTEBOOK_TOKEN``, when set, overrides and replaces the persisted value.

    python -m signalpilot._server.local_token /notebook-token/token

The token is never printed: the caller passes the same path to
``--token-password-file``.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def ensure_token_file(path: str | os.PathLike[str]) -> str:
    """Return the token at ``path``, creating or overriding it as needed."""
    file = Path(path)
    override = os.environ.get("SP_NOTEBOOK_TOKEN", "").strip()

    existing = ""
    try:
        existing = file.read_text(encoding="utf-8").strip()
    except OSError:
        pass

    token = override or existing or secrets.token_urlsafe(32)
    if token != existing:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(token, encoding="utf-8")
        # 0600 is best-effort: the readers are this container's own user and, for
        # compose, the gateway running under the same uid.
        try:
            file.chmod(0o600)
        except OSError:
            pass
    return token


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python -m signalpilot._server.local_token <token-file>",
            file=sys.stderr,
        )
        return 2
    ensure_token_file(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
