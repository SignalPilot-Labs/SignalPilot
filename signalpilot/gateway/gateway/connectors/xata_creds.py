"""Xata credential indirection and connection scoping.

Two problems this module solves, both driven by the shared demo warehouse:

1. **The org key must not be copied into per-workspace storage.** The demo
   connector hands every workspace a branch of the *same* Xata project, which
   means every workspace's connection would otherwise hold a copy of the
   org-wide control-plane key (`XATA_KEY`, a secret that lives in AWS Secrets
   Manager in production). Instead the connection stores a *reference*
   (`xata_credential_ref`) and the key is materialized from the server-side
   secret at use time, by `resolve_xata_extras()`. One copy of the secret, held
   by the process, never at rest in the connections table.

2. **A shared-key connection must not be a skeleton key for the whole org.**
   The control-plane endpoints take the project as a path param and the branch
   as a query param, so a connection carrying an org-scoped key could otherwise
   reach every project and every branch in the org — including other users'
   demo branches. `enforce_xata_scope()` pins such connections to exactly the
   project and branch recorded in their own extras.

Both behaviours are opt-in per connection: a normal BYO-key Xata connection
(user brings their own scoped key) stores its key inline and is unpinned, so
the multi-branch agent workflow keeps working unchanged.
"""

from __future__ import annotations

import os

# Credential refs: a symbolic name resolved to a secret held by the gateway
# process. Kept as an explicit allowlist so a tampered extras blob can never
# name an arbitrary environment variable.
CREDENTIAL_REF_ENV: dict[str, str] = {
    "demo": "XATA_KEY",
}

# Extras keys owned by this module.
REF_KEY = "xata_credential_ref"
PIN_KEY = "xata_pinned"


class XataCredentialError(RuntimeError):
    """The referenced server-side Xata secret is missing or unknown."""


class XataScopeError(PermissionError):
    """The caller addressed a project/branch outside a pinned connection's scope."""


def resolve_xata_extras(extras: dict | None) -> dict:
    """Return `extras` with `xata_api_key` materialized from the server-side secret.

    A no-op for connections that store their key inline (the BYO-key case) or
    that use the legacy OIDC path. Never mutates the caller's dict.
    """
    extras = extras or {}
    ref = extras.get(REF_KEY)
    if not ref:
        return extras
    env_var = CREDENTIAL_REF_ENV.get(str(ref))
    if not env_var:
        raise XataCredentialError(f"Unknown Xata credential reference '{ref}'")
    key = os.getenv(env_var, "").strip()
    if not key:
        raise XataCredentialError(
            f"Xata credential '{ref}' is not configured on this gateway ({env_var} is unset)"
        )
    return {**extras, "xata_api_key": key}


def is_pinned(extras: dict | None) -> bool:
    """True if this connection may only address its own project and branch."""
    return bool((extras or {}).get(PIN_KEY))


def enforce_xata_scope(
    extras: dict | None,
    *,
    project: str | None = None,
    branch: str | None = None,
) -> None:
    """Raise XataScopeError if a pinned connection is addressed off-scope.

    Unpinned connections are unrestricted — they carry the user's own key, so
    reaching other projects in their own org is their prerogative.
    """
    extras = extras or {}
    if not is_pinned(extras):
        return
    own_project = extras.get("xata_project")
    if project is not None and project != own_project:
        raise XataScopeError(
            "This connection is scoped to a single Xata project and cannot address another."
        )
    own_branch = extras.get("branch")
    if branch is not None and branch.lower() != str(own_branch or "").lower():
        raise XataScopeError(
            f"This connection is scoped to branch '{own_branch}' and cannot address '{branch}'."
        )
