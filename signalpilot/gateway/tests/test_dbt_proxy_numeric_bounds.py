"""Tests for the NUMERIC binary weight cap and Fix 3-bis propagation.

Covers:
- _parse_numeric_binary: weight cap (±MAX_NUMERIC_WEIGHT), at-cap regression,
  ndigits cap regression.
- _handle_bind: ValueError from parse_bind_value is caught and emits
  ErrorResponse with SQLSTATE 22P03 (covers both ndigits and weight caps).
"""

from __future__ import annotations

import asyncio
import struct
import time
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from gateway.dbt_proxy.protocol import (
    MAX_NUMERIC_WEIGHT,
    _parse_numeric_binary,
)
from gateway.dbt_proxy.session import DbtProxySession
from gateway.dbt_proxy.tokens import RunTokenClaims


def _build_numeric_header(
    ndigits: int,
    weight: int,
    sign: int = 0x0000,
    dscale: int = 0,
) -> bytes:
    """Build the 8-byte NUMERIC binary header (no digit data appended)."""
    return struct.pack("!HhHH", ndigits, weight, sign, dscale)


def _build_numeric_binary(
    ndigits: int,
    weight: int,
    digits: list[int],
    sign: int = 0x0000,
    dscale: int = 0,
) -> bytes:
    """Build a complete binary NUMERIC payload."""
    header = _build_numeric_header(ndigits, weight, sign, dscale)
    return header + struct.pack(f"!{ndigits}H", *digits)


def _build_bind_payload_with_numeric_binary(raw_numeric: bytes) -> bytes:
    """Build a Bind message payload containing one binary NUMERIC parameter."""
    from gateway.dbt_proxy.protocol import OID_NUMERIC

    portal = b"\x00"         # unnamed portal
    stmt = b"s\x00"          # statement name "s"
    n_formats = struct.pack("!H", 1)
    fmt_binary = struct.pack("!H", 1)   # binary format for all params
    n_params = struct.pack("!H", 1)
    param_len = struct.pack("!i", len(raw_numeric))
    return portal + stmt + n_formats + fmt_binary + n_params + param_len + raw_numeric


class FakeWriter:
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


def _make_session_with_stmt(stmt_name: str) -> tuple[DbtProxySession, FakeWriter]:
    """Return a session pre-loaded with one named statement backed by OID_NUMERIC."""
    from gateway.dbt_proxy.protocol import OID_NUMERIC

    reader = asyncio.StreamReader()
    writer = FakeWriter()
    claims = RunTokenClaims(
        run_id=uuid.uuid4(),
        org_id="org-1",
        user_id="user-1",
        connector_name="my_conn",
        expires_at=9999999999.0,
    )
    session = DbtProxySession(reader, writer, claims, MagicMock())
    # Inject one statement directly (bypassing Parse message path)
    session._named_stmts[stmt_name] = ("SELECT $1", [OID_NUMERIC])
    return session, writer


class TestParseNumericBinaryWeightCap:
    """_parse_numeric_binary must reject |weight| > MAX_NUMERIC_WEIGHT."""

    def test_weight_max_positive_raises(self) -> None:
        """weight = +32767 → ValueError mentioning 'weight' and the cap value."""
        raw = _build_numeric_header(ndigits=0, weight=32767)

        t0 = time.monotonic()
        with pytest.raises(ValueError, match="weight") as exc_info:
            _parse_numeric_binary(raw)
        elapsed = time.monotonic() - t0

        assert str(MAX_NUMERIC_WEIGHT) in str(exc_info.value)
        assert elapsed < 0.1, "loop must not have run before rejection"

    def test_weight_max_negative_raises(self) -> None:
        """weight = -32768 → ValueError mentioning 'weight' and the cap value."""
        raw = _build_numeric_header(ndigits=0, weight=-32768)

        t0 = time.monotonic()
        with pytest.raises(ValueError, match="weight") as exc_info:
            _parse_numeric_binary(raw)
        elapsed = time.monotonic() - t0

        assert str(MAX_NUMERIC_WEIGHT) in str(exc_info.value)
        assert elapsed < 0.1

    def test_weight_at_positive_cap_succeeds(self) -> None:
        """weight = MAX_NUMERIC_WEIGHT with ndigits=1 → returns a Decimal."""
        digits = [1]
        raw = _build_numeric_binary(
            ndigits=1, weight=MAX_NUMERIC_WEIGHT, digits=digits
        )
        result = _parse_numeric_binary(raw)
        assert isinstance(result, Decimal)

    def test_weight_one_over_positive_cap_raises(self) -> None:
        """weight = MAX_NUMERIC_WEIGHT + 1 → ValueError."""
        raw = _build_numeric_header(ndigits=1, weight=MAX_NUMERIC_WEIGHT + 1)
        with pytest.raises(ValueError, match="weight"):
            _parse_numeric_binary(raw)

    def test_ndigits_cap_still_enforced(self) -> None:
        """Regression: ndigits > 1000 must still raise (M-8 fix unchanged)."""
        raw = _build_numeric_header(ndigits=1001, weight=0)
        with pytest.raises(ValueError, match="ndigits"):
            _parse_numeric_binary(raw)


class TestHandleBindNumericErrorPropagation:
    """Fix 3-bis: _handle_bind must catch ValueError from parse_bind_value."""

    @pytest.mark.asyncio
    async def test_weight_overflow_returns_error_response_22p03(self) -> None:
        """weight=32767 Bind → ErrorResponse with SQLSTATE 22P03, no raise."""
        session, writer = _make_session_with_stmt("s")

        raw_numeric = _build_numeric_header(ndigits=0, weight=32767)
        bind_payload = _build_bind_payload_with_numeric_binary(raw_numeric)

        # Must not raise — the error must be written to the writer
        await session._handle_bind(bind_payload)

        combined = writer.combined
        assert b"22P03" in combined, "expected SQLSTATE 22P03 in ErrorResponse"
        assert b"E" in combined, "expected ErrorResponse type byte"
        assert session._named_portals == {}, "_named_portals must be unchanged"

    @pytest.mark.asyncio
    async def test_ndigits_overflow_returns_error_response_22p03(self) -> None:
        """ndigits=1001 Bind → ErrorResponse with SQLSTATE 22P03, no raise.

        Regression for M-8: the pre-existing ndigits cap ValueError must now
        also produce a proper ErrorResponse instead of propagating out of run().
        """
        session, writer = _make_session_with_stmt("s")

        raw_numeric = _build_numeric_header(ndigits=1001, weight=0)
        bind_payload = _build_bind_payload_with_numeric_binary(raw_numeric)

        await session._handle_bind(bind_payload)

        combined = writer.combined
        assert b"22P03" in combined, "expected SQLSTATE 22P03 in ErrorResponse"
        assert b"E" in combined, "expected ErrorResponse type byte"
        assert session._named_portals == {}, "_named_portals must be unchanged"

    @pytest.mark.asyncio
    async def test_valid_numeric_bind_succeeds(self) -> None:
        """A valid binary NUMERIC Bind succeeds and produces BindComplete."""
        session, writer = _make_session_with_stmt("s")

        # weight=1, ndigits=1, digit=42 → 42 * 10000^1 = 420000
        raw_numeric = _build_numeric_binary(ndigits=1, weight=1, digits=[42])
        bind_payload = _build_bind_payload_with_numeric_binary(raw_numeric)

        await session._handle_bind(bind_payload)

        combined = writer.combined
        assert b"22P03" not in combined, "no error expected for valid numeric"
        assert b"2" in combined, "expected BindComplete"
        assert "" in session._named_portals, "unnamed portal should be stored"
