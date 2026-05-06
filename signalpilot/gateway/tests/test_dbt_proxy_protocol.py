"""Tests for the pg-wire v3 protocol framing module."""

from __future__ import annotations

import struct
import asyncio
import uuid

import pytest

from gateway.dbt_proxy.protocol import (
    OID_BOOL,
    OID_INT4,
    OID_TEXT,
    OID_TIMESTAMPTZ,
    UnsupportedOID,
    parse_bind_value,
    read_startup_message,
    write_data_row,
    write_error_response,
    write_row_description,
)


def _make_startup_payload(params: dict[str, str]) -> bytes:
    """Build a realistic StartupMessage for a dbt-style connection."""
    proto = struct.pack("!I", 0x00030000)
    body = proto
    for k, v in params.items():
        body += k.encode() + b"\x00" + v.encode() + b"\x00"
    body += b"\x00"
    length = struct.pack("!I", len(body) + 4)
    return length + body


class TestProtocolFraming:
    async def test_read_startup_message_roundtrip(self) -> None:
        params = {
            "user": f"run-{uuid.uuid4()}",
            "database": "my_connector",
            "application_name": "dbt",
        }
        raw = _make_startup_payload(params)
        reader = asyncio.StreamReader()
        reader.feed_data(raw)
        result = await read_startup_message(reader)
        assert result["user"] == params["user"]
        assert result["database"] == params["database"]

    def test_write_row_description_golden(self) -> None:
        cols = [("id", 23), ("name", 25)]
        msg = write_row_description(cols)
        assert msg[0:1] == b"T"
        length = struct.unpack("!I", msg[1:5])[0]
        assert length == len(msg) - 1
        # 2-byte column count
        n = struct.unpack("!H", msg[5:7])[0]
        assert n == 2

    def test_write_data_row_golden(self) -> None:
        row = ["42", "hello", None]
        msg = write_data_row(row)
        assert msg[0:1] == b"D"
        n = struct.unpack("!H", msg[5:7])[0]
        assert n == 3
        # Last value is NULL (length -1)
        # Skip first two values to find null indicator
        # value 0: len(4 bytes "0042") = 2, value 1: len(5 bytes "hello") = 5
        offset = 7
        v0_len = struct.unpack("!i", msg[offset:offset + 4])[0]
        assert v0_len == 2  # "42"
        offset += 4 + v0_len
        v1_len = struct.unpack("!i", msg[offset:offset + 4])[0]
        assert v1_len == 5  # "hello"
        offset += 4 + v1_len
        v2_len = struct.unpack("!i", msg[offset:offset + 4])[0]
        assert v2_len == -1  # NULL

    def test_write_error_response_includes_sqlstate(self) -> None:
        msg = write_error_response("test error", sqlstate="28P01")
        assert msg[0:1] == b"E"
        # Should contain 'C' field code followed by SQLSTATE
        payload = msg[5:]
        assert b"C28P01\x00" in payload
        assert b"Mtest error\x00" in payload

    def test_bind_value_int4_text_format(self) -> None:
        raw = b"42"
        val = parse_bind_value(raw, OID_INT4, 0)
        assert val == 42

    def test_bind_value_text_text_format(self) -> None:
        raw = "hello world".encode("utf-8")
        val = parse_bind_value(raw, OID_TEXT, 0)
        assert val == "hello world"

    def test_bind_value_bool_text_format(self) -> None:
        assert parse_bind_value(b"t", OID_BOOL, 0) is True
        assert parse_bind_value(b"false", OID_BOOL, 0) is False

    def test_bind_value_timestamptz_text_format(self) -> None:
        from datetime import datetime, timezone
        raw = b"2024-01-15 12:34:56+00"
        val = parse_bind_value(raw, OID_TIMESTAMPTZ, 0)
        assert isinstance(val, datetime)
        assert val.year == 2024

    def test_unsupported_oid_returns_sentinel(self) -> None:
        raw = b"\x00\x01"
        result = parse_bind_value(raw, oid=9999, format_code=1)
        assert isinstance(result, UnsupportedOID)
        assert result.oid == 9999
