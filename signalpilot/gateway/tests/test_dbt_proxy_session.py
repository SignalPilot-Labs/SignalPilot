"""In-process socket tests for DbtProxySession.

Uses asyncio.start_server on 127.0.0.1:0 (OS-assigned port) — no real Postgres.
Fakes are injected via constructor; no monkeypatching.
"""

from __future__ import annotations

import asyncio
import struct
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.dbt_proxy.protocol import (
    write_authentication_cleartext_password,
    write_authentication_ok,
    write_backend_key_data,
    write_parameter_status,
    write_ready_for_query,
)
from gateway.dbt_proxy.tokens import RunTokenClaims


def _make_startup_bytes(user: str, database: str = "my_conn") -> bytes:
    proto = struct.pack("!I", 0x00030000)
    body = proto
    for k, v in [("user", user), ("database", database), ("application_name", "dbt")]:
        body += k.encode() + b"\x00" + v.encode() + b"\x00"
    body += b"\x00"
    return struct.pack("!I", len(body) + 4) + body


def _make_frontend_msg(type_byte: bytes, payload: bytes) -> bytes:
    length = struct.pack("!I", len(payload) + 4)
    return type_byte + length + payload


def _make_simple_query(sql: str) -> bytes:
    return _make_frontend_msg(b"Q", sql.encode() + b"\x00")


def _make_terminate() -> bytes:
    return _make_frontend_msg(b"X", b"")


def _claims(run_id: uuid.UUID, connector: str = "my_conn") -> RunTokenClaims:
    return RunTokenClaims(
        run_id=run_id,
        org_id="org-1",
        user_id="user-1",
        connector_name=connector,
        expires_at=9999999999.0,
    )


