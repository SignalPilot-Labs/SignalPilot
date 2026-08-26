"""Pure path confinement for workspace-relative file paths.

No filesystem access: these paths name entries inside a manifest, not files on
disk, so validation is purely lexical. The rules mirror the notebook-server's
path_confinement contract (no traversal, no NUL, project-relative only).
"""

from __future__ import annotations

import posixpath

_MAX_PATH_LENGTH = 1024


class WorkspacePathError(ValueError):
    """The supplied path escapes or malforms the project-relative namespace."""


def confine_relpath(path: str) -> str:
    """Normalize `path` to a canonical project-relative POSIX path.

    Raises WorkspacePathError for absolute paths, traversal, NUL bytes,
    Windows drive/backslash forms, and empty results.
    """
    if not isinstance(path, str) or not path:
        raise WorkspacePathError("Path must be a non-empty string")
    if "\x00" in path:
        raise WorkspacePathError("Path contains a NUL byte")
    if len(path) > _MAX_PATH_LENGTH:
        raise WorkspacePathError("Path exceeds the maximum length")
    if "\\" in path or (len(path) >= 2 and path[1] == ":"):
        raise WorkspacePathError("Windows-style paths are not accepted")
    if path.startswith("/") or path.startswith("~"):
        raise WorkspacePathError("Path must be project-relative")

    normalized = posixpath.normpath(path)
    if normalized in (".", "") or normalized.startswith("../") or normalized == "..":
        raise WorkspacePathError("Path escapes the project root")
    # normpath cannot leave interior '..' segments, but a crafted input like
    # 'a/../../b' normalizes to '../b' and is caught above. Belt and braces:
    if any(part == ".." for part in normalized.split("/")):
        raise WorkspacePathError("Path escapes the project root")
    return normalized
