"""Compute a deterministic notebook_id from (org_id, user_id, project_id).

branch is NOT included (C3). A notebook's storage identity does not change across
branch switches. In-session branch switching is out of scope for R4.

project_id=None and project_id="" collapse to the same id — this is intentional.
Do NOT "fix" this by substituting str(None): the collapse is documented and tested.
The notebook_id is a 32-hex-char prefix of SHA-256.

Orphan-on-rename: if project_id changes, the old prefix continues to exist until
R6 GC. This is documented in deploy/k8s/README.md.
"""

from __future__ import annotations

from hashlib import sha256


def compute_notebook_id(org_id: str, user_id: str, project_id: str | None) -> str:
    """Return a 32-hex-char notebook_id derived from (org_id, user_id, project_id).

    project_id=None and project_id="" produce the same id (both collapse to "").
    branch is intentionally excluded — see module docstring.
    """
    payload = f"{org_id}:{user_id}:{project_id or ''}"
    return sha256(payload.encode()).hexdigest()[:32]
