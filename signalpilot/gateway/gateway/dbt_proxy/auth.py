"""Startup handshake handler for the dbt-proxy TCP listener.

Protocol (loopback, no TLS — R8 will add SCRAM/TLS):
  1. Read StartupMessage from client.
  2. Send AuthenticationCleartextPassword request.
  3. Read PasswordMessage (the cleartext run-token).
  4. Call token_store.verify(user, password) → RunTokenClaims.
  5. On success: send AuthenticationOk + ParameterStatus frames + ReadyForQuery.
  6. On failure: send ErrorResponse(SQLSTATE 28P01) and close the connection.

The cleartext password is the run-token (hex HMAC string). This is acceptable
because:
  - The listener binds to loopback / container-internal addresses only.
  - Tokens are short-lived (60–86400 s TTL).
  - HMAC provides integrity; the secret is never on the wire.

Security note: R8 will upgrade to SCRAM-SHA-256 + TLS.
"""

from __future__ import annotations

import logging
import uuid

from .errors import AuthFailed, RunTokenExpired
from .protocol import (
    read_password_message,
    read_startup_message,
    write_authentication_cleartext_password,
    write_authentication_ok,
    write_backend_key_data,
    write_error_response,
    write_parameter_status,
    write_ready_for_query,
)
from .tokens import RunTokenClaims, RunTokenStore

logger = logging.getLogger(__name__)

_PARAM_STATUS_FRAMES = [
    ("server_version", "14.0"),
    ("client_encoding", "UTF8"),
    ("DateStyle", "ISO, MDY"),
    ("integer_datetimes", "on"),
    ("standard_conforming_strings", "on"),
]


async def handle_startup(
    reader,
    writer,
    token_store: RunTokenStore,
) -> RunTokenClaims:
    """Perform the Postgres startup handshake and return verified claims.

    Sends ErrorResponse(28P01) and closes the writer on auth failure so the
    caller's session loop can exit cleanly.

    Raises AuthFailed or RunTokenExpired on failure (writer is already closed).
    """
    try:
        params = await read_startup_message(reader)
    except Exception as exc:
        err_id = uuid.uuid4().hex
        logger.warning("dbt_proxy startup_message error id=%s exc=%r", err_id, exc)
        writer.write(write_error_response("protocol error", sqlstate="08006"))
        await writer.drain()
        writer.close()
        raise AuthFailed(f"startup_message protocol error (ref={err_id})")

    user = params.get("user", "")
    _database = params.get("database", "")

    writer.write(write_authentication_cleartext_password())
    await writer.drain()

    try:
        password = await read_password_message(reader)
    except Exception as exc:
        err_id = uuid.uuid4().hex
        logger.warning("dbt_proxy password_message error id=%s exc=%r", err_id, exc)
        writer.write(write_error_response("protocol error", sqlstate="28P01"))
        await writer.drain()
        writer.close()
        raise AuthFailed(f"password_message protocol error (ref={err_id})")

    try:
        claims = await token_store.verify(user, password)
    except RunTokenExpired:
        # Safe message: "Token for run_id=... has expired" — no DSN content.
        writer.write(write_error_response("authentication failed: token expired", sqlstate="28P01"))
        await writer.drain()
        writer.close()
        raise
    except AuthFailed:
        # Safe message: "Token HMAC mismatch" / "Invalid user format" — no DSN content.
        writer.write(write_error_response("authentication failed", sqlstate="28P01"))
        await writer.drain()
        writer.close()
        raise

    # Auth OK — send startup response frames
    writer.write(write_authentication_ok())
    for name, value in _PARAM_STATUS_FRAMES:
        writer.write(write_parameter_status(name, value))
    writer.write(write_backend_key_data(pid=0, secret=0))
    writer.write(write_ready_for_query(b"I"))
    await writer.drain()

    # Log run_id only; org_id/connector_name are sensitive per RunTokenClaims.__repr__
    # but included here for operational visibility. Keep consistent with repr masking policy.
    logger.info("dbt_proxy auth_ok run_id=%s", claims.run_id)
    return claims


__all__ = ["handle_startup"]
