"""Tests for wire-frame size limits in the pg-wire v3 protocol framing module.

Verifies that read_startup_message and read_frontend_message reject
attacker-controlled oversized length fields BEFORE allocating memory,
preventing OOM via uint32-amplified readexactly() calls.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from gateway.dbt_proxy.protocol import (
    MAX_FRONTEND_MESSAGE_LEN,
    MAX_STARTUP_MESSAGE_LEN,
    read_frontend_message,
    read_startup_message,
)


def _make_startup_message(params: dict[str, str]) -> bytes:
    """Build a valid StartupMessage with protocol version 3.0."""
    proto = struct.pack("!I", 0x00030000)
    body = proto
    for k, v in params.items():
        body += k.encode() + b"\x00" + v.encode() + b"\x00"
    body += b"\x00"
    total_length = struct.pack("!I", len(body) + 4)
    return total_length + body


def _make_frontend_message(msg_type: bytes, payload: bytes) -> bytes:
    """Build a valid typed frontend message frame."""
    length = struct.pack("!I", len(payload) + 4)
    return msg_type + length + payload


class TestStartupMessageLimits:
    """read_startup_message must reject oversized length fields before allocation."""

    @pytest.mark.asyncio
    async def test_rejects_oversize_length(self) -> None:
        """A length field of MAX_STARTUP_MESSAGE_LEN + 1 raises ValueError immediately.

        We supply only the 4-byte length header (no body data), so if the
        implementation attempted readexactly() for the oversized body it would
        block waiting for data that never arrives — the test would hang rather
        than pass, proving the cap fires before the read.
        """
        oversize_length = MAX_STARTUP_MESSAGE_LEN + 1
        length_bytes = struct.pack("!I", oversize_length)
        reader = asyncio.StreamReader()
        reader.feed_data(length_bytes)
        reader.feed_eof()

        with pytest.raises(ValueError, match="too large"):
            await read_startup_message(reader)

    @pytest.mark.asyncio
    async def test_accepts_realistic_size(self) -> None:
        """A normal startup message (~200 bytes) parses correctly."""
        params = {
            "user": "run-abc123",
            "database": "my_connector",
            "application_name": "dbt",
        }
        raw = _make_startup_message(params)
        reader = asyncio.StreamReader()
        reader.feed_data(raw)

        result = await read_startup_message(reader)

        assert result["user"] == "run-abc123"
        assert result["database"] == "my_connector"
        assert result["application_name"] == "dbt"

    @pytest.mark.asyncio
    async def test_rejects_length_below_minimum(self) -> None:
        """A length field below 8 raises ValueError (regression for existing check)."""
        length_bytes = struct.pack("!I", 7)
        reader = asyncio.StreamReader()
        reader.feed_data(length_bytes)
        reader.feed_eof()

        with pytest.raises(ValueError, match="too short"):
            await read_startup_message(reader)


class TestFrontendMessageLimits:
    """read_frontend_message must reject oversized length fields before allocation."""

    @pytest.mark.asyncio
    async def test_rejects_oversize_length(self) -> None:
        """A length field of MAX_FRONTEND_MESSAGE_LEN + 1 raises ValueError immediately.

        Only the type byte and 4-byte length header are supplied; if the
        implementation tried readexactly() for the body the test would hang,
        proving the cap fires before any allocation.
        """
        oversize_length = MAX_FRONTEND_MESSAGE_LEN + 1
        header = b"Q" + struct.pack("!I", oversize_length)
        reader = asyncio.StreamReader()
        reader.feed_data(header)
        reader.feed_eof()

        with pytest.raises(ValueError, match="too large"):
            await read_frontend_message(reader)

    @pytest.mark.asyncio
    async def test_accepts_at_cap(self) -> None:
        """An exact MAX_FRONTEND_MESSAGE_LEN payload parses (boundary-inclusive)."""
        payload = b"\x00" * (MAX_FRONTEND_MESSAGE_LEN - 4)
        raw = _make_frontend_message(b"Q", payload)
        reader = asyncio.StreamReader(limit=MAX_FRONTEND_MESSAGE_LEN + 8)
        reader.feed_data(raw)

        msg_type, result_payload = await read_frontend_message(reader)

        assert msg_type == "Q"
        assert len(result_payload) == MAX_FRONTEND_MESSAGE_LEN - 4

    @pytest.mark.asyncio
    async def test_rejects_length_below_four(self) -> None:
        """A length field below 4 raises ValueError (regression for existing check)."""
        header = b"Q" + struct.pack("!I", 3)
        reader = asyncio.StreamReader()
        reader.feed_data(header)
        reader.feed_eof()

        with pytest.raises(ValueError, match="Invalid message length"):
            await read_frontend_message(reader)

    @pytest.mark.asyncio
    async def test_accepts_small_message(self) -> None:
        """A small valid SimpleQuery message parses correctly."""
        query = b"SELECT 1\x00"
        raw = _make_frontend_message(b"Q", query)
        reader = asyncio.StreamReader()
        reader.feed_data(raw)

        msg_type, payload = await read_frontend_message(reader)

        assert msg_type == "Q"
        assert payload == query
