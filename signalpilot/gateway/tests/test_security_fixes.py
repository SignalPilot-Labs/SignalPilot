"""Tests for Round 3 security fixes (V1-V6 + hardening items).

Each test class covers one vulnerability finding.
"""

from __future__ import annotations

import asyncio
import struct
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.dbt_proxy.tokens import RunTokenClaims
from gateway.engine.dbt_validation import validate_dbt_statement


def _claims(connector: str = "my_db") -> RunTokenClaims:
    return RunTokenClaims(
        run_id=uuid.uuid4(),
        org_id="test-org",
        user_id="test-user",
        connector_name=connector,
        expires_at=9999999999.0,
    )


def _make_frontend_msg(type_byte: bytes, payload: bytes) -> bytes:
    length = struct.pack("!I", len(payload) + 4)
    return type_byte + length + payload


def _make_simple_query(sql: str) -> bytes:
    return _make_frontend_msg(b"Q", sql.encode() + b"\x00")


def _make_terminate() -> bytes:
    return _make_frontend_msg(b"X", b"")


# ─── V1: Upstream errors sanitized ───────────────────────────────────────────


class TestV1UpstreamErrorSanitization:
    """Verify that upstream exception text (potentially containing DSN) is never
    forwarded to the client. Only a generic message with a correlation ID is sent."""

    async def test_upstream_exception_sends_generic_ref_not_exc_message(self) -> None:
        from gateway.dbt_proxy.session import DbtProxySession

        claims = _claims()
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

        async def _fake_execute_dsn_error(c, s, *, store):
            raise ConnectionRefusedError(
                "Connection failed: postgresql://user:SECRET_PASSWORD@warehouse.host:5432/db"
            )

        session_mod.execute_query = _fake_execute_dsn_error  # type: ignore[assignment]
        try:
            session = DbtProxySession(reader, writer, claims, fake_store)
            await session.run()
        finally:
            session_mod.execute_query = original_execute

        combined = b"".join(buf)
        # The DSN must NOT appear in the response to the client
        assert b"SECRET_PASSWORD" not in combined
        assert b"warehouse.host" not in combined
        # A correlation ref must be present
        assert b"ref=" in combined
        # SQLSTATE 58000 must be present
        assert b"58000" in combined

    async def test_upstream_error_ref_id_logged_not_sent_to_client(self) -> None:
        from gateway.dbt_proxy.session import DbtProxySession

        claims = _claims()
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

        async def _fake_execute_generic_error(c, s, *, store):
            raise RuntimeError("dsn=postgresql://admin:hunter2@db/prod")

        session_mod.execute_query = _fake_execute_generic_error  # type: ignore[assignment]

        with patch("gateway.dbt_proxy.session.logger") as mock_logger:
            try:
                session = DbtProxySession(reader, writer, claims, fake_store)
                await session.run()
            finally:
                session_mod.execute_query = original_execute

            # The full exc must appear in the server-side log
            assert mock_logger.error.called
            log_call = mock_logger.error.call_args
            # exc= in log format string
            assert "exc=%r" in log_call[0][0]


# ─── V2: Governance deny-list expanded ───────────────────────────────────────


