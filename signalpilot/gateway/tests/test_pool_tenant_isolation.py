"""Tests for pool-key tenant isolation and connect-time destination revalidation.

Two separate findings live in pool_manager.acquire:

1. The pool was keyed by db_type + connection string only. Two tenants with the
   same visible connection string but different credential extras (service-account
   JSON, TLS key, SSH tunnel, token) collided, and because the reuse branch returns
   before set_credential_extras() runs, the second tenant received the first
   tenant's fully initialized connector.
2. connect() ran with no address validation, so a host validated when the
   connection was saved could later be re-pointed at an internal address.
"""

from __future__ import annotations

import os
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.common.credential_identity import CREDENTIAL_IDENTITY_KEY
from gateway.connectors.pool_manager import (
    PoolManager,
    _make_pool_key,
    _safe_pool_key_for_log,
)
from gateway.governance.context import current_org_id_var

_CONN_STR = "postgresql://svc:pw@shared.example.com:5432/app"


def _mock_connector(tag: str) -> MagicMock:
    connector = MagicMock()
    connector.tag = tag
    connector.connect = AsyncMock()
    connector.close = AsyncMock()
    connector.health_check = AsyncMock(return_value=True)
    connector.set_credential_extras = MagicMock()
    return connector


def _extras(identity: str, **kwargs) -> dict:
    return {CREDENTIAL_IDENTITY_KEY: identity, **kwargs}


# ─── Tenant isolation ─────────────────────────────────────────────────────────


