"""Canonical workspace confinement for caller-supplied directory parameters.

Distinct from :class:`~signalpilot._server.files.path_validator.PathValidator`,
which deliberately preserves symlinks and treats the root itself as forbidden.
Directory parameters need the opposite: the *resolved* target must be compared
(so a symlink planted inside the workspace cannot point out of it) and the root
itself is a legal value.

Raises ``HTTPException(400)`` so handlers need no per-parameter error plumbing.
"""

from __future__ import annotations

import os
from pathlib import Path

from signalpilot._utils.http import HTTPException, HTTPStatus

WORKSPACE_ROOT_ENV = "SP_WORKSPACE_ROOT"
DEFAULT_WORKSPACE_ROOT = "/workspace"


def _reject(label: str) -> HTTPException:
    return HTTPException(
        status_code=HTTPStatus.BAD_REQUEST,
        detail=f"Invalid {label}: outside the workspace",
    )


def workspace_roots() -> list[Path]:
    """Resolved directories a path parameter may live under, primary first."""
    roots: list[Path] = []

    configured = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if configured:
        roots.append(Path(configured))

    # The sandbox boot command chdirs into the workspace before exec'ing the server,
    # and the container's WORKDIR is the workspace root.
    try:
        roots.append(Path.cwd())
    except OSError:
        pass

    if not configured:
        default_root = Path(DEFAULT_WORKSPACE_ROOT)
        if default_root.is_dir():
            roots.append(default_root)

    # Execution scratch checkouts live outside the editor's workspace dir.
    try:
        from signalpilot._server.files.workspace import PROJECTS_ROOT

        roots.append(PROJECTS_ROOT)
    except Exception:
        pass

    resolved: list[Path] = []
    for root in roots:
        try:
            candidate = root.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if candidate not in resolved:
            resolved.append(candidate)

    if not resolved:
        resolved.append(Path(DEFAULT_WORKSPACE_ROOT))
    return resolved


def confine(
    candidate: str | os.PathLike[str],
    *,
    label: str = "path",
) -> Path:
    """Resolve ``candidate`` and assert the real path stays in the workspace.

    Relative paths resolve against the primary workspace root, not the process
    cwd, so a caller cannot reach a sibling of the root via a bare relative
    path.
    """
    raw = os.fspath(candidate)
    if "\x00" in raw or not raw.strip():
        raise _reject(label)

    roots = workspace_roots()

    path = Path(raw)
    # Reject traversal components up front rather than relying on resolve()
    # semantics staying constant across Python versions.
    if ".." in path.parts:
        raise _reject(label)

    if not path.is_absolute():
        path = roots[0] / path

    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _reject(label) from exc

    for root in roots:
        if resolved.is_relative_to(root):
            return resolved

    raise _reject(label)


def confine_optional(
    candidate: str | os.PathLike[str] | None,
    *,
    label: str = "path",
) -> Path | None:
    """``confine`` that passes ``None`` and empty values through untouched."""
    if candidate is None:
        return None
    if isinstance(candidate, str) and not candidate.strip():
        return None
    return confine(candidate, label=label)


def is_confined(candidate: str | os.PathLike[str]) -> bool:
    """Non-raising ``confine`` for filtering discovered paths."""
    try:
        confine(candidate)
    except HTTPException:
        return False
    return True
