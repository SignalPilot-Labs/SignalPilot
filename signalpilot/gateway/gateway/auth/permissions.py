"""Permission vocabulary for the two Clerk organization roles.

Every organization has admins and members. The gateway decides access with
one dependency per route (``OrgAdmin`` for admin-only routes, ownership checks
for user-owned resources); this module names the same decisions as a flat set
of permission strings so the web app and the docs can read them without
re-deriving the rules.

The vocabulary is the contract shared with ``signalpilot/web`` (``usePermissions``)
and with ``docs/docs/product/roles.mdx`` (generated from this file). Add a
permission here, and only here; the docs test fails until the page is
regenerated.
"""

from __future__ import annotations

from .user import is_org_admin_role

# Ordered so the generated docs table is stable. Each entry: (permission, what it lets you do).
_ADMIN_PERMISSION_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    ("connections.write", "Create, edit, delete, clone, import and export database connections"),
    ("connections.test_credentials", "Test arbitrary credentials through the gateway before saving them"),
    ("schema.curate", "Curate schema: endorsements, refinement, column corrections, semantic model, PII rules"),
    ("settings.write", "Change organization settings, chat defaults and MCP agent defaults"),
    ("secrets.org.write", "Store, rotate or clear the organization Anthropic key"),
    ("byok.manage", "Manage bring-your-own encryption keys"),
    ("keys.admin", "Mint keys with the write, admin, dbt_proxy or agent:run scopes; list and revoke every key"),
    ("knowledge.publish", "Publish, edit, approve and archive knowledge base entries"),
    ("reports.manage", "Create, edit and delete durable reports"),
    ("evals.run", "Change eval configuration, start or cancel runs, upload eval sets"),
    ("improvements.run", "Trigger, enable or disable improvement runs"),
    ("schema_watches.write", "Create and change schema watches"),
    ("projects.write", "Create, change and delete workspace and dbt projects"),
    ("github.write", "Install or remove the GitHub App, link repositories, import and sync"),
    ("chat.default_project", "Set the organization default project for chat"),
    ("budgets.write", "Create and close session budgets"),
    ("audit.read", "Read the audit log, its statistics and export it"),
    ("billing.manage", "Change the plan, start checkout, cancel, open the billing portal"),
    ("usage.org", "See organization-wide usage and credit consumption"),
    ("team.manage", "Invite and remove members, change roles, manage verified domains"),
    ("integrations.write", "Install or remove Notion and Slack integrations"),
    ("mcp.org_connectors", "Manage organization-scope MCP connectors and the MCP policy"),
    ("security.read", "Read the security status page"),
    ("branch.production_write", "Write files on a project's production (default) branch"),
)

_MEMBER_PERMISSION_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    ("keys.personal", "Mint, list and revoke personal API keys with the read, query and execute scopes"),
    ("knowledge.propose", "Propose a knowledge base entry; it lands pending until an admin approves it"),
    ("usage.self", "See your own usage"),
)

PERMISSION_DESCRIPTIONS: dict[str, str] = dict(_ADMIN_PERMISSION_DESCRIPTIONS + _MEMBER_PERMISSION_DESCRIPTIONS)

MEMBER_PERMISSIONS: frozenset[str] = frozenset(name for name, _ in _MEMBER_PERMISSION_DESCRIPTIONS)
ADMIN_PERMISSIONS: frozenset[str] = frozenset(PERMISSION_DESCRIPTIONS)
PERMISSIONS: frozenset[str] = ADMIN_PERMISSIONS

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"

# Error details. Role failures reuse OrgAdmin's detail; ownership failures use this one.
ADMIN_ROLE_REQUIRED = "Organization admin role required"
OWNERSHIP_DENIAL = "You can only change resources you created"


def normalize_role(role: str | None) -> str:
    """Collapse every role spelling the gateway sees to ``admin`` or ``member``.

    ``resolve_org_role`` yields ``admin`` or ``basic_member``; Clerk's memberships
    API spells the admin role ``org:admin``. Anything that is not an admin is a member.
    """
    return ROLE_ADMIN if is_org_admin_role(role) else ROLE_MEMBER


def permissions_for(role: str | None) -> frozenset[str]:
    """The permission set of a role: admins hold every permission, members the member subset."""
    return ADMIN_PERMISSIONS if is_org_admin_role(role) else MEMBER_PERMISSIONS


__all__ = [
    "ADMIN_PERMISSIONS",
    "ADMIN_ROLE_REQUIRED",
    "MEMBER_PERMISSIONS",
    "OWNERSHIP_DENIAL",
    "PERMISSIONS",
    "PERMISSION_DESCRIPTIONS",
    "ROLE_ADMIN",
    "ROLE_MEMBER",
    "normalize_role",
    "permissions_for",
]
