"""Terminal cwd validation helper.

Isolated for unit-testability. Called by terminal.py::websocket_endpoint to
validate the ?cwd= query parameter before creating a PTY.

Security: contains cwd to allowed roots (project root in cloud, project+home
in local mode). /tmp is NOT allowed in any mode (S2) — removes the JWT-staging
emptyDir leak vector named in the F-10 threat model.
"""

from __future__ import annotations

import os
from pathlib import Path


def _is_cloud_mode() -> bool:
    """Return True when running in cloud deployment mode.

    Mirrors gateway/runtime/mode.py::is_cloud_mode() — the env var is the
    single source of truth; this thin wrapper avoids a gateway→notebook-server
    import dependency.
    """
    return os.environ.get("SP_DEPLOYMENT_MODE", "local") == "cloud"


def validate_terminal_cwd(raw_cwd: str | None) -> str | None:
    """Validate and resolve a terminal cwd path.

    Args:
        raw_cwd: Raw cwd string from query parameter. May be None or empty.

    Returns:
        Resolved absolute path string if valid, or None if raw_cwd is falsy.

    Raises:
        ValueError: If the path contains parent traversal components, does not
            exist, or resolves outside the allowed roots.
    """
    if not raw_cwd:
        return None

    from signalpilot._server.files.project_sync import PROJECTS_ROOT

    # Belt-and-braces: reject .. in path components before resolution.
    # This guards against future Python changes to .resolve() semantics.
    raw_path = Path(raw_cwd)
    if ".." in raw_path.parts:
        raise ValueError("invalid cwd: parent traversal")

    # Resolve to absolute path; fail fast if path does not exist.
    try:
        resolved = raw_path.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise ValueError("invalid cwd") from exc

    # Build the set of allowed roots.
    # /tmp is NOT in the allow-list in any mode (S2).
    allowed_roots: list[Path] = [PROJECTS_ROOT.resolve()]
    if not _is_cloud_mode():
        # Local mode: also allow the user's home directory.
        allowed_roots.append(Path.home().resolve())

    for root in allowed_roots:
        if resolved.is_relative_to(root):
            return str(resolved)

    raise ValueError("invalid cwd: outside allowed roots")