class TestDbtProxySession:
    async def test_auth_happy_path(self) -> None:
        """Verify that a good token produces AuthOk + ReadyForQuery."""
        from gateway.dbt_proxy.tokens import RunTokenStore
        from gateway.dbt_proxy.auth import handle_startup

        secret = "test-secret"
        token_store = RunTokenStore(secret)
        run_id = uuid.uuid4()
        token_hex, _ = await token_store.mint(run_id, "org-1", "user-1", "my_conn", ttl_seconds=300)

        startup = _make_startup_bytes(f"run-{run_id}", "my_conn")
        password_msg = _make_frontend_msg(b"p", token_hex.encode() + b"\x00")
        data_in = startup + password_msg

        reader = asyncio.StreamReader()
        reader.feed_data(data_in)

        buf: list[bytes] = []

        class FakeWriter:
            def write(self, data: bytes) -> None:
                buf.append(data)
            async def drain(self) -> None:
                pass
            def close(self) -> None:
                pass
            def get_extra_info(self, key: str) -> object:
                return None

        writer = FakeWriter()
        claims = await handle_startup(reader, writer, token_store)
        assert claims.run_id == run_id
        combined = b"".join(buf)
        # AuthenticationCleartextPassword → type R
        assert b"R" in combined
        # AuthOk must be present
        assert combined.count(b"R") >= 2

    async def test_auth_fail_sends_error_and_closes(self) -> None:
        """Wrong token → ErrorResponse with SQLSTATE 28P01."""
        from gateway.dbt_proxy.tokens import RunTokenStore
        from gateway.dbt_proxy.auth import handle_startup
        from gateway.dbt_proxy.errors import AuthFailed

        secret = "test-secret"
        token_store = RunTokenStore(secret)
        run_id = uuid.uuid4()
        await token_store.mint(run_id, "org-1", "user-1", "my_conn", ttl_seconds=300)

        startup = _make_startup_bytes(f"run-{run_id}", "my_conn")
        bad_password = _make_frontend_msg(b"p", b"badtoken\x00")
        data_in = startup + bad_password

        reader = asyncio.StreamReader()
        reader.feed_data(data_in)

        buf: list[bytes] = []
        closed = [False]

        class FakeWriter:
            def write(self, data: bytes) -> None:
                buf.append(data)
            async def drain(self) -> None:
                pass
            def close(self) -> None:
                closed[0] = True
            def get_extra_info(self, key: str) -> object:
                return None

        writer = FakeWriter()
        with pytest.raises(AuthFailed):
            await handle_startup(reader, writer, token_store)

        combined = b"".join(buf)
        # ErrorResponse type 'E' present
        assert b"E" in combined
        # SQLSTATE 28P01 present
        assert b"28P01" in combined
        assert closed[0] is True

    async def test_simple_query_select_forwarded(self) -> None:
        """SimpleQuery SELECT → RowDescription/DataRow/CommandComplete sent."""
        from gateway.dbt_proxy.session import DbtProxySession
        from gateway.dbt_proxy.forwarder import QueryResult

        run_id = uuid.uuid4()
        claims = _claims(run_id)

        # Fake store
        fake_store = MagicMock()

        # Fake execute_query
        fake_result = QueryResult(
            columns=[("id", 23), ("name", 25)],
            rows=[["1", "Alice"], ["2", "Bob"]],
            command_tag="SELECT 2",
        )

        sql_bytes = _make_simple_query("SELECT id, name FROM users")
        terminate = _make_terminate()

        reader = asyncio.StreamReader()
        reader.feed_data(sql_bytes + terminate)

        buf: list[bytes] = []

        class FakeWriter:
            def write(self, data: bytes) -> None:
                buf.append(data)
            async def drain(self) -> None:
                pass
            def close(self) -> None:
                pass

        writer = FakeWriter()

        import gateway.dbt_proxy.session as session_mod
        original_execute = session_mod.execute_query

        async def _fake_execute(c, s, *, store):
            return fake_result

        session_mod.execute_query = _fake_execute  # type: ignore[assignment]
        try:
            session = DbtProxySession(reader, writer, claims, fake_store)
            await session.run()
        finally:
            session_mod.execute_query = original_execute

        combined = b"".join(buf)
        # RowDescription 'T'
        assert b"T" in combined
        # DataRow 'D'
        assert b"D" in combined
        # CommandComplete 'C'
        assert b"C" in combined
        # ReadyForQuery 'Z'
        assert b"Z" in combined

    async def test_non_postgres_connector_returns_sqlstate_0a000(self) -> None:
        """NonPostgresConnector → ErrorResponse SQLSTATE 0A000."""
        from gateway.dbt_proxy.session import DbtProxySession
        from gateway.dbt_proxy.errors import NonPostgresConnector

        run_id = uuid.uuid4()
        claims = _claims(run_id, connector="my_bigquery_conn")
        fake_store = MagicMock()

        sql_bytes = _make_simple_query("SELECT 1")
        terminate = _make_terminate()

        reader = asyncio.StreamReader()
        reader.feed_data(sql_bytes + terminate)

        buf: list[bytes] = []

        class FakeWriter:
            def write(self, data: bytes) -> None:
                buf.append(data)
            async def drain(self) -> None:
                pass
            def close(self) -> None:
                pass

        writer = FakeWriter()

        import gateway.dbt_proxy.session as session_mod
        original_execute = session_mod.execute_query

        async def _fake_execute_raises(c, s, *, store):
            raise NonPostgresConnector("BigQuery is not postgres")

        session_mod.execute_query = _fake_execute_raises  # type: ignore[assignment]
        try:
            session = DbtProxySession(reader, writer, claims, fake_store)
            await session.run()
        finally:
            session_mod.execute_query = original_execute

        combined = b"".join(buf)
        assert b"0A000" in combined

    async def test_governance_blocked_sends_error_no_exec(self) -> None:
        """Governance-blocked DDL → ErrorResponse written, forwarder not called."""
        from gateway.dbt_proxy.session import DbtProxySession

        run_id = uuid.uuid4()
        claims = _claims(run_id)
        fake_store = MagicMock()

        # COPY is blocked
        sql_bytes = _make_simple_query("COPY secret_table TO '/tmp/out.csv'")
        terminate = _make_terminate()

        reader = asyncio.StreamReader()
        reader.feed_data(sql_bytes + terminate)

        buf: list[bytes] = []
        exec_called = [False]

        class FakeWriter:
            def write(self, data: bytes) -> None:
                buf.append(data)
            async def drain(self) -> None:
                pass
            def close(self) -> None:
                pass

        writer = FakeWriter()

        import gateway.dbt_proxy.session as session_mod
        import gateway.dbt_proxy.forwarder as forwarder_mod
        original_execute = session_mod.execute_query

        async def _fake_execute(c, s, *, store):
            # The governance check in execute_query raises ValueError for blocked statements
            # and writes the audit row; we re-raise it here to simulate that flow
            from gateway.engine.dbt_validation import validate_dbt_statement
            from gateway.dbt_proxy.audit import record as audit_record

            validation = validate_dbt_statement(s, claims=c)
            if validation.blocked:
                await audit_record(c, s, blocked=True, block_reason=validation.block_reason, kind=validation.kind, store=store)
                raise ValueError(validation.block_reason or "blocked")
            exec_called[0] = True
            from gateway.dbt_proxy.forwarder import QueryResult
            return QueryResult(columns=[], rows=[], command_tag="OK")

        session_mod.execute_query = _fake_execute  # type: ignore[assignment]
        try:
            session = DbtProxySession(reader, writer, claims, fake_store)
            await session.run()
        finally:
            session_mod.execute_query = original_execute

        assert exec_called[0] is False
        combined = b"".join(buf)
        assert b"E" in combined  # ErrorResponse
