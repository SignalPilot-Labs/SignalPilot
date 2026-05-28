"""JWT secret management for notebook session tokens.

- Cloud mode (SP_DEPLOYMENT_MODE=cloud): read SP_SESSION_JWT_SECRET env var.
  If unset/empty → raise at call time; gateway fails to boot.
- Local mode: read /gateway-secrets/notebook_jwt_secret on the gateway-private
  volume (signalpilot-gateway-secrets). If missing → generate and persist atomically
  with 0600. If exists but empty/unreadable → raise (do NOT regenerate; would
  invalidate live pods).

The gateway-secrets volume is mounted ONLY into the gateway service — never into
the web container — so the web process has no filesystem path to this secret.

Called once at gateway startup; result cached in _cached_secret.
"""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
from pathlib import Path

from ..runtime.mode import is_cloud_mode

logger = logging.getLogger(__name__)

_GATEWAY_SECRET_PATH = Path("/gateway-secrets/notebook_jwt_secret")

_cached_secret: str | None = None


def _write_secret_atomic(path: Path, value: str) -> None:
    """Write secret atomically with 0600 permissions."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".notebook_jwt_secret_")
    try:
        os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value)
        os.replace(tmp_path, str(path))
        logger.info("Generated and persisted notebook JWT secret to %s", path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_session_jwt_secret() -> str:
    """Load (or generate) the notebook session JWT signing secret.

    Returns the secret string. Raises RuntimeError on any unrecoverable failure.
    The result is cached after the first successful call.
    """
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret

    if is_cloud_mode():
        secret = os.environ.get("SP_SESSION_JWT_SECRET", "").strip()
        if not secret:
            raise RuntimeError(
                "Cloud mode requires SP_SESSION_JWT_SECRET env var but it is unset or empty. "
                "Generate a secret (e.g. python -c \"import secrets; print(secrets.token_urlsafe(48))\") "
                "and set SP_SESSION_JWT_SECRET."
            )
        _cached_secret = secret
        logger.info("Loaded notebook session JWT secret from SP_SESSION_JWT_SECRET env var")
        return _cached_secret

    # Local mode: use /gateway-secrets/notebook_jwt_secret (gateway-private volume only)
    path = _GATEWAY_SECRET_PATH
    if path.exists():
        try:
            content = path.read_text().strip()
        except OSError as e:
            raise RuntimeError(
                f"Cannot read notebook JWT secret from {path}: {e}. "
                "Check file permissions."
            ) from e
        if not content:
            raise RuntimeError(
                f"Notebook JWT secret file {path} exists but is empty. "
                "Do NOT regenerate automatically — that would invalidate live pods. "
                "Delete /gateway-secrets/notebook_jwt_secret manually and restart to "
                "generate a new secret, or restore the original secret."
            )
        _cached_secret = content
        logger.info("Loaded notebook session JWT secret from %s", path)
        return _cached_secret

    # File missing — generate and persist
    new_secret = secrets.token_urlsafe(48)
    _write_secret_atomic(path, new_secret)
    _cached_secret = new_secret
    return _cached_secret