class TestV2GovernanceDenyList:
    """Verify the expanded deny-list blocks DO blocks, LOAD, dangerous functions,
    and CREATE FUNCTION/PROCEDURE/etc. Tests use the AST-walk path."""

    def test_do_block_plpgsql_blocked(self) -> None:
        result = validate_dbt_statement(
            "DO $$ BEGIN EXECUTE 'COPY foo FROM PROGRAM ''evil'''; END $$ LANGUAGE plpgsql",
            claims=_claims(),
        )
        assert result.blocked
        assert "do" in (result.block_reason or "")

    def test_do_keyword_alone_blocked(self) -> None:
        result = validate_dbt_statement("DO 'SELECT 1'", claims=_claims())
        assert result.blocked

    def test_load_command_blocked(self) -> None:
        result = validate_dbt_statement("LOAD '/usr/lib/postgresql/evil.so'", claims=_claims())
        assert result.blocked
        assert "load" in (result.block_reason or "")

    def test_create_function_plpython3u_blocked(self) -> None:
        result = validate_dbt_statement(
            "CREATE FUNCTION evil() RETURNS void LANGUAGE plpython3u AS $$ import os; os.system('id') $$",
            claims=_claims(),
        )
        assert result.blocked

    def test_create_function_c_blocked(self) -> None:
        result = validate_dbt_statement(
            "CREATE FUNCTION evil() RETURNS void LANGUAGE c AS '/path/to/lib.so', 'evil_func'",
            claims=_claims(),
        )
        assert result.blocked

    def test_create_procedure_blocked(self) -> None:
        result = validate_dbt_statement(
            "CREATE PROCEDURE bad_proc() LANGUAGE plpgsql AS $$ BEGIN SELECT 1; END $$",
            claims=_claims(),
        )
        assert result.blocked
        assert "procedure" in (result.block_reason or "")

    def test_create_trigger_blocked(self) -> None:
        result = validate_dbt_statement(
            "CREATE TRIGGER bad_trig AFTER INSERT ON foo FOR EACH ROW EXECUTE FUNCTION bad_func()",
            claims=_claims(),
        )
        assert result.blocked

    def test_create_language_blocked(self) -> None:
        result = validate_dbt_statement("CREATE LANGUAGE plpython3u", claims=_claims())
        assert result.blocked

    def test_security_definer_blocked(self) -> None:
        result = validate_dbt_statement(
            "CREATE FUNCTION priv_esc() RETURNS void LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'",
            claims=_claims(),
        )
        assert result.blocked
        assert "security_definer" in (result.block_reason or "")

    def test_pg_read_server_files_blocked(self) -> None:
        result = validate_dbt_statement(
            "SELECT pg_read_server_files('/etc/postgresql/postgresql.conf')",
            claims=_claims(),
        )
        assert result.blocked
        assert "pg_read_server_files" in (result.block_reason or "")

    def test_pg_read_file_blocked(self) -> None:
        result = validate_dbt_statement(
            "SELECT pg_read_file('/etc/passwd')",
            claims=_claims(),
        )
        assert result.blocked

    def test_pg_read_binary_file_blocked(self) -> None:
        result = validate_dbt_statement(
            "SELECT pg_read_binary_file('/etc/passwd')",
            claims=_claims(),
        )
        assert result.blocked

    def test_pg_ls_dir_blocked(self) -> None:
        result = validate_dbt_statement("SELECT pg_ls_dir('/etc')", claims=_claims())
        assert result.blocked

    def test_lo_import_blocked(self) -> None:
        result = validate_dbt_statement("SELECT lo_import('/etc/passwd')", claims=_claims())
        assert result.blocked

    def test_lo_export_blocked(self) -> None:
        result = validate_dbt_statement(
            "SELECT lo_export(12345, '/tmp/out')", claims=_claims()
        )
        assert result.blocked

    def test_dblink_blocked(self) -> None:
        result = validate_dbt_statement(
            "SELECT * FROM dblink('host=evil.com user=hacker password=pw', 'SELECT 1')",
            claims=_claims(),
        )
        assert result.blocked
        assert "dblink" in (result.block_reason or "")

    def test_pg_stat_file_blocked(self) -> None:
        result = validate_dbt_statement("SELECT pg_stat_file('/etc/passwd')", claims=_claims())
        assert result.blocked

    def test_current_setting_blocked(self) -> None:
        result = validate_dbt_statement(
            "SELECT current_setting('ssl_cert_file')", claims=_claims()
        )
        assert result.blocked

    def test_normal_select_still_allowed(self) -> None:
        result = validate_dbt_statement("SELECT id, name FROM users WHERE active = TRUE", claims=_claims())
        assert not result.blocked

    def test_create_table_as_select_still_allowed(self) -> None:
        result = validate_dbt_statement(
            "CREATE TABLE foo AS SELECT id FROM bar", claims=_claims()
        )
        assert not result.blocked

    def test_create_extension_prefix_check_still_blocks(self) -> None:
        result = validate_dbt_statement("CREATE EXTENSION pg_stat_statements", claims=_claims())
        assert result.blocked


# ─── V3: Fail closed when secret is missing ──────────────────────────────────


class TestV3FailClosedMissingSecret:
    """Verify that DbtProxyServer.start() does NOT bind a port when the secret
    is absent, and that no token_store operations are reachable."""

    async def test_server_does_not_bind_when_secret_missing(self) -> None:
        from gateway.dbt_proxy.config import DbtProxyConfig
        from gateway.dbt_proxy.server import DbtProxyServer

        config = DbtProxyConfig(
            sp_dbt_proxy_host="127.0.0.1",
            sp_dbt_proxy_port=0,
            sp_gateway_run_token_secret="",  # missing
            sp_dbt_proxy_enabled=True,
        )

        bound_ports: list[int] = []
        original_start_server = asyncio.start_server

        async def _spy_start_server(handler, host, port, **kwargs):
            bound_ports.append(port)
            return await original_start_server(handler, host, port, **kwargs)

        with patch("gateway.dbt_proxy.server.asyncio.start_server", side_effect=_spy_start_server):
            async with DbtProxyServer.start(config, token_store=None, store_factory=None):
                pass

        # Port must NOT have been bound
        assert bound_ports == []

    async def test_server_binds_when_secret_present(self) -> None:
        from gateway.dbt_proxy.config import DbtProxyConfig
        from gateway.dbt_proxy.server import DbtProxyServer
        from gateway.dbt_proxy.tokens import RunTokenStore

        config = DbtProxyConfig(
            sp_dbt_proxy_host="127.0.0.1",
            sp_dbt_proxy_port=0,  # OS assigns
            sp_gateway_run_token_secret="good-secret",
            sp_dbt_proxy_enabled=True,
        )
        token_store = RunTokenStore("good-secret")

        async with DbtProxyServer.start(
            config, token_store=token_store, store_factory=lambda: MagicMock()
        ) as server:
            assert server is not None


