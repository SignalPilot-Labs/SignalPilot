"""Tests for the slowloris read-timeout hardening in the dbt-proxy protocol module.

Verifies that read_exact (and therefore read_startup_message /
read_frontend_message) raise ValueError when the peer sends a frame header
but stalls the body, and that the timeout fires fast (wall-clock < 1.0 s).

READ_TIMEOUT_SECONDS is monkeypatched to 0.05 s in the slow tests to keep
the suite fast.  The patch works because read_exact reads the module-level
name at call time (not as a default arg).
"""

from __future__ import annotations

import asyncio
import struct
import time

import pytest

import gateway.dbt_proxy.protocol as protocol
from gateway.dbt_proxy.protocol import (
    read_frontend_message,
    read_startup_message,
)

_FAST_TIMEOUT = 0.05  # seconds — monkeypatched value for slow-path tests


class TestSlowlorisTimeout:
    """read_exact must time out and raise ValueError when a peer stalls."""

    @pytest.mark.asyncio
    async def test_startup_slowloris_body_never_arrives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Startup: header arrives, body never does → ValueError within 1 s.

        The length value (100) is within the cap, so if the implementation
        allocates memory before timing out the test would hang.  Instead, the
        await on read_exact(reader, 96) must time out.
        """
        monkeypatch.setattr(protocol, "READ_TIMEOUT_SECONDS", _FAST_TIMEOUT)

        total_length = 100
        length_bytes = struct.pack("!I", total_length)
        reader = asyncio.StreamReader()
        reader.feed_data(length_bytes)
        # No body — reader remains open (not EOF)

        t0 = time.monotonic()
        with pytest.raises(ValueError, match="read timed out"):
            await read_startup_message(reader)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"timeout fired too late: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_frontend_slowloris_body_never_arrives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Frontend: type byte + length header arrive, body never does → ValueError."""
        monkeypatch.setattr(protocol, "READ_TIMEOUT_SECONDS", _FAST_TIMEOUT)

        payload_len = 100
        # length field includes itself (4 bytes)
        header = b"Q" + struct.pack("!I", payload_len + 4)
        reader = asyncio.StreamReader()
        reader.feed_data(header)
        # No payload bytes fed

        t0 = time.monotonic()
        with pytest.raises(ValueError, match="read timed out"):
            await read_frontend_message(reader)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"timeout fired too late: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_header_slowloris_length_bytes_never_arrive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Frontend: only the type byte arrives, length bytes stall → ValueError.

        The very first read_exact(reader, 4) call (for the length field) must
        time out, proving the timeout applies to every read_exact invocation.
        """
        monkeypatch.setattr(protocol, "READ_TIMEOUT_SECONDS", _FAST_TIMEOUT)

        reader = asyncio.StreamReader()
        reader.feed_data(b"Q")
        # No length bytes fed

        t0 = time.monotonic()
        with pytest.raises(ValueError, match="read timed out"):
            await read_frontend_message(reader)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"timeout fired too late: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_fast_path_full_message_succeeds(self) -> None:
        """A fully-buffered valid message succeeds without spurious timeout.

        Uses the real 30 s READ_TIMEOUT_SECONDS — the data is pre-fed into
        the StreamReader so readexactly() returns immediately; no timeout risk.
        """
        query = b"SELECT 1\x00"
        length = struct.pack("!I", len(query) + 4)
        raw = b"Q" + length + query

        reader = asyncio.StreamReader()
        reader.feed_data(raw)

        msg_type, payload = await read_frontend_message(reader)

        assert msg_type == "Q"
        assert payload == query

    @pytest.mark.asyncio
    async def test_fast_path_large_message_succeeds(self) -> None:
        """A near-cap (16 MiB-1) fully-buffered message succeeds without timeout.

        Confirms that the timeout constant is not set so low it rejects
        legitimate large payloads whose data is already available in the buffer.
        """
        from gateway.dbt_proxy.protocol import MAX_FRONTEND_MESSAGE_LEN

        payload = b"\x00" * (MAX_FRONTEND_MESSAGE_LEN - 4)
        length = struct.pack("!I", len(payload) + 4)
        raw = b"B" + length + payload

        reader = asyncio.StreamReader(limit=MAX_FRONTEND_MESSAGE_LEN + 8)
        reader.feed_data(raw)

        msg_type, result_payload = await read_frontend_message(reader)

        assert msg_type == "B"
        assert len(result_payload) == MAX_FRONTEND_MESSAGE_LEN - 4
