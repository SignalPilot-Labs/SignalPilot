"""Per-connection session loop for the dbt-proxy.

Extended Query handling (R3 design decision):
  Parse/Bind/Describe/Execute/Sync messages are collapsed onto the simple-query
  path via client-side parameter substitution. This avoids server-side prepared
  statement state and keeps the proxy stateless per-message.

  Substitution: each $N placeholder in the Parse query string is replaced with
  the corresponding Bind value, formatted as a SQL literal. Supported OIDs are
  listed in protocol.py. Unsupported OIDs produce an ErrorResponse with
  SQLSTATE 0A000 and the connection is NOT closed (the client can retry with
  different params or disconnect).

Session lifecycle:
  1. handle_startup() completes and returns RunTokenClaims.
  2. Loop reads typed frontend messages.
  3. SimpleQuery ('Q') → execute → send RowDescription/DataRow/CommandComplete/Z.
  4. Parse ('P') → store statement name + query + param OIDs.
  5. Bind ('B') → resolve params → substitute → store portal SQL.
  6. Describe ('D') → send RowDescription for portal (no-op T message).
  7. Execute ('E') → execute portal SQL → send rows + CommandComplete.
  8. Sync ('S') → send ReadyForQuery.
  9. Terminate ('X') → close connection.
  10. Unknown → ErrorResponse; do NOT close (libpq may retry).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from ..store import Store
from .errors import NonPostgresConnector
from .forwarder import execute_query
from .protocol import (
    UnsupportedOID,
    parse_bind_message,
    parse_bind_value,
    parse_parse_message,
    parse_simple_query_payload,
    read_frontend_message,
    write_command_complete,
    write_data_row,
    write_error_response,
    write_ready_for_query,
    write_row_description,
)
from .tokens import RunTokenClaims

logger = logging.getLogger(__name__)

# Sent at the start of each extended query cycle
_PARSE_COMPLETE = b"1" + b"\x00\x00\x00\x04"
_BIND_COMPLETE = b"2" + b"\x00\x00\x00\x04"
_NO_DATA = b"n" + b"\x00\x00\x00\x04"


_INVALID_FLOAT_VALUES: frozenset[str] = frozenset({"inf", "-inf", "nan"})


def _format_param(value: object) -> str:
    """Format a Python value as a SQL literal for inline substitution.

    Raises ValueError for values that cannot be safely represented as SQL
    literals (NaN/Inf floats, NUL bytes in text). Fail closed rather than
    producing invalid or injection-prone SQL.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # NaN and Inf are not valid SQL literals — reject rather than forward
        if str(value).lower() in _INVALID_FLOAT_VALUES:
            raise ValueError(f"float parameter value {value!r} is not a valid SQL literal (NaN/Inf)")
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"
    # Text / varchar — reject NUL bytes; escape single quotes only
    text = str(value)
    if "\x00" in text:
        raise ValueError("text parameter contains NUL byte (\\x00), which is not allowed in Postgres text input")
    escaped = text.replace("'", "''")
    return f"'{escaped}'"


def _substitute_params(query: str, params: list[object]) -> str:
    """Replace $1 .. $N placeholders with formatted literals.

    SECURITY NOTE: str.replace substitutes ALL occurrences of $N, including
    those inside string literals or comments. This is a known limitation of
    the inline-substitution approach. dbt-postgres never puts $N placeholders
    inside literals in its compiled output, so this is acceptable for R3.
    TODO(R4): pass params to connector.execute() instead of substituting.
    # SECURITY: DO NOT REMOVE the SECURITY NOTE above without implementing R4.
    """
    result = query
    # Reverse order so $10 doesn't get partially replaced by $1
    for i in range(len(params), 0, -1):
        result = result.replace(f"${i}", _format_param(params[i - 1]))
    return result


