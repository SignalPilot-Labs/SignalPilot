"""Thin Clerk Backend API client used to mint GENUINE Clerk-signed session tokens.

Why this exists: the synthetic-JWKS harness gives total control over claims but signs
with our own key. This module gives the opposite guarantee — tokens signed by the real
Clerk instance, fetched through the real JWKS endpoint — so the happy paths are proved
at full fidelity.

Everything it creates (two throwaway users, one throwaway organization, and their
sessions) is torn down in ``cleanup()``. It never reads, modifies, or deletes
pre-existing users, organizations, or memberships.

Two operational gotchas, both handled here:
  * api.clerk.com sits behind Cloudflare, which answers Python's default urllib
    User-Agent with "HTTP 403, error code: 1010". A conventional UA is required.
  * The instance-level ``max_allowed_memberships`` is 1, so the throwaway org must
    raise its own limit before a second member can be added.
"""

from __future__ import annotations

import base64
import json
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE = "https://api.clerk.com/v1"
# Cloudflare in front of api.clerk.com rejects urllib's default UA with error 1010.
USER_AGENT = "curl/8.4.0"

# The non-privileged organization role key on this instance is "org:member"
# (GET /v1/organization_roles). It is NOT "org:basic_member".
MEMBER_ROLE_KEY = "org:member"
ADMIN_ROLE_KEY = "org:admin"


class ClerkError(RuntimeError):
    pass


def load_env_value(name: str, repo_root: Path) -> str | None:
    """Read a single variable out of the repo-root .env. Value is never logged."""
    env_path = repo_root / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            return value or None
    return None


def decode_claims(token: str) -> dict:
    """Decode a JWT payload WITHOUT verifying — for asserting claim shape only."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@dataclass
class ClerkAdmin:
    secret_key: str

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.secret_key}")
        req.add_header("User-Agent", USER_AGENT)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:600]

    def expect(self, method: str, path: str, body: dict | None = None) -> dict:
        status, payload = self.call(method, path, body)
        if status >= 300:
            raise ClerkError(f"{method} {path} -> {status}: {payload}")
        return payload  # type: ignore[return-value]


@dataclass
class ClerkFixture:
    """A throwaway org with one admin and one non-privileged member, plus live tokens."""

    admin: ClerkAdmin
    org_id: str
    admin_user_id: str
    member_user_id: str
    admin_token: str
    member_token: str
    admin_claims: dict
    member_claims: dict
    _sessions: list[str] = field(default_factory=list)
    _users: list[str] = field(default_factory=list)
    _orgs: list[str] = field(default_factory=list)

    def cleanup(self) -> list[str]:
        """Revoke and delete everything created. Returns a human-readable log."""
        log: list[str] = []
        for sid in self._sessions:
            status, _ = self.admin.call("POST", f"/sessions/{sid}/revoke", {})
            log.append(f"revoke session {sid} -> {status}")
        for oid in self._orgs:
            status, _ = self.admin.call("DELETE", f"/organizations/{oid}")
            log.append(f"delete organization {oid} -> {status}")
        for uid in self._users:
            status, _ = self.admin.call("DELETE", f"/users/{uid}")
            log.append(f"delete user {uid} -> {status}")
        return log


# Naming convention that marks a resource as ours and therefore safe to sweep.
ORG_NAME_PREFIX = "sp-e2e-authz-"
USER_MARKER_FIRST_NAME = "SPE2E"


def sweep_stale(secret_key: str) -> list[str]:
    """Delete residue from a previous run that was killed before teardown.

    Matches ONLY the harness's own naming convention: organizations whose name starts
    with `sp-e2e-authz-`, and users whose first name is exactly `SPE2E`. Anything else
    is left strictly alone.
    """
    api = ClerkAdmin(secret_key)
    log: list[str] = []

    status, orgs = api.call("GET", "/organizations?limit=100")
    if status < 300:
        rows = orgs.get("data", orgs) if isinstance(orgs, dict) else orgs
        for org in rows or []:
            if str(org.get("name", "")).startswith(ORG_NAME_PREFIX):
                code, _ = api.call("DELETE", f"/organizations/{org['id']}")
                log.append(f"swept stale organization {org['id']} -> {code}")

    status, users = api.call("GET", "/users?limit=100")
    if status < 300:
        for user in users or []:
            if user.get("first_name") == USER_MARKER_FIRST_NAME:
                code, _ = api.call("DELETE", f"/users/{user['id']}")
                log.append(f"swept stale user {user['id']} -> {code}")

    return log


def provision(secret_key: str) -> ClerkFixture:
    """Create a throwaway org + two users and mint one real session token for each.

    The organization is created *by* the admin user, which also makes it that user's
    active organization — that is what causes the ``o`` claim to appear in the session
    token. Adding the second user as a membership does the same for them.
    """
    api = ClerkAdmin(secret_key)
    tag = secrets.token_hex(5)
    users: list[str] = []
    orgs: list[str] = []
    sessions: list[str] = []

    def rollback():
        fixture = ClerkFixture(api, "", "", "", "", "", {}, {},
                               _sessions=sessions, _users=users, _orgs=orgs)
        fixture.cleanup()

    try:
        created: dict[str, str] = {}
        for label in ("admin", "member"):
            user = api.expect("POST", "/users", {
                "email_address": [f"sp-e2e-{label}-{tag}@example.com"],
                "password": secrets.token_urlsafe(24),
                "skip_password_checks": True,
                "first_name": USER_MARKER_FIRST_NAME,
                "last_name": f"{label}-{tag}",
            })
            created[label] = user["id"]
            users.append(user["id"])

        org = api.expect("POST", "/organizations", {
            "name": f"{ORG_NAME_PREFIX}{tag}",
            "created_by": created["admin"],
            "max_allowed_memberships": 5,
        })
        orgs.append(org["id"])
        # The instance default is 1; raise it so a second member can join.
        api.expect("PATCH", f"/organizations/{org['id']}", {"max_allowed_memberships": 5})

        membership = api.expect("POST", f"/organizations/{org['id']}/memberships", {
            "user_id": created["member"], "role": MEMBER_ROLE_KEY,
        })
        if membership.get("role") == ADMIN_ROLE_KEY:
            raise ClerkError("member user was granted org:admin - fixture is unsafe")

        tokens: dict[str, str] = {}
        claims: dict[str, dict] = {}
        for label in ("admin", "member"):
            session = api.expect("POST", "/sessions", {"user_id": created[label]})
            sessions.append(session["id"])
            token = api.expect("POST", f"/sessions/{session['id']}/tokens", {})["jwt"]
            tokens[label] = token
            claims[label] = decode_claims(token)

        return ClerkFixture(
            admin=api,
            org_id=org["id"],
            admin_user_id=created["admin"],
            member_user_id=created["member"],
            admin_token=tokens["admin"],
            member_token=tokens["member"],
            admin_claims=claims["admin"],
            member_claims=claims["member"],
            _sessions=sessions, _users=users, _orgs=orgs,
        )
    except Exception:
        rollback()
        raise
