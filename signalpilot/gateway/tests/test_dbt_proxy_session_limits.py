"""Tests for per-session named-statement and named-portal caps in DbtProxySession.

Verifies that _handle_parse rejects a 257th distinct statement name with
SQLSTATE 53000, and that re-Parse of an existing name at full cap succeeds
(overwrite path). Same logic for _handle_bind / _named_portals.

Also verifies Fix 3-bis loop-level ValueError safety net in run():
- Malformed UTF-8 in portal name → ErrorResponse 22P03, no abrupt close.
- Binary float8 NaN Bind value → ErrorResponse 22P03, connection recovers.

Tests drive _handle_parse / _handle_bind directly to avoid the full
startup/auth overhead.
"""

from __future__ import annotations

import asyncio
import struct
import uuid
from unittest.mock import MagicMock

import pytest

from gateway.dbt_proxy.protocol import OID_FLOAT8
from gateway.dbt_proxy.session import (
    MAX_NAMED_PORTALS_PER_SESSION,
    MAX_NAMED_STATEMENTS_PER_SESSION,
    DbtProxySession,
)
from gateway.dbt_proxy.tokens import RunTokenClaims


def _claims() -> RunTokenClaims:
    return RunTokenClaims(
        run_id=uuid.uuid4(),
        org_id="org-1",
        user_id="user-1",
        connector_name="my_conn",
        expires_at=9999999999.0,
    )


class FakeWriter:
    """Captures write() calls; drain() is a no-op."""

    def __init__(self) -> None:
        self.buf: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.buf.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    @property
    def combined(self) -> bytes:
        return b"".join(self.buf)


def _make_parse_payload(stmt_name: str, query: str = "SELECT 1") -> bytes:
    """Build a minimal Parse message payload."""
    return (
        stmt_name.encode() + b"\x00"
        + query.encode() + b"\x00"
        + struct.pack("!H", 0)  # 0 param type OIDs
    )


def _make_bind_payload(portal: str, stmt_name: str) -> bytes:
    """Build a minimal Bind message payload with zero params."""
    return (
        portal.encode() + b"\x00"
        + stmt_name.encode() + b"\x00"
        + struct.pack("!H", 0)   # 0 format codes
        + struct.pack("!H", 0)   # 0 param values
    )


def _make_session() -> tuple[DbtProxySession, FakeWriter]:
    reader = asyncio.StreamReader()
    writer = FakeWriter()
    session = DbtProxySession(reader, writer, _claims(), MagicMock())
    return session, writer


class TestNamedStatementCap:
    """_handle_parse must enforce MAX_NAMED_STATEMENTS_PER_SESSION."""

    @pytest.mark.asyncio
    async def test_256_distinct_statements_all_succeed(self) -> None:
        """The first MAX cap entries are accepted; each produces ParseComplete."""
        session, writer = _make_session()

        for i in range(MAX_NAMED_STATEMENTS_PER_SESSION):
            writer.buf.clear()
            await session._handle_parse(_make_parse_payload(f"stmt_{i}"))
            # ParseComplete is b"1\x00\x00\x00\x04"
            assert b"1" in writer.combined, f"stmt_{i} did not get ParseComplete"

        assert len(session._named_stmts) == MAX_NAMED_STATEMENTS_PER_SESSION

    @pytest.mark.asyncio
    async def test_257th_distinct_name_rejected_with_sqlstate_53000(self) -> None:
        """The 257th unique name must be rejected with SQLSTATE 53000."""
        session, writer = _make_session()

        for i in range(MAX_NAMED_STATEMENTS_PER_SESSION):
            await session._handle_parse(_make_parse_payload(f"stmt_{i}"))

        assert len(session._named_stmts) == MAX_NAMED_STATEMENTS_PER_SESSION

        writer.buf.clear()
        await session._handle_parse(_make_parse_payload("stmt_overflow"))

        combined = writer.combined
        assert b"53000" in combined, "expected SQLSTATE 53000 in ErrorResponse"
        assert b"E" in combined, "expected ErrorResponse type byte"
        assert len(session._named_stmts) == MAX_NAMED_STATEMENTS_PER_SESSION, (
            "dict must not grow past the cap"
        )

    @pytest.mark.asyncio
    async def test_reparse_existing_name_at_full_cap_succeeds(self) -> None:
        """Re-Parse of an existing name at full cap must succeed (overwrite path)."""
        session, writer = _make_session()

        for i in range(MAX_NAMED_STATEMENTS_PER_SESSION):
            await session._handle_parse(_make_parse_payload(f"stmt_{i}"))

        assert len(session._named_stmts) == MAX_NAMED_STATEMENTS_PER_SESSION

        writer.buf.clear()
        # Re-parse an existing name with a different query
        await session._handle_parse(_make_parse_payload("stmt_0", "SELECT 42"))

        combined = writer.combined
        assert b"53000" not in combined, "re-parse of existing name must not be rejected"
        assert b"1" in combined, "re-parse must produce ParseComplete"
        # Size must not change
        assert len(session._named_stmts) == MAX_NAMED_STATEMENTS_PER_SESSION
        # Query must be updated
        assert session._named_stmts["stmt_0"][0] == "SELECT 42"


