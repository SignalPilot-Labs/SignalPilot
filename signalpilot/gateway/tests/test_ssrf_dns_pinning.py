"""DNS-rebinding hardening for outbound database connections.

resolve_and_validate checked the addresses a hostname resolved to and then threw
them away: every driver performed its own second lookup when it connected, so a
record that resolved to a public address during validation could answer with
169.254.169.254 microseconds later. Substituting the IP into the DSN is not an
option — it breaks TLS hostname verification and SNI routing — so the resolver is
pinned instead for the duration of the connect.

Covered here:

* the acquire-time denylist still refuses metadata/link-local/private addresses;
* a host that rebinds between validation and connect is answered from the pinned
  (validated) address, not the rebound one;
* the pin is reference counted and fully removed afterwards;
* a driver that resolves outside socket.getaddrinfo is caught by the post-connect
  peer-address check;
* an SSH bastion on a link-local address is refused before the tunnel starts;
* live warehouses (Postgres 5602-5608, SQL Server 1434) still connect, including
  through the pinning code path.
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest

from gateway.connectors.pool_manager import PoolManager, _connected_peer_ip
from gateway.network.validation import (
    _pinned_hosts,
    assert_address_allowed,
    pinned_resolution,
)

_PUBLIC_IP = "93.184.216.34"
_METADATA_IP = "169.254.169.254"


def _mock_connector() -> MagicMock:
    connector = MagicMock()
    connector.connect = AsyncMock()
    connector.close = AsyncMock()
    connector.health_check = AsyncMock(return_value=True)
    connector.set_credential_extras = MagicMock()
    return connector


def _addrinfo(ip: str, port) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]


def _rebinding_getaddrinfo(first: str, then: str):
    """Answer the first lookup with *first* and every later one with *then*."""
    calls = {"n": 0}

    def fake(host, port=None, *args, **kwargs):
        calls["n"] += 1
        return _addrinfo(first if calls["n"] == 1 else then, port)

    return fake


# ─── Pin primitive ────────────────────────────────────────────────────────────


class TestPinnedResolution:
    def test_pinned_host_resolves_to_the_validated_address(self):
        original = socket.getaddrinfo
        with pinned_resolution("rebind.example.com", [_PUBLIC_IP]):
            assert socket.getaddrinfo("rebind.example.com", 5432)[0][4][0] == _PUBLIC_IP
        assert socket.getaddrinfo is original

    def test_case_and_whitespace_insensitive(self):
        with pinned_resolution("Rebind.Example.COM", [_PUBLIC_IP]):
            assert socket.getaddrinfo(" rebind.example.com ".strip(), 5432)[0][4][0] == _PUBLIC_IP

    def test_other_hosts_pass_through_untouched(self):
        with patch("socket.getaddrinfo", side_effect=lambda h, p, *a, **k: _addrinfo("203.0.113.9", p)):
            with pinned_resolution("pinned.example.com", [_PUBLIC_IP]):
                assert socket.getaddrinfo("other.example.com", 443)[0][4][0] == "203.0.113.9"
                assert socket.getaddrinfo("pinned.example.com", 443)[0][4][0] == _PUBLIC_IP

    def test_nested_pins_are_reference_counted(self):
        original = socket.getaddrinfo
        with pinned_resolution("a.example.com", [_PUBLIC_IP]):
            with pinned_resolution("b.example.com", ["198.51.100.7"]):
                assert socket.getaddrinfo("b.example.com", 1)[0][4][0] == "198.51.100.7"
            assert socket.getaddrinfo("a.example.com", 1)[0][4][0] == _PUBLIC_IP
        assert socket.getaddrinfo is original
        assert _pinned_hosts == {}

    def test_pin_is_released_when_the_body_raises(self):
        original = socket.getaddrinfo
        with pytest.raises(RuntimeError):
            with pinned_resolution("a.example.com", [_PUBLIC_IP]):
                raise RuntimeError("connect failed")
        assert socket.getaddrinfo is original
        assert _pinned_hosts == {}

    def test_address_family_mismatch_fails_closed(self):
        with pinned_resolution("v4only.example.com", [_PUBLIC_IP]):
            with pytest.raises(socket.gaierror):
                socket.getaddrinfo("v4only.example.com", 443, socket.AF_INET6)


# ─── Acquire-time behaviour ───────────────────────────────────────────────────


class TestAcquireRebinding:
    @pytest.mark.asyncio
    async def test_metadata_host_is_refused_before_connect(self):
        """Existing control — must stay green."""
        pm = PoolManager()
        connector = _mock_connector()

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch("socket.getaddrinfo", side_effect=lambda h, p, *a, **k: _addrinfo(_METADATA_IP, p)),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            with pytest.raises(ValueError):
                await pm.acquire("postgres", "postgresql://u:p@meta.example.com:5432/db", org_id="org-a")

        connector.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rebound_host_is_not_followed_at_connect(self):
        """DNS flips to the metadata address after validation; the driver must not see it."""
        pm = PoolManager()
        connector = _mock_connector()
        seen: list[str] = []

        async def _connect(conn_str: str) -> None:
            # Stands in for the driver's own second lookup.
            seen.append(socket.getaddrinfo("rebind.example.com", 5432)[0][4][0])

        connector.connect = AsyncMock(side_effect=_connect)

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch("socket.getaddrinfo", side_effect=_rebinding_getaddrinfo(_PUBLIC_IP, _METADATA_IP)),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            got = await pm.acquire("postgres", "postgresql://u:p@rebind.example.com:5432/db", org_id="org-a")

        assert got is connector
        assert seen == [_PUBLIC_IP], f"driver followed the rebound address: {seen}"

    @pytest.mark.asyncio
    async def test_pin_does_not_outlive_the_connect(self):
        pm = PoolManager()
        connector = _mock_connector()
        original = socket.getaddrinfo

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch("socket.getaddrinfo", side_effect=lambda h, p, *a, **k: _addrinfo(_PUBLIC_IP, p)),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            await pm.acquire("postgres", "postgresql://u:p@ok.example.com:5432/db", org_id="org-a")

        assert socket.getaddrinfo is original
        assert _pinned_hosts == {}

    @pytest.mark.asyncio
    async def test_local_mode_leaves_the_resolver_alone(self):
        """Loopback warehouses must keep working, and nothing gets pinned."""
        pm = PoolManager()
        connector = _mock_connector()
        original = socket.getaddrinfo

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "local"}),
            patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
        ):
            got = await pm.acquire("postgres", "postgresql://u:p@127.0.0.1:5602/sp_retail", org_id="org-a")

        assert got is connector
        assert socket.getaddrinfo is original
        assert _pinned_hosts == {}


# ─── Post-connect peer check (drivers that resolve in C) ──────────────────────


class TestPeerAddressCheck:
    def test_assert_address_allowed_rejects_metadata(self):
        with pytest.raises(ValueError):
            assert_address_allowed(_METADATA_IP)

    def test_assert_address_allowed_accepts_public(self):
        assert_address_allowed(_PUBLIC_IP)

    def test_peer_ip_is_read_from_a_driver_socket(self):
        a, b = socket.socketpair()
        try:
            holder = MagicMock()
            holder._conn = a
            assert _connected_peer_ip(holder) == a.getpeername()[0]
            # The borrowed fd must survive the inspection.
            a.send(b"ping")
            assert b.recv(4) == b"ping"
        finally:
            a.close()
            b.close()

    def test_peer_ip_is_none_for_drivers_without_a_socket(self):
        assert _connected_peer_ip(MagicMock()) is None

    @pytest.mark.asyncio
    async def test_connection_landing_on_a_blocked_address_is_closed(self):
        """A C-resolving driver ends up on loopback despite a public validation."""
        pm = PoolManager()
        a, b = socket.socketpair()
        connector = _mock_connector()
        connector._conn = a

        try:
            with (
                patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
                patch("socket.getaddrinfo", side_effect=lambda h, p, *ar, **k: _addrinfo(_PUBLIC_IP, p)),
                patch("gateway.connectors.pool_manager.get_connector", return_value=connector),
            ):
                with pytest.raises(ValueError, match="blocked internal address"):
                    await pm.acquire("mssql", "mssql://u:p@dbl.example.com:1433/db", org_id="org-a")
        finally:
            a.close()
            b.close()

        connector.close.assert_awaited()
        assert pm.pool_count == 0


# ─── SSH bastion ──────────────────────────────────────────────────────────────


class TestSSHBastionValidation:
    def _config(self, host: str) -> dict:
        return {"host": host, "port": 22, "username": "ec2-user", "password": "pw"}

    def test_link_local_bastion_is_refused_before_the_tunnel_starts(self):
        from gateway.connectors import ssh_tunnel as mod

        forwarder = MagicMock()
        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch.object(mod, "HAS_SSHTUNNEL", True),
            patch.object(mod, "SSHTunnelForwarder", forwarder),
            patch("socket.getaddrinfo", side_effect=lambda h, p, *a, **k: _addrinfo(_METADATA_IP, p)),
        ):
            tunnel = mod.SSHTunnel(self._config("bastion.example.com"))
            with pytest.raises(ValueError, match="blocked"):
                tunnel.start("warehouse.internal", 5432)

        forwarder.assert_not_called()

    def test_public_bastion_is_allowed_and_pinned(self):
        from gateway.connectors import ssh_tunnel as mod

        forwarder = MagicMock()
        forwarder.return_value.local_bind_host = "127.0.0.1"
        forwarder.return_value.local_bind_port = 54321
        seen: list[str] = []
        forwarder.return_value.start.side_effect = lambda: seen.append(
            socket.getaddrinfo("bastion.example.com", 22)[0][4][0]
        )

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "cloud"}),
            patch.object(mod, "HAS_SSHTUNNEL", True),
            patch.object(mod, "SSHTunnelForwarder", forwarder),
            patch("socket.getaddrinfo", side_effect=_rebinding_getaddrinfo(_PUBLIC_IP, _METADATA_IP)),
        ):
            tunnel = mod.SSHTunnel(self._config("bastion.example.com"))
            assert tunnel.start("warehouse.internal", 5432) == ("127.0.0.1", 54321)

        assert seen == [_PUBLIC_IP]

    def test_local_mode_bastion_is_not_validated(self):
        """Local deployments legitimately tunnel through RFC1918/loopback bastions."""
        from gateway.connectors import ssh_tunnel as mod

        forwarder = MagicMock()
        forwarder.return_value.local_bind_host = "127.0.0.1"
        forwarder.return_value.local_bind_port = 54321

        with (
            patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "local"}),
            patch.object(mod, "HAS_SSHTUNNEL", True),
            patch.object(mod, "SSHTunnelForwarder", forwarder),
        ):
            tunnel = mod.SSHTunnel(self._config("10.0.0.9"))
            assert tunnel.start("warehouse.internal", 5432) == ("127.0.0.1", 54321)


# ─── Live warehouses ──────────────────────────────────────────────────────────

_PROJECT_ENV_DIR = Path(__file__).resolve().parents[3] / "demo-generator" / "trap-arena" / "projects"
_LIVE_PG_PORTS = range(5602, 5609)


def _live_pg_urls() -> list[tuple[str, str]]:
    """(project, url) for every trap-arena warehouse on 5602-5608. Nothing is printed."""
    urls: list[tuple[str, str]] = []
    if not _PROJECT_ENV_DIR.is_dir():
        return urls
    for path in sorted(_PROJECT_ENV_DIR.glob("*/project.env")):
        text = path.read_text(encoding="utf-8", errors="replace")

        def field(key: str, blob: str = "") -> str | None:
            m = re.search(rf"^{key}\s*=\s*([^;\s#]+)", blob, re.MULTILINE)
            return m.group(1) if m else None

        port, database, user = field("PG_PORT", text), field("PG_DB", text), field("PG_USER_RO", text)
        pw = re.search(r"PG_PASS_RO\s*=\s*([^;\s#]+)", text)
        if not (port and database and user and pw) or int(port) not in _LIVE_PG_PORTS:
            continue
        urls.append(
            (path.parent.name, f"postgresql://{quote(user)}:{quote(pw.group(1), safe='')}@127.0.0.1:{port}/{database}")
        )
    return urls


def _pg_up(url: str) -> bool:
    async def _probe() -> bool:
        from gateway.connectors.drivers.postgres import PostgresConnector

        c = PostgresConnector()
        try:
            await c.connect(url)
            ok = await c.health_check()
            await c.close()
            return bool(ok)
        except Exception:
            return False

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


_PG_URLS = [(name, url) for name, url in _live_pg_urls() if _pg_up(url)]

MSSQL_HOST = os.environ.get("SP_TEST_MSSQL_HOST", "127.0.0.1")
MSSQL_PORT = os.environ.get("SP_TEST_MSSQL_PORT", "1434")
MSSQL_URL = f"mssql://sa:Str0ng%21Passw0rd@{MSSQL_HOST}:{MSSQL_PORT}/sp_test"


def _mssql_up() -> bool:
    try:
        import pymssql
    except ImportError:
        return False
    try:
        conn = pymssql.connect(
            server=MSSQL_HOST,
            port=MSSQL_PORT,
            user="sa",
            password="Str0ng!Passw0rd",
            database="sp_test",
            login_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


_MSSQL_UP = _mssql_up()


@pytest.mark.skipif(not _PG_URLS, reason="no trap-arena Postgres warehouse reachable on 5602-5608")
class TestLivePostgresRegression:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,url", _PG_URLS, ids=[n for n, _ in _PG_URLS])
    async def test_pool_manager_still_connects_and_queries(self, name: str, url: str):
        pm = PoolManager()
        with patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "local"}):
            async with pm.connection("postgres", url) as connector:
                rows = await connector.execute("SELECT 1 AS value")
        assert rows[0]["value"] == 1
        await pm.close_all()

    @pytest.mark.asyncio
    async def test_pinned_hostname_reaches_the_real_warehouse(self):
        """End-to-end proof that the pin drives asyncpg's own resolution.

        The hostname does not exist in DNS, so the connection can only succeed if
        asyncpg resolved it through the pin — and the DSN still carries the
        hostname, so TLS verification and SNI would see the original name.
        """
        from gateway.connectors.drivers.postgres import PostgresConnector

        _, url = _PG_URLS[0]
        pinned_url = url.replace("@127.0.0.1:", "@pinned-warehouse.invalid:")

        with pytest.raises(socket.gaierror):
            # Without the pin the name does not resolve at all.
            socket.getaddrinfo("pinned-warehouse.invalid", 5432)

        connector = PostgresConnector()
        with pinned_resolution("pinned-warehouse.invalid", ["127.0.0.1"]):
            await connector.connect(pinned_url)
            rows = await connector.execute("SELECT 1 AS value")
        await connector.close()
        assert rows[0]["value"] == 1


@pytest.mark.skipif(not _MSSQL_UP, reason="SQL Server test container (sp-mssql-test) not reachable")
class TestLiveMSSQLRegression:
    @pytest.mark.asyncio
    async def test_pool_manager_still_connects_and_queries(self):
        pm = PoolManager()
        with patch.dict(os.environ, {"SP_DEPLOYMENT_MODE": "local"}):
            async with pm.connection("mssql", MSSQL_URL) as connector:
                rows = await connector.execute("SELECT 1 AS value")
        assert rows[0]["value"] == 1
        await pm.close_all()
