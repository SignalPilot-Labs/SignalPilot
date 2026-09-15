"""The permission vocabulary shared with the web app and the docs."""

from __future__ import annotations

import pytest

from gateway.auth import (
    ADMIN_PERMISSIONS,
    MEMBER_PERMISSIONS,
    PERMISSION_DESCRIPTIONS,
    PERMISSIONS,
    normalize_role,
    permissions_for,
)

BRIEF_VOCABULARY = {
    "connections.write",
    "connections.test_credentials",
    "schema.curate",
    "settings.write",
    "secrets.org.write",
    "byok.manage",
    "keys.admin",
    "knowledge.publish",
    "reports.manage",
    "evals.run",
    "improvements.run",
    "schema_watches.write",
    "projects.write",
    "github.write",
    "chat.default_project",
    "budgets.write",
    "audit.read",
    "billing.manage",
    "usage.org",
    "team.manage",
    "integrations.write",
    "mcp.org_connectors",
    "security.read",
    "branch.production_write",
    "keys.personal",
    "knowledge.propose",
    "usage.self",
}


def test_vocabulary_is_exactly_the_brief():
    assert PERMISSIONS == frozenset(BRIEF_VOCABULARY)
    assert ADMIN_PERMISSIONS == PERMISSIONS
    assert MEMBER_PERMISSIONS == {"keys.personal", "knowledge.propose", "usage.self"}
    assert MEMBER_PERMISSIONS < ADMIN_PERMISSIONS


def test_every_permission_has_a_description():
    assert set(PERMISSION_DESCRIPTIONS) == PERMISSIONS
    assert all(description.strip() for description in PERMISSION_DESCRIPTIONS.values())


@pytest.mark.parametrize("role", ["admin", "org:admin"])
def test_admin_spellings_get_every_permission(role):
    assert permissions_for(role) == ADMIN_PERMISSIONS
    assert normalize_role(role) == "admin"


@pytest.mark.parametrize("role", ["basic_member", "org:member", "member", "", None, "viewer"])
def test_everything_else_is_a_member(role):
    assert permissions_for(role) == MEMBER_PERMISSIONS
    assert normalize_role(role) == "member"


def test_permission_sets_are_immutable():
    assert isinstance(permissions_for("admin"), frozenset)
    assert isinstance(permissions_for("basic_member"), frozenset)