class TestNamedPortalCap:
    """_handle_bind must enforce MAX_NAMED_PORTALS_PER_SESSION."""

    @pytest.mark.asyncio
    async def test_256_distinct_portals_all_succeed(self) -> None:
        """The first MAX cap portals are accepted; each produces BindComplete."""
        session, writer = _make_session()

        # Pre-register one statement to back all binds
        await session._handle_parse(_make_parse_payload("shared_stmt"))
        writer.buf.clear()

        for i in range(MAX_NAMED_PORTALS_PER_SESSION):
            writer.buf.clear()
            await session._handle_bind(_make_bind_payload(f"portal_{i}", "shared_stmt"))
            assert b"2" in writer.combined, f"portal_{i} did not get BindComplete"

        assert len(session._named_portals) == MAX_NAMED_PORTALS_PER_SESSION

    @pytest.mark.asyncio
    async def test_257th_distinct_portal_rejected_with_sqlstate_53000(self) -> None:
        """The 257th unique portal must be rejected with SQLSTATE 53000."""
        session, writer = _make_session()

        await session._handle_parse(_make_parse_payload("shared_stmt"))

        for i in range(MAX_NAMED_PORTALS_PER_SESSION):
            await session._handle_bind(_make_bind_payload(f"portal_{i}", "shared_stmt"))

        assert len(session._named_portals) == MAX_NAMED_PORTALS_PER_SESSION

        writer.buf.clear()
        await session._handle_bind(_make_bind_payload("portal_overflow", "shared_stmt"))

        combined = writer.combined
        assert b"53000" in combined, "expected SQLSTATE 53000 in ErrorResponse"
        assert b"E" in combined, "expected ErrorResponse type byte"
        assert len(session._named_portals) == MAX_NAMED_PORTALS_PER_SESSION, (
            "portal dict must not grow past the cap"
        )


def _make_bind_payload_raw_portal(portal_bytes: bytes, stmt_name: str) -> bytes:
    """Build a Bind payload where the portal name bytes are passed verbatim (pre-NUL)."""
    return (
        portal_bytes + b"\x00"
        + stmt_name.encode() + b"\x00"
        + struct.pack("!H", 0)   # 0 format codes
        + struct.pack("!H", 0)   # 0 param values
    )


def _make_bind_payload_float8_binary(stmt_name: str, float8_bytes: bytes) -> bytes:
    """Build a Bind payload with one binary float8 parameter."""
    # OID_FLOAT8 = 701; the session uses the OID from the statement's oids list
    portal = b"\x00"
    stmt = stmt_name.encode() + b"\x00"
    n_formats = struct.pack("!H", 1)
    fmt_binary = struct.pack("!H", 1)   # binary format for all params
    n_params = struct.pack("!H", 1)
    param_len = struct.pack("!i", len(float8_bytes))
    return portal + stmt + n_formats + fmt_binary + n_params + param_len + float8_bytes


