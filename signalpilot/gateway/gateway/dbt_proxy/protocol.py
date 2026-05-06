"""PostgreSQL wire-protocol v3 framing for the dbt-proxy.

This module implements the minimal subset of the Postgres frontend/backend
protocol v3 required to speak to dbt-postgres (libpq client).

Supported backend message types (server → client):
  R  AuthenticationCleartextPassword (type code 0x03)
  R  AuthenticationOk (type code 0x00)
  E  ErrorResponse
  Z  ReadyForQuery
  T  RowDescription
  D  DataRow
  C  CommandComplete
  S  ParameterStatus
  K  BackendKeyData

Supported frontend message types (client → server):
  StartupMessage  (version 3.0, no type byte prefix)
  p  PasswordMessage
  Q  SimpleQuery
  P  Parse
  B  Bind
  D  Describe
  E  Execute
  S  Sync
  X  Terminate

Supported parameter type OIDs for Bind-value parsing (§A.1):
  23    int4
  20    int8
  25    text
  1043  varchar
  16    bool
  1184  timestamptz
  1700  numeric
  701   float8

Any other OID is returned as an UnsupportedOID sentinel so the caller
(session.py) can send an ErrorResponse without the protocol module raising.

R3 limits (documented here per spec):
  - No SSL/TLS (loopback only).
  - No COPY, LISTEN/NOTIFY, cursor protocol.
  - No statement-level prepared-statement caching beyond inline substitution.
  - Extended Query (Parse/Bind/Describe/Execute/Sync) is collapsed onto the
    simple-query path via client-side parameter substitution in session.py.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# ─── OID constants ────────────────────────────────────────────────────────────

OID_INT4 = 23
OID_INT8 = 20
OID_TEXT = 25
OID_VARCHAR = 1043
OID_BOOL = 16
OID_TIMESTAMPTZ = 1184
OID_NUMERIC = 1700
OID_FLOAT8 = 701

SUPPORTED_OIDS: frozenset[int] = frozenset({
    OID_INT4, OID_INT8, OID_TEXT, OID_VARCHAR,
    OID_BOOL, OID_TIMESTAMPTZ, OID_NUMERIC, OID_FLOAT8,
})

# Postgres epoch: 2000-01-01 00:00:00 UTC
_PG_EPOCH = datetime(2000, 1, 1, tzinfo=UTC).timestamp()
_USEC_PER_SEC = 1_000_000

# ─── Sentinel for unsupported OIDs ───────────────────────────────────────────


@dataclass
class UnsupportedOID:
    """Returned by parse_bind_value when a parameter OID is not in SUPPORTED_OIDS."""

    oid: int


# ─── Reading from asyncio StreamReader ───────────────────────────────────────


async def read_exact(reader, n: int) -> bytes:
    """Read exactly n bytes from the reader, raising EOFError on premature close."""
    return await reader.readexactly(n)


async def read_startup_message(reader) -> dict[str, str]:
    """Read a StartupMessage from the client.

    StartupMessage format (no type byte prefix):
      int32  total_length (including the length field itself)
      int32  protocol_version  (0x00030000 for 3.0)
      bytes  NUL-terminated key=value pairs, terminated by a NUL byte.

    Returns a dict of parameters (user, database, application_name, etc.).
    Raises ValueError if the protocol version is not 3.0.
    """
    length_bytes = await read_exact(reader, 4)
    total_length = struct.unpack("!I", length_bytes)[0]
    if total_length < 8:
        raise ValueError(f"StartupMessage too short: {total_length}")
    body = await read_exact(reader, total_length - 4)
    proto_version = struct.unpack("!I", body[:4])[0]
    if proto_version != 0x00030000:
        raise ValueError(f"Unsupported protocol version: {proto_version:#010x}")
    params: dict[str, str] = {}
    payload = body[4:]
    while payload:
        nul = payload.find(b"\x00")
        if nul == -1 or nul == 0:
            break
        key = payload[:nul].decode("utf-8", errors="replace")
        payload = payload[nul + 1:]
        nul2 = payload.find(b"\x00")
        if nul2 == -1:
            break
        value = payload[:nul2].decode("utf-8", errors="replace")
        payload = payload[nul2 + 1:]
        params[key] = value
    return params


async def read_frontend_message(reader) -> tuple[str, bytes]:
    """Read a typed frontend message (post-startup).

    Format:
      char   type byte
      int32  length (includes the 4-byte length field itself)
      bytes  payload (length - 4 bytes)

    Returns (type_char, payload_bytes).
    """
    type_byte = await read_exact(reader, 1)
    msg_type = type_byte.decode("latin-1")
    length_bytes = await read_exact(reader, 4)
    length = struct.unpack("!I", length_bytes)[0]
    if length < 4:
        raise ValueError(f"Invalid message length: {length}")
    payload = await read_exact(reader, length - 4)
    return msg_type, payload


# ─── Writing backend messages ─────────────────────────────────────────────────


def _framed(type_byte: bytes, payload: bytes) -> bytes:
    """Wrap payload in a backend message frame."""
    length = len(payload) + 4
    return type_byte + struct.pack("!I", length) + payload


def write_authentication_cleartext_password() -> bytes:
    """AuthenticationCleartextPassword — request cleartext password from client."""
    # R message with int32 code 3
    payload = struct.pack("!I", 3)
    return _framed(b"R", payload)


def write_authentication_ok() -> bytes:
    """AuthenticationOk — authentication successful."""
    payload = struct.pack("!I", 0)
    return _framed(b"R", payload)


def write_error_response(message: str, severity: str = "ERROR", sqlstate: str = "08000") -> bytes:
    """ErrorResponse with the required fields: Severity, Code, Message.

    Field format: single byte field code, NUL-terminated string, final NUL.
    """
    fields = (
        b"S" + severity.encode() + b"\x00"
        + b"C" + sqlstate.encode() + b"\x00"
        + b"M" + message.encode("utf-8", errors="replace") + b"\x00"
        + b"\x00"
    )
    return _framed(b"E", fields)


def write_ready_for_query(status: bytes = b"I") -> bytes:
    """ReadyForQuery — signals client that backend is ready for a new query.

    status: b'I' (idle), b'T' (in transaction), b'E' (failed transaction).
    """
    return _framed(b"Z", status)


def write_parameter_status(name: str, value: str) -> bytes:
    """ParameterStatus — send a server parameter to the client."""
    payload = name.encode() + b"\x00" + value.encode() + b"\x00"
    return _framed(b"S", payload)


def write_backend_key_data(pid: int, secret: int) -> bytes:
    """BackendKeyData — fake PID and cancel key (not used in proxy)."""
    payload = struct.pack("!II", pid, secret)
    return _framed(b"K", payload)


def write_row_description(columns: list[tuple[str, int]]) -> bytes:
    """RowDescription — describe result columns.

    columns: list of (name, type_oid). Format_code 0 (text) for all.
    """
    n = len(columns)
    payload = struct.pack("!H", n)
    for name, type_oid in columns:
        # RowDescription field: table_oid(I) + attr_num(h) + type_oid(I) + type_size(h) + type_mod(i) + format(h)
        payload += (
            name.encode("utf-8") + b"\x00"
            + struct.pack("!IhIhih", 0, 0, type_oid, -1, -1, 0)
        )
    return _framed(b"T", payload)


def write_data_row(values: list[str | None]) -> bytes:
    """DataRow — one row of result data, all values as text (format 0)."""
    n = len(values)
    payload = struct.pack("!H", n)
    for v in values:
        if v is None:
            payload += struct.pack("!i", -1)
        else:
            encoded = v.encode("utf-8")
            payload += struct.pack("!I", len(encoded)) + encoded
    return _framed(b"D", payload)


def write_command_complete(tag: str) -> bytes:
    """CommandComplete — e.g. 'SELECT 5', 'INSERT 0 1'."""
    payload = tag.encode() + b"\x00"
    return _framed(b"C", payload)


# ─── Startup auth helpers ─────────────────────────────────────────────────────


async def read_password_message(reader) -> str:
    """Read a PasswordMessage (type 'p') from the client."""
    msg_type, payload = await read_frontend_message(reader)
    if msg_type != "p":
        raise ValueError(f"Expected PasswordMessage ('p'), got {msg_type!r}")
    return payload.rstrip(b"\x00").decode("utf-8")


# ─── Bind-value parser ────────────────────────────────────────────────────────


def parse_bind_value(raw: bytes, oid: int, format_code: int) -> Any | UnsupportedOID:
    """Parse a single Bind parameter value into a Python value.

    format_code 0 = text, 1 = binary.
    Returns UnsupportedOID(oid) when the OID is not in SUPPORTED_OIDS.
    Binary format values are decoded for the supported OIDs.
    Text format values are parsed from their string representation.
    """
    if oid not in SUPPORTED_OIDS:
        return UnsupportedOID(oid)

    if format_code == 0:
        # Text format
        text = raw.decode("utf-8")
        if oid == OID_BOOL:
            return text.lower() in ("t", "true", "1", "yes", "on")
        if oid in (OID_INT4, OID_INT8):
            return int(text)
        if oid in (OID_TEXT, OID_VARCHAR):
            return text
        if oid == OID_NUMERIC:
            return Decimal(text)
        if oid == OID_FLOAT8:
            return float(text)
        if oid == OID_TIMESTAMPTZ:
            return _parse_timestamptz_text(text)
        return text
    # Binary format
    if oid == OID_BOOL:
        return raw[0] != 0
    if oid == OID_INT4:
        return struct.unpack("!i", raw)[0]
    if oid == OID_INT8:
        return struct.unpack("!q", raw)[0]
    if oid in (OID_TEXT, OID_VARCHAR):
        return raw.decode("utf-8")
    if oid == OID_NUMERIC:
        return _parse_numeric_binary(raw)
    if oid == OID_FLOAT8:
        return struct.unpack("!d", raw)[0]
    if oid == OID_TIMESTAMPTZ:
        usec = struct.unpack("!q", raw)[0]
        return datetime.fromtimestamp(_PG_EPOCH + usec / _USEC_PER_SEC, tz=UTC)
    return UnsupportedOID(oid)


def _parse_timestamptz_text(text: str) -> datetime:
    """Parse a Postgres timestamptz text value to a datetime."""
    text = text.strip()
    # Common formats from libpq: "2024-01-15 12:34:56+00" or ISO with T
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S.%f%z"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    # Fallback to fromisoformat
    return datetime.fromisoformat(text)


def _parse_numeric_binary(raw: bytes) -> Decimal:
    """Parse Postgres binary NUMERIC into a Python Decimal.

    Binary format: ndigits(2), weight(2), sign(2), dscale(2), digits(2*ndigits).
    Each digit is base-10000.
    """
    if len(raw) < 8:
        return Decimal(0)
    ndigits, weight, sign, dscale = struct.unpack("!HhHH", raw[:8])
    digits = struct.unpack(f"!{ndigits}H", raw[8:8 + 2 * ndigits])
    # Reconstruct the decimal
    value = Decimal(0)
    for i, digit in enumerate(digits):
        value += Decimal(digit) * Decimal(10000) ** (weight - i)
    if sign == 0x4000:
        value = -value
    return value.quantize(Decimal(10) ** -dscale) if dscale > 0 else value


def parse_simple_query_payload(payload: bytes) -> str:
    """Extract the SQL string from a SimpleQuery payload."""
    return payload.rstrip(b"\x00").decode("utf-8")


def parse_parse_message(payload: bytes) -> tuple[str, str, list[int]]:
    """Parse a Parse message payload.

    Returns (statement_name, query, param_type_oids).
    """
    nul1 = payload.find(b"\x00")
    stmt_name = payload[:nul1].decode("utf-8")
    rest = payload[nul1 + 1:]
    nul2 = rest.find(b"\x00")
    query = rest[:nul2].decode("utf-8")
    rest = rest[nul2 + 1:]
    n_params = struct.unpack("!H", rest[:2])[0]
    oids = list(struct.unpack(f"!{n_params}I", rest[2:2 + 4 * n_params]))
    return stmt_name, query, oids


def parse_bind_message(payload: bytes) -> tuple[str, str, list[int], list[bytes | None]]:
    """Parse a Bind message payload.

    Returns (portal_name, stmt_name, format_codes, param_values).
    format_codes: per-param format codes (0=text, 1=binary). If length=1, applies to all.
    param_values: list of raw bytes per param (None if NULL).
    """
    nul1 = payload.find(b"\x00")
    portal = payload[:nul1].decode("utf-8")
    rest = payload[nul1 + 1:]
    nul2 = rest.find(b"\x00")
    stmt = rest[:nul2].decode("utf-8")
    rest = rest[nul2 + 1:]
    n_formats = struct.unpack("!H", rest[:2])[0]
    formats = list(struct.unpack(f"!{n_formats}H", rest[2:2 + 2 * n_formats]))
    rest = rest[2 + 2 * n_formats:]
    n_params = struct.unpack("!H", rest[:2])[0]
    rest = rest[2:]
    values: list[bytes | None] = []
    for _ in range(n_params):
        length = struct.unpack("!i", rest[:4])[0]
        rest = rest[4:]
        if length == -1:
            values.append(None)
        else:
            values.append(rest[:length])
            rest = rest[length:]
    return portal, stmt, formats, values


__all__ = [
    "UnsupportedOID",
    "SUPPORTED_OIDS",
    "OID_INT4", "OID_INT8", "OID_TEXT", "OID_VARCHAR",
    "OID_BOOL", "OID_TIMESTAMPTZ", "OID_NUMERIC", "OID_FLOAT8",
    "read_exact",
    "read_startup_message",
    "read_frontend_message",
    "read_password_message",
    "write_authentication_cleartext_password",
    "write_authentication_ok",
    "write_error_response",
    "write_ready_for_query",
    "write_parameter_status",
    "write_backend_key_data",
    "write_row_description",
    "write_data_row",
    "write_command_complete",
    "parse_bind_value",
    "parse_simple_query_payload",
    "parse_parse_message",
    "parse_bind_message",
]
