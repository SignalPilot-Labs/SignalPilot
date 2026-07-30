"""Isolation rules for the shared demo warehouses.

The demo connector hands every workspace a branch of the *same* Xata project,
authenticated by one org-wide control-plane key that lives in AWS Secrets
Manager. Two properties therefore have to hold, and both are easy to regress:

  1. that key is never written into a workspace's connection record — the
     connection stores a reference and the gateway resolves it per request;
  2. a connection backed by that shared key can only ever address its own
     project and its own branch, so it cannot reach the read-only parent
     warehouse or another user's sandbox.

Everything here is pure-function level (no network, no database) so the rules
stay covered even when the live Xata org is unavailable.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from gateway.api import demo
from gateway.connectors.xata_creds import (
    XataCredentialError,
    XataScopeError,
    enforce_xata_scope,
    is_pinned,
    resolve_xata_extras,
)
from gateway.models import ConnectionCreate, DBType
from gateway.store.connection_strings import _build_connection_string, _extract_credential_extras

ORG = "0psl2d"
PROJECT = "prj_democontoso"
OTHER_PROJECT = "prj_demonorthwind"
BRANCH = "demo-a1b2c3d4"
OTHER_BRANCH = "demo-99887766"
FAKE_KEY = "xau_test_key_do_not_use"


def _demo_connection(**overrides) -> ConnectionCreate:
    """A connection shaped exactly like the one the demo connector creates."""
    kwargs = dict(
        name="contoso-demo",
        db_type=DBType.xata,
        branch=BRANCH,
        xata_credential_ref="demo",
        xata_pinned=True,
        xata_organization=ORG,
        xata_project=PROJECT,
        xata_database="xata",
        tags=["sp-demo", "demo:contoso"],
    )
    kwargs.update(overrides)
    return ConnectionCreate(**kwargs)


# ─── 1. the org key never goes to rest ───────────────────────────────────────


def test_demo_connection_stores_a_reference_not_the_key(monkeypatch):
    monkeypatch.setenv("XATA_KEY", FAKE_KEY)
    extras = _extract_credential_extras(_demo_connection())

    assert extras["xata_credential_ref"] == "demo"
    assert extras["xata_pinned"] is True
    assert "xata_api_key" not in extras
    # belt and braces: the key must not appear anywhere in the stored blob
    assert FAKE_KEY not in json.dumps(extras)


def test_demo_connection_string_carries_no_secret():
    cs = _build_connection_string(_demo_connection())
    assert cs == f"xata://{ORG}/{PROJECT}/{BRANCH}/xata"
    assert FAKE_KEY not in cs


def test_reference_resolves_to_the_gateway_held_key(monkeypatch):
    monkeypatch.setenv("XATA_KEY", FAKE_KEY)
    stored = _extract_credential_extras(_demo_connection())

    resolved = resolve_xata_extras(stored)

    assert resolved["xata_api_key"] == FAKE_KEY
    # resolution must not write back into the stored dict
    assert "xata_api_key" not in stored


def test_unset_secret_is_an_error_not_a_silent_anonymous_call(monkeypatch):
    monkeypatch.delenv("XATA_KEY", raising=False)
    with pytest.raises(XataCredentialError):
        resolve_xata_extras({"xata_credential_ref": "demo"})


def test_unknown_credential_reference_is_refused(monkeypatch):
    """A tampered extras blob must not be able to name an arbitrary env var."""
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-never-be-read")
    with pytest.raises(XataCredentialError):
        resolve_xata_extras({"xata_credential_ref": "AWS_SECRET_ACCESS_KEY"})


def test_byo_key_connections_are_untouched():
    """A user's own inline key still works exactly as before."""
    extras = {"xata_api_key": "xau_users_own_key", "xata_project": PROJECT}
    assert resolve_xata_extras(extras) == extras


# ─── 2. a shared-key connection is pinned to its own project and branch ──────


def test_demo_connection_is_pinned():
    assert is_pinned(_extract_credential_extras(_demo_connection()))


def test_byo_key_connection_is_not_pinned():
    extras = _extract_credential_extras(
        ConnectionCreate(
            name="my-xata",
            db_type=DBType.xata,
            branch="main",
            xata_api_key="xau_users_own_key",
            xata_organization=ORG,
            xata_project=PROJECT,
        )
    )
    assert not is_pinned(extras)


@pytest.fixture
def pinned() -> dict:
    return {"xata_pinned": True, "xata_project": PROJECT, "branch": BRANCH}


def test_own_project_and_branch_are_allowed(pinned):
    enforce_xata_scope(pinned, project=PROJECT)
    enforce_xata_scope(pinned, branch=BRANCH)
    enforce_xata_scope(pinned, branch=BRANCH.upper())  # branch match is case-insensitive


def test_another_project_is_refused(pinned):
    """The whole point: one org key must not be a key to the whole org."""
    with pytest.raises(XataScopeError):
        enforce_xata_scope(pinned, project=OTHER_PROJECT)


def test_another_users_branch_is_refused(pinned):
    """Branch names are enumerable, so this is the cross-tenant write path."""
    with pytest.raises(XataScopeError):
        enforce_xata_scope(pinned, branch=OTHER_BRANCH)


def test_the_shared_parent_branch_is_refused(pinned):
    with pytest.raises(XataScopeError):
        enforce_xata_scope(pinned, branch="main")


def test_unpinned_connections_keep_full_multi_branch_access():
    extras = {"xata_api_key": "xau_users_own_key", "xata_project": PROJECT, "branch": "main"}
    enforce_xata_scope(extras, project=OTHER_PROJECT)
    enforce_xata_scope(extras, branch="anything-at-all")