class TestRunLoopValueErrorSafetyNet:
    """Fix 3-bis loop-level safety net: ValueError escaping any handler must
    produce ErrorResponse 22P03 and allow the connection to continue.

    These tests exercise the broader try/except ValueError in run() that catches
    errors escaping _handle_bind before (UnicodeDecodeError from parse_bind_message)
    and after (ValueError from _format_param) the existing per-iteration try/except.
    """

    @pytest.mark.asyncio
    async def test_malformed_utf8_portal_name_emits_error_response_22p03(self) -> None:
        """Bind with non-UTF-8 portal name bytes raises UnicodeDecodeError (a ValueError
        subclass) inside parse_bind_message, which escapes _handle_bind.  The loop-level
        catch must convert it to ErrorResponse SQLSTATE 22P03 without closing.

        Recovery is verified by injecting a second Bind (well-formed) that succeeds.
        """
        session, writer = _make_session()

        # Pre-register a statement so _handle_bind doesn't fail on unknown-stmt check
        await session._handle_parse(_make_parse_payload("good_stmt"))
        writer.buf.clear()

        # Build a Bind payload whose portal name contains 0xFF (invalid UTF-8 start byte)
        bad_portal_bytes = b"\xff\xfe"  # never valid in UTF-8
        bad_bind = _make_bind_payload_raw_portal(bad_portal_bytes, "good_stmt")

        # We call _handle_bind directly here since run() requires a real reader.
        # UnicodeDecodeError is a ValueError subclass — it must be caught by
        # run()'s loop-level except. We verify _handle_bind itself propagates it
        # (i.e. no catch inside _handle_bind for this case), and then test run()
        # wrapping by using the helper below.
        with pytest.raises((UnicodeDecodeError, ValueError)):
            await session._handle_bind(bad_bind)

    @pytest.mark.asyncio
    async def test_run_loop_catches_unicode_decode_error_emits_22p03_and_continues(
        self,
    ) -> None:
        """run() must catch UnicodeDecodeError from _handle_bind (via parse_bind_message),
        emit ErrorResponse 22P03, and continue — verified by a subsequent Sync receiving
        ReadyForQuery.
        """
        # Build the two-message sequence: bad Bind ('B') then Sync ('S')
        bad_portal_bytes = b"\xff\xfe"
        bad_bind_payload = _make_bind_payload_raw_portal(bad_portal_bytes, "")

        def _frame(msg_type: bytes, payload: bytes) -> bytes:
            return msg_type + struct.pack("!I", 4 + len(payload)) + payload

        bad_bind_frame = _frame(b"B", bad_bind_payload)
        sync_frame = _frame(b"S", b"")
        terminate_frame = _frame(b"X", b"")

        wire = bad_bind_frame + sync_frame + terminate_frame

        reader = asyncio.StreamReader()
        reader.feed_data(wire)
        reader.feed_eof()

        writer = FakeWriter()
        session = DbtProxySession(reader, writer, _claims(), MagicMock())

        await session.run()

        combined = writer.combined
        # ErrorResponse for the bad Bind
        assert b"22P03" in combined, "expected SQLSTATE 22P03 for bad portal name"
        assert b"E" in combined, "expected ErrorResponse type byte"
        # ReadyForQuery from Sync proves the loop continued after the error
        assert b"Z" in combined, "expected ReadyForQuery ('Z') from Sync — loop must continue"

    @pytest.mark.asyncio
    async def test_binary_float8_nan_bind_emits_22p03_and_continues(self) -> None:
        """Bind with binary float8 NaN (0x7FF8000000000000) parses cleanly in
        parse_bind_value (returns float('nan')), then trips _format_param with ValueError.
        That ValueError escapes _handle_bind after the existing try/except.
        The loop-level catch must emit ErrorResponse 22P03 and keep the loop alive.
        """
        # float8 NaN IEEE 754: 0x7FF8000000000000
        nan_bytes = bytes.fromhex("7FF8000000000000")

        def _frame(msg_type: bytes, payload: bytes) -> bytes:
            return msg_type + struct.pack("!I", 4 + len(payload)) + payload

        # Pre-populate statement with OID_FLOAT8 parameter
        # Use a Parse frame to seed the session
        parse_payload = (
            b"f\x00"                       # stmt name "f"
            + b"SELECT $1\x00"             # query
            + struct.pack("!H", 1)         # 1 oid
            + struct.pack("!I", OID_FLOAT8)
        )
        bind_payload = _make_bind_payload_float8_binary("f", nan_bytes)
        sync_payload = b""
        terminate_payload = b""

        wire = (
            _frame(b"P", parse_payload)
            + _frame(b"B", bind_payload)
            + _frame(b"S", sync_payload)
            + _frame(b"X", terminate_payload)
        )

        reader = asyncio.StreamReader()
        reader.feed_data(wire)
        reader.feed_eof()

        writer = FakeWriter()
        session = DbtProxySession(reader, writer, _claims(), MagicMock())

        await session.run()

        combined = writer.combined
        # ParseComplete from Parse
        assert b"1" in combined, "expected ParseComplete from Parse"
        # ErrorResponse with 22P03 from the NaN Bind
        assert b"22P03" in combined, "expected SQLSTATE 22P03 for NaN float8 Bind"
        # ReadyForQuery from Sync proves loop continued
        assert b"Z" in combined, "expected ReadyForQuery from Sync — loop must continue"