class DbtProxySession:
    """Manages one client connection's message loop."""

    def __init__(
        self,
        reader,
        writer,
        claims: RunTokenClaims,
        store: Store,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._claims = claims
        self._store = store
        # Extended query state
        self._named_stmts: dict[str, tuple[str, list[int]]] = {}  # name -> (query, oids)
        self._named_portals: dict[str, str] = {}  # name -> resolved SQL

    async def run(self) -> None:
        """Main message loop — runs until Terminate or connection error."""
        while True:
            try:
                msg_type, payload = await read_frontend_message(self._reader)
            except Exception as exc:
                logger.info("dbt_proxy connection closed run_id=%s: %s", self._claims.run_id, exc)
                break

            if msg_type == "Q":
                await self._handle_simple_query(payload)
            elif msg_type == "P":
                await self._handle_parse(payload)
            elif msg_type == "B":
                await self._handle_bind(payload)
            elif msg_type == "D":
                await self._handle_describe(payload)
            elif msg_type == "E":
                await self._handle_execute(payload)
            elif msg_type == "S":
                await self._handle_sync()
            elif msg_type == "X":
                break
            else:
                self._writer.write(
                    write_error_response(
                        f"Unsupported message type: {msg_type!r}",
                        sqlstate="0A000",
                    )
                )
                await self._writer.drain()

        self._writer.close()

    async def _handle_simple_query(self, payload: bytes) -> None:
        sql = parse_simple_query_payload(payload)
        await self._execute_and_respond(sql)
        self._writer.write(write_ready_for_query(b"I"))
        await self._writer.drain()

    async def _handle_parse(self, payload: bytes) -> None:
        stmt_name, query, oids = parse_parse_message(payload)
        self._named_stmts[stmt_name] = (query, oids)
        self._writer.write(_PARSE_COMPLETE)
        await self._writer.drain()

    async def _handle_bind(self, payload: bytes) -> None:
        portal, stmt_name, formats, raw_values = parse_bind_message(payload)

        if stmt_name not in self._named_stmts:
            self._writer.write(
                write_error_response(f"Unknown statement: {stmt_name!r}", sqlstate="26000")
            )
            await self._writer.drain()
            return

        query, oids = self._named_stmts[stmt_name]

        # Resolve format codes — if 1 code, apply to all; else index-matched
        def _fmt(i: int) -> int:
            if not formats:
                return 0
            return formats[0] if len(formats) == 1 else (formats[i] if i < len(formats) else 0)

        params: list[object] = []
        for i, raw in enumerate(raw_values):
            oid = oids[i] if i < len(oids) else 0
            if raw is None:
                params.append(None)
                continue
            parsed = parse_bind_value(raw, oid, _fmt(i))
            if isinstance(parsed, UnsupportedOID):
                self._writer.write(
                    write_error_response(
                        f"unsupported_parameter_oid: {parsed.oid}",
                        sqlstate="0A000",
                    )
                )
                await self._writer.drain()
                return
            params.append(parsed)

        resolved_sql = _substitute_params(query, params)
        self._named_portals[portal] = resolved_sql
        self._writer.write(_BIND_COMPLETE)
        await self._writer.drain()

    async def _handle_describe(self, payload: bytes) -> None:
        # Describe: 'S' (statement) or 'P' (portal) + name
        # We send NoData for simplicity — RowDescription follows Execute
        self._writer.write(_NO_DATA)
        await self._writer.drain()

    async def _handle_execute(self, payload: bytes) -> None:
        # Execute: portal name (NUL-terminated) + max rows (int32, ignored)
        nul = payload.find(b"\x00")
        portal_name = payload[:nul].decode("utf-8") if nul >= 0 else ""
        sql = self._named_portals.get(portal_name)
        if sql is None:
            self._writer.write(
                write_error_response(f"Unknown portal: {portal_name!r}", sqlstate="34000")
            )
            await self._writer.drain()
            return
        await self._execute_and_respond(sql, from_extended=True)

    async def _handle_sync(self) -> None:
        self._writer.write(write_ready_for_query(b"I"))
        await self._writer.drain()

    async def _execute_and_respond(self, sql: str, from_extended: bool = False) -> None:
        """Execute sql via forwarder and write result frames to the client.

        Error sanitization: exception text from the upstream connector layer may
        contain the warehouse DSN (host, port, credentials). Only governance-level
        ValueError messages (block_reason) and NonPostgresConnector messages (safe,
        never contain DSN) are forwarded to the client. All other exceptions are
        replaced with a sanitized message keyed by a correlation ID that appears in
        the server log only.
        """
        try:
            result = await execute_query(self._claims, sql, store=self._store)
        except NonPostgresConnector as exc:
            # Safe to forward: message is "Connector '...' is type '...'" — no DSN.
            self._writer.write(write_error_response(str(exc), sqlstate="0A000"))
            await self._writer.drain()
            return
        except ValueError as exc:
            # Safe to forward: governance block_reason — no DSN content.
            self._writer.write(write_error_response(str(exc), sqlstate="42501"))
            await self._writer.drain()
            return
        except Exception as exc:
            # SECURITY: do NOT forward str(exc) — it may contain the warehouse DSN.
            err_id = uuid.uuid4().hex
            logger.error(
                "dbt_proxy upstream error id=%s run_id=%s exc=%r",
                err_id,
                self._claims.run_id,
                exc,
            )
            self._writer.write(
                write_error_response(
                    f"upstream connection failed (ref={err_id})",
                    sqlstate="58000",
                )
            )
            await self._writer.drain()
            return

        if result.columns:
            self._writer.write(write_row_description(result.columns))
            for row in result.rows:
                self._writer.write(write_data_row(row))
        self._writer.write(write_command_complete(result.command_tag))
        await self._writer.drain()


__all__ = ["DbtProxySession"]