class TestPoolTenantIsolation:
    @pytest.mark.asyncio
    async def test_same_connection_string_different_credentials_get_separate_pools(self):
        """Distinct credential extras must never share a pooled connector."""
        pm = PoolManager()
        a, b = _mock_connector("tenant-a"), _mock_connector("tenant-b")

        with patch("gateway.connectors.pool_manager.get_connector", side_effect=[a, b]):
            got_a = await pm.acquire(
                "postgres", _CONN_STR, credential_extras=_extras("cred-a", access_token="token-a"), org_id="org-a"
            )
            got_b = await pm.acquire(
                "postgres", _CONN_STR, credential_extras=_extras("cred-b", access_token="token-b"), org_id="org-b"
            )

        assert got_a is a
        assert got_b is b
        assert pm.pool_count == 2
        # Each connector saw only its own credentials.
        assert a.set_credential_extras.call_args[0][0]["access_token"] == "token-a"
        assert b.set_credential_extras.call_args[0][0]["access_token"] == "token-b"

    @pytest.mark.asyncio
    async def test_same_org_same_credentials_reuses_the_connector(self):
        """Isolation must not defeat pooling for the same principal."""
        pm = PoolManager()
        a = _mock_connector("tenant-a")

        with patch("gateway.connectors.pool_manager.get_connector", return_value=a):
            first = await pm.acquire("postgres", _CONN_STR, credential_extras=_extras("cred-a"), org_id="org-a")
            second = await pm.acquire("postgres", _CONN_STR, credential_extras=_extras("cred-a"), org_id="org-a")

        assert first is second
        assert pm.pool_count == 1
        assert a.connect.await_count == 1

    @pytest.mark.asyncio
    async def test_same_credentials_different_orgs_do_not_share(self):
        """org scoping alone separates two tenants that look identical."""
        pm = PoolManager()
        a, b = _mock_connector("a"), _mock_connector("b")

        with patch("gateway.connectors.pool_manager.get_connector", side_effect=[a, b]):
            await pm.acquire("postgres", _CONN_STR, credential_extras=None, org_id="org-a")
            await pm.acquire("postgres", _CONN_STR, credential_extras=None, org_id="org-b")

        assert pm.pool_count == 2

    @pytest.mark.asyncio
    async def test_cache_hit_with_different_credentials_is_refused(self):
        """Guard the reuse branch itself, not just the key derivation.

        The key is pinned to one value so the second acquire lands on an existing
        entry; the identity check must still reject it, because reuse returns
        before set_credential_extras() is applied.
        """
        pm = PoolManager()
        a, b = _mock_connector("tenant-a"), _mock_connector("tenant-b")
        fixed_key = "postgres:collision"

        with (
            patch("gateway.connectors.pool_manager._make_pool_key", return_value=fixed_key),
            patch("gateway.connectors.pool_manager.get_connector", side_effect=[a, b]),
        ):
            got_a = await pm.acquire(
                "postgres", _CONN_STR, credential_extras=_extras("cred-a", access_token="token-a"), org_id="org-a"
            )
            got_b = await pm.acquire(
                "postgres", _CONN_STR, credential_extras=_extras("cred-b", access_token="token-b"), org_id="org-b"
            )

        assert got_a is a
        assert got_b is b
        assert got_b is not got_a
        # Tenant A's connector was torn down rather than handed over, and tenant B
        # got a connector initialized with its own credentials.
        a.close.assert_awaited()
        assert b.set_credential_extras.call_args[0][0]["access_token"] == "token-b"

    @pytest.mark.asyncio
    async def test_rotated_credentials_do_not_reuse_the_old_connector(self):
        """A new credential identity (rewritten credential row) forces a new pool entry."""
        pm = PoolManager()
        old, new = _mock_connector("old"), _mock_connector("new")

        with patch("gateway.connectors.pool_manager.get_connector", side_effect=[old, new]):
            first = await pm.acquire("postgres", _CONN_STR, credential_extras=_extras("cred-v1"), org_id="org-a")
            second = await pm.acquire("postgres", _CONN_STR, credential_extras=_extras("cred-v2"), org_id="org-a")

        assert first is old
        assert second is new

    @pytest.mark.asyncio
    async def test_identity_marker_never_reaches_the_connector(self):
        """The store-supplied identity is bookkeeping, not credential data."""
        pm = PoolManager()
        connector = _mock_connector("a")

        with patch("gateway.connectors.pool_manager.get_connector", return_value=connector):
            await pm.acquire(
                "postgres", _CONN_STR, credential_extras=_extras("cred-a", access_token="t"), org_id="org-a"
            )

        passed = connector.set_credential_extras.call_args[0][0]
        assert CREDENTIAL_IDENTITY_KEY not in passed
        assert passed == {"access_token": "t"}

    @pytest.mark.asyncio
    async def test_release_matches_the_scoped_key(self):
        """release() must resolve the same key acquire() used."""
        pm = PoolManager()
        connector = _mock_connector("a")

        with patch("gateway.connectors.pool_manager.get_connector", return_value=connector):
            await pm.acquire("postgres", _CONN_STR, credential_extras=_extras("cred-a"), org_id="org-a")
        key = _make_pool_key("postgres", _CONN_STR, "org-a", "cred-a")
        before = pm._pools[key][1]
        await pm.release("postgres", _CONN_STR, credential_extras=_extras("cred-a"), org_id="org-a")
        assert pm._pools[key][1] >= before

    @pytest.mark.asyncio
    async def test_close_pool_is_org_scoped(self):
        """Rotating one tenant's credentials must not evict another tenant's pool."""
        pm = PoolManager()
        a, b = _mock_connector("a"), _mock_connector("b")

        with patch("gateway.connectors.pool_manager.get_connector", side_effect=[a, b]):
            await pm.acquire("postgres", _CONN_STR, credential_extras=_extras("cred-a"), org_id="org-a")
            await pm.acquire("postgres", _CONN_STR, credential_extras=_extras("cred-b"), org_id="org-b")

        closed = await pm.close_pool(_CONN_STR, org_id="org-a")
        assert closed == 1
        assert pm.pool_count == 1
        a.close.assert_awaited()
        b.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_org_id_defaults_to_the_governance_context(self):
        """Call sites that do not pass org_id still get org-scoped keys."""
        pm = PoolManager()
        a, b = _mock_connector("a"), _mock_connector("b")

        with patch("gateway.connectors.pool_manager.get_connector", side_effect=[a, b]):
            token = current_org_id_var.set("org-a")
            try:
                await pm.acquire("postgres", _CONN_STR)
            finally:
                current_org_id_var.reset(token)
            token = current_org_id_var.set("org-b")
            try:
                await pm.acquire("postgres", _CONN_STR)
            finally:
                current_org_id_var.reset(token)

        assert pm.pool_count == 2

    @pytest.mark.asyncio
    async def test_hand_built_extras_are_separated_by_shape(self):
        """Extras assembled at the API layer still get a non-secret identity.

        Same org, same DSN, different service-account and TLS material — the pool
        must not merge them even though no store marker is present.
        """
        pm = PoolManager()
        a, b = _mock_connector("a"), _mock_connector("b")
        sa_a = '{"client_email": "a@proj.iam.gserviceaccount.com", "private_key_id": "k1"}'
        sa_b = '{"client_email": "b@proj.iam.gserviceaccount.com", "private_key_id": "k2"}'

        with patch("gateway.connectors.pool_manager.get_connector", side_effect=[a, b]):
            await pm.acquire("postgres", _CONN_STR, credential_extras={"credentials_json": sa_a}, org_id="org-a")
            await pm.acquire("postgres", _CONN_STR, credential_extras={"credentials_json": sa_b}, org_id="org-a")

        assert pm.pool_count == 2

    @pytest.mark.asyncio
    async def test_shape_identity_ignores_secret_values(self):
        """The fallback identity is built from identifiers, never from the secrets."""
        from gateway.connectors.pool_manager import _extras_shape_identity

        base = {"ssl_config": {"enabled": True, "mode": "verify-full", "client_key": "PEM-ONE"}}
        rotated = {"ssl_config": {"enabled": True, "mode": "verify-full", "client_key": "PEM-TWO"}}
        identity = _extras_shape_identity(base)

        assert identity == _extras_shape_identity(rotated)
        assert "PEM-ONE" not in identity
        # A different TLS mode, or losing the key entirely, is a different shape.
        assert identity != _extras_shape_identity(
            {"ssl_config": {"enabled": True, "mode": "require", "client_key": "PEM-ONE"}}
        )
        assert identity != _extras_shape_identity({"ssl_config": {"enabled": True, "mode": "verify-full"}})

    def test_pool_key_is_never_logged_verbatim(self):
        """The log helper still redacts the password and keeps only non-secret scope."""
        key = _make_pool_key("postgres", _CONN_STR, "org-a", "cred-a")
        rendered = _safe_pool_key_for_log(key)
        assert "pw" not in rendered.split("org=")[0]
        assert "shared.example.com:5432" in rendered
        assert "org=org-a" in rendered