def test_pin_requires_something_to_pin_to():
    with pytest.raises(ValueError, match="xata_pinned"):
        _demo_connection(xata_project=None)
    with pytest.raises(ValueError, match="xata_pinned"):
        _demo_connection(branch=None)


def test_credential_ref_satisfies_the_new_xata_field_requirements():
    """Without an inline key the model must not fall back to the legacy
    region+database path — the ref is a valid way to be a new-Xata connection."""
    conn = _demo_connection()
    assert conn.xata_api_key is None
    assert conn.region is None


# ─── 3. the demo catalog ─────────────────────────────────────────────────────


def _set_catalog(monkeypatch, value: str) -> None:
    monkeypatch.setenv("SP_DEMO_CATALOG", value)


def test_catalog_parses_multiple_warehouses(monkeypatch):
    _set_catalog(
        monkeypatch,
        json.dumps(
            [
                {"slug": "contoso", "project": PROJECT, "title": "Contoso", "repo_url": "https://x/y"},
                {"slug": "northwind", "project": OTHER_PROJECT, "title": "NORTHWIND"},
            ]
        ),
    )
    demos = demo._catalog()

    assert [d.slug for d in demos] == ["contoso", "northwind"]
    assert [d.connection_name for d in demos] == ["contoso-demo", "northwind-demo"]
    assert demos[0].parent_branch == "main"


def test_catalog_survives_a_bad_entry(monkeypatch):
    """One malformed entry must not take the whole demo page down."""
    _set_catalog(
        monkeypatch,
        json.dumps(
            [
                {"slug": "Bad Slug!", "project": PROJECT},
                {"slug": "no-project"},
                "not-an-object",
                {"slug": "northwind", "project": OTHER_PROJECT, "title": "NORTHWIND"},
            ]
        ),
    )
    assert [d.slug for d in demo._catalog()] == ["northwind"]


def test_catalog_drops_duplicate_slugs(monkeypatch):
    _set_catalog(
        monkeypatch,
        json.dumps(
            [
                {"slug": "northwind", "project": PROJECT, "title": "First"},
                {"slug": "northwind", "project": OTHER_PROJECT, "title": "Second"},
            ]
        ),
    )
    demos = demo._catalog()
    assert len(demos) == 1
    assert demos[0].title == "First"


def test_malformed_catalog_disables_the_demo_rather_than_crashing(monkeypatch):
    _set_catalog(monkeypatch, "{not json")
    assert demo._catalog() == []
    _set_catalog(monkeypatch, json.dumps({"slug": "contoso"}))
    assert demo._catalog() == []


def test_legacy_single_project_config_still_works(monkeypatch):
    monkeypatch.delenv("SP_DEMO_CATALOG", raising=False)
    monkeypatch.setenv("SP_DEMO_XATA_PROJECT", PROJECT)
    monkeypatch.setenv("SP_DEMO_CONNECTION_NAME", "contoso-demo")
    monkeypatch.setenv("SP_DEMO_REPO_URL", "https://github.com/kiwi0401/contoso-demo")

    demos = demo._catalog()
    assert len(demos) == 1
    assert demos[0].project == PROJECT
    assert demos[0].connection_name == "contoso-demo"


def test_demo_disabled_without_configuration(monkeypatch):
    monkeypatch.delenv("SP_DEMO_CATALOG", raising=False)
    monkeypatch.delenv("SP_DEMO_XATA_PROJECT", raising=False)
    monkeypatch.setenv("XATA_KEY", FAKE_KEY)
    monkeypatch.setenv("SP_DEMO_XATA_ORG", ORG)
    assert not demo._demo_config().enabled


# ─── 4. the endpoint guard maps scope violations to 403 ──────────────────────


def test_endpoint_guard_returns_403(pinned):
    from gateway.api.schema.exploration import _require_xata_scope

    _require_xata_scope(pinned, project=PROJECT)  # own project: fine

    with pytest.raises(HTTPException) as exc:
        _require_xata_scope(pinned, project=OTHER_PROJECT)
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        _require_xata_scope(pinned, branch="main")
    assert exc.value.status_code == 403


def test_pinned_edits_are_restricted_to_cosmetic_fields():
    """A pin is only as strong as the fields an edit can move.

    PUT /api/connections/{name} accepts `branch`, `xata_project` and
    `xata_api_url`, all of which redefine what the connection points at. Left
    open, a demo user could repoint at another user's branch and then legally
    ask for its write credentials, or repoint xata_api_url at a host they
    control and be handed the org key as a Bearer token.
    """
    from gateway.api.connections.crud import _PINNED_EDITABLE_FIELDS

    for field in ("branch", "xata_project", "xata_organization", "xata_api_url", "xata_api_key"):
        assert field not in _PINNED_EDITABLE_FIELDS, f"{field} must not be editable on a pinned connection"
    # cosmetic edits stay allowed so the sandbox is not read-only in the UI
    assert "description" in _PINNED_EDITABLE_FIELDS
    assert "tags" in _PINNED_EDITABLE_FIELDS


def test_xata_identity_is_carried_into_edit_revalidation():
    """Xata identity lives in extras, not on ConnectionInfo. If an edit does not
    fold it back in, revalidating the merged record fails ('require region and
    database') and every edit of a Xata connection 500s."""
    from gateway.api.connections.crud import _XATA_IDENTITY_EXTRAS

    for field in ("branch", "xata_project", "xata_organization", "xata_credential_ref"):
        assert field in _XATA_IDENTITY_EXTRAS


def test_scope_error_does_not_leak_the_other_project_id(pinned):
    """Error text is user-facing; it should not enumerate the org for them."""
    with pytest.raises(XataScopeError) as exc:
        enforce_xata_scope(pinned, project=OTHER_PROJECT)
    assert OTHER_PROJECT not in str(exc.value)
    assert PROJECT not in str(exc.value)