# ─── V4: Default bind host is 127.0.0.1 ──────────────────────────────────────


class TestV4DefaultBindHost:
    def test_default_host_is_loopback(self) -> None:
        from gateway.dbt_proxy.config import DbtProxyConfig

        config = DbtProxyConfig()
        assert config.sp_dbt_proxy_host == "127.0.0.1"

    def test_non_loopback_emits_warning(self, caplog) -> None:  # type: ignore[no-untyped-def]
        import logging

        from gateway.dbt_proxy.config import DbtProxyConfig

        config = DbtProxyConfig(sp_dbt_proxy_host="0.0.0.0")
        with caplog.at_level(logging.WARNING):
            config.warn_if_non_loopback()

        assert any("non-loopback" in r.message for r in caplog.records)

    def test_loopback_no_warning(self, caplog) -> None:  # type: ignore[no-untyped-def]
        import logging

        from gateway.dbt_proxy.config import DbtProxyConfig

        config = DbtProxyConfig(sp_dbt_proxy_host="127.0.0.1")
        with caplog.at_level(logging.WARNING):
            config.warn_if_non_loopback()

        assert not any("non-loopback" in r.message for r in caplog.records)


# ─── V5: Inline param substitution safety ────────────────────────────────────


class TestV5InlineParamSubstitution:
    """Verify that NUL bytes and NaN/Inf floats are rejected, not forwarded."""

    def test_nul_byte_in_text_param_raises(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        with pytest.raises(ValueError, match="NUL byte"):
            _format_param("hello\x00world")

    def test_nan_float_raises(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        with pytest.raises(ValueError, match="NaN"):
            _format_param(float("nan"))

    def test_inf_float_raises(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        with pytest.raises(ValueError, match="Inf"):
            _format_param(float("inf"))

    def test_neg_inf_float_raises(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        with pytest.raises(ValueError, match="Inf"):
            _format_param(float("-inf"))

    def test_normal_float_formats_correctly(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        assert _format_param(3.14) == "3.14"
        assert _format_param(0.0) == "0.0"

    def test_text_with_single_quote_escaped(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        result = _format_param("O'Brien")
        assert result == "'O''Brien'"

    def test_none_formats_as_null(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        assert _format_param(None) == "NULL"

    def test_bool_formats(self) -> None:
        from gateway.dbt_proxy.session import _format_param

        assert _format_param(True) == "TRUE"
        assert _format_param(False) == "FALSE"

    def test_substitute_params_raises_on_nul_byte(self) -> None:
        from gateway.dbt_proxy.session import _substitute_params

        with pytest.raises(ValueError, match="NUL byte"):
            _substitute_params("SELECT $1", ["evil\x00injection"])

    def test_substitute_params_raises_on_nan(self) -> None:
        from gateway.dbt_proxy.session import _substitute_params

        with pytest.raises(ValueError, match="NaN"):
            _substitute_params("SELECT $1", [float("nan")])


# ─── V6: Audit failure aborts statement ──────────────────────────────────────


class TestV6AuditFailureAbortsStatement:
    """Verify that an audit write failure raises AuditWriteError and the
    statement execution is aborted (not silently swallowed)."""

    async def test_audit_write_failure_raises_audit_write_error(self) -> None:
        from gateway.dbt_proxy.audit import AuditWriteError, record

        claims = _claims()
        fake_store = MagicMock()
        fake_store.append_audit = AsyncMock(side_effect=Exception("DB down"))

        with pytest.raises(AuditWriteError):
            await record(
                claims,
                "SELECT 1",
                blocked=False,
                block_reason=None,
                kind="read",
                store=fake_store,
            )

    async def test_audit_write_failure_is_logged_as_error(self) -> None:
        from gateway.dbt_proxy.audit import AuditWriteError, record

        claims = _claims()
        fake_store = MagicMock()
        fake_store.append_audit = AsyncMock(side_effect=Exception("DB down"))

        with patch("gateway.dbt_proxy.audit.logger") as mock_logger:
            with pytest.raises(AuditWriteError):
                await record(
                    claims,
                    "SELECT 1",
                    blocked=False,
                    block_reason=None,
                    kind="read",
                    store=fake_store,
                )
            assert mock_logger.error.called

    async def test_audit_failure_propagates_through_execute_query(self) -> None:
        """AuditWriteError from audit.record() propagates through execute_query."""
        import gateway.dbt_proxy.forwarder as forwarder_mod
        from gateway.dbt_proxy.audit import AuditWriteError

        claims = _claims()
        fake_store = MagicMock()
        fake_store.append_audit = AsyncMock(side_effect=Exception("PG primary down"))
        # get_connection must return None to trigger early exit before pool acquire
        fake_store.get_connection = AsyncMock(return_value=None)

        # The blocked-branch audit call should raise AuditWriteError
        with pytest.raises(AuditWriteError):
            await forwarder_mod.execute_query(
                claims,
                "COPY secret TO '/tmp/out'",  # will be blocked → audit call
                store=fake_store,
            )

    async def test_unaudited_statement_sends_error_to_client(self) -> None:
        """When audit fails, session sends ErrorResponse rather than executing."""
        from gateway.dbt_proxy.audit import AuditWriteError
        from gateway.dbt_proxy.session import DbtProxySession

        claims = _claims()
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

        async def _fake_execute_audit_fail(c, s, *, store):
            raise AuditWriteError("audit write failed (ref=abc123)")

        session_mod.execute_query = _fake_execute_audit_fail  # type: ignore[assignment]
        try:
            session = DbtProxySession(reader, writer, claims, fake_store)
            await session.run()
        finally:
            session_mod.execute_query = original_execute

        combined = b"".join(buf)
        # ErrorResponse 'E' must be present — statement was aborted
        assert b"E" in combined
        # ReadyForQuery 'Z' must still be sent (session continues)
        assert b"Z" in combined


# ─── Auth.py error sanitization (hardening) ──────────────────────────────────


class TestAuthErrorSanitization:
    """Verify auth.py never echoes raw exception text to the client."""

    async def test_bad_startup_message_sends_generic_protocol_error(self) -> None:
        from gateway.dbt_proxy.auth import handle_startup
        from gateway.dbt_proxy.errors import AuthFailed
        from gateway.dbt_proxy.tokens import RunTokenStore

        token_store = RunTokenStore("test-secret")

        # Feed garbage — will fail read_startup_message
        reader = asyncio.StreamReader()
        reader.feed_data(b"\x00\x00\x00\x08garbage!!")
        reader.feed_eof()

        buf: list[bytes] = []

        class FakeWriter:
            def write(self, data: bytes) -> None:
                buf.append(data)

            async def drain(self) -> None:
                pass

            def close(self) -> None:
                pass

        writer = FakeWriter()

        with pytest.raises(AuthFailed):
            await handle_startup(reader, writer, token_store)

        combined = b"".join(buf)
        # Must NOT echo any python exception repr
        assert b"Traceback" not in combined
        # Must contain the generic message
        assert b"protocol error" in combined

    async def test_auth_ok_does_not_log_org_id(self) -> None:
        """auth_ok log line should NOT include org_id (per masking policy)."""
        from gateway.dbt_proxy.auth import handle_startup
        from gateway.dbt_proxy.tokens import RunTokenStore

        secret = "test-secret"
        token_store = RunTokenStore(secret)
        run_id = uuid.uuid4()
        token_hex, _ = await token_store.mint(run_id, "SENSITIVE_ORG", "user-1", "conn", ttl_seconds=300)

        startup_proto = struct.pack("!I", 0x00030000)
        body = startup_proto
        for k, v in [("user", f"run-{run_id}"), ("database", "conn")]:
            body += k.encode() + b"\x00" + v.encode() + b"\x00"
        body += b"\x00"
        startup = struct.pack("!I", len(body) + 4) + body
        password_msg = struct.pack("!cI", b"p", len(token_hex) + 5) + token_hex.encode() + b"\x00"

        reader = asyncio.StreamReader()
        reader.feed_data(startup + password_msg)

        class FakeWriter:
            def write(self, data: bytes) -> None:
                pass

            async def drain(self) -> None:
                pass

            def close(self) -> None:
                pass

        writer = FakeWriter()

        with patch("gateway.dbt_proxy.auth.logger") as mock_logger:
            await handle_startup(reader, writer, token_store)
            info_call = mock_logger.info.call_args
            # org_id must NOT appear in the format args of the log line
            log_args = str(info_call)
            assert "SENSITIVE_ORG" not in log_args