# ─── Connect-time destination revalidation ────────────────────────────────────


def _fake_getaddrinfo(ip: str):
    def _resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 5432))]

    return _resolver


class TestConnectTimeDestinationValidation:
    @pytest.mark.asyncio
    async def test_link_local_metadata_address_is_refused_at_acquire(self):
        """A host that now resolves to the metadata address must not be connected to."""
        pm = PoolManager()
        connector = _mock_connector("a")

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo("169.254.169.254")),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            with pytest.raises(ValueError):
                await pm.acquire("postgres", "postgresql://u:p@rebind.example.com:5432/db", org_id="org-a")

        # Fails closed: no connection attempted, nothing pooled.
        connector.connect.assert_not_awaited()
        assert pm.pool_count == 0

    @pytest.mark.asyncio
    async def test_no_fallback_to_hostname_when_resolution_fails(self):
        """DNS failure is a rejection, not a reason to try the raw hostname."""
        pm = PoolManager()
        connector = _mock_connector("a")

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch("socket.getaddrinfo", side_effect=socket.gaierror("no such host")),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            with pytest.raises(ValueError):
                await pm.acquire("postgres", "postgresql://u:p@gone.example.com:5432/db", org_id="org-a")

        connector.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_private_host_is_allowed_when_private_connections_are_enabled(self):
        """SP_ALLOW_PRIVATE_CONNECTIONS is respected — VPC warehouses keep working."""
        pm = PoolManager()
        connector = _mock_connector("a")

        with (
            patch.dict(
                os.environ,
                {"SP_DEPLOYMENT_MODE": "cloud", "SP_ALLOW_PRIVATE_CONNECTIONS": "1"},
            ),
            patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo("10.1.2.3")),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            got = await pm.acquire("postgres", "postgresql://u:p@vpc.internal:5432/db", org_id="org-a")

        assert got is connector
        connector.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_private_host_is_refused_when_private_connections_are_disabled(self):
        pm = PoolManager()
        connector = _mock_connector("a")

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud", "SP_ALLOW_PRIVATE_CONNECTIONS": "0"}),
            patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo("10.1.2.3")),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            with pytest.raises(ValueError):
                await pm.acquire("postgres", "postgresql://u:p@vpc.internal:5432/db", org_id="org-a")

        connector.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_local_deployment_keeps_loopback_warehouses_working(self):
        """Loopback is unconditionally blocked by the resolver, so local mode skips the check."""
        pm = PoolManager()
        connector = _mock_connector("a")

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "local"}),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            got = await pm.acquire("postgres", "postgresql://u:p@127.0.0.1:5602/sp_retail", org_id="org-a")

        assert got is connector
        connector.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_tcp_db_types_are_not_resolved(self):
        """DuckDB/BigQuery have no TCP host to validate."""
        pm = PoolManager()
        connector = _mock_connector("a")

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch("socket.getaddrinfo", side_effect=AssertionError("must not resolve")),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            got = await pm.acquire("duckdb", "md:analytics", org_id="org-a")

        assert got is connector
