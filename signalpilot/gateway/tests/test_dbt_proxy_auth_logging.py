"""Tests that dbt_proxy auth handshake logs do not leak sensitive token material.

Verifies APP-L-2: on startup_message and password_message failures the logger
emits only the exception type name, never repr(exc) / str(exc) which could
embed raw token bytes or key material from caller-controlled input.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.dbt_proxy.errors import AuthFailed

SENTINEL = "SENSITIVE-TOKEN-ABC"


class _SentinelError(RuntimeError):
    """Exception whose repr and args contain the sentinel string."""

    def __repr__(self) -> str:
        return f"_SentinelError({SENTINEL!r})"


def _make_mock_writer() -> MagicMock:
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.is_closing = MagicMock(return_value=False)
    return writer


def _make_mock_token_store() -> MagicMock:
    store = MagicMock()
    store.verify = AsyncMock(side_effect=AuthFailed("bad token"))
    return store


class TestAuthLoggingDoesNotLeakSensitiveData:
    @pytest.mark.asyncio
    async def test_startup_message_error_omits_sensitive_repr(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """startup_message failure must log exc_type only, not repr(exc)."""
        exc = _SentinelError(SENTINEL)

        reader = asyncio.StreamReader()
        writer = _make_mock_writer()

        with patch(
            "gateway.dbt_proxy.auth.read_startup_message",
            new=AsyncMock(side_effect=exc),
        ):
            with caplog.at_level(logging.WARNING, logger="gateway.dbt_proxy.auth"):
                with pytest.raises(AuthFailed) as exc_info:
                    from gateway.dbt_proxy.auth import handle_startup
                    await handle_startup(reader, writer, _make_mock_token_store())

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, "expected at least one WARNING record"

        for record in warning_records:
            rendered = record.getMessage()
            assert SENTINEL not in rendered, (
                f"sentinel found in log message: {rendered!r}"
            )

        combined = " ".join(r.getMessage() for r in warning_records)
        assert "_SentinelError" in combined, (
            f"exc_type name not found in log messages: {combined!r}"
        )
        assert "id=" in combined, "err_id not found in log messages"

        # Verify err_id in log matches the ref in AuthFailed message
        auth_failed_msg = str(exc_info.value)
        ref_parts = auth_failed_msg.split("ref=")
        assert len(ref_parts) == 2, f"expected ref= in AuthFailed message: {auth_failed_msg!r}"
        err_id = ref_parts[1].rstrip(")")
        assert err_id in combined, (
            f"AuthFailed ref={err_id!r} not found in log: {combined!r}"
        )

    @pytest.mark.asyncio
    async def test_password_message_error_omits_sensitive_repr(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """password_message failure must log exc_type only, not repr(exc)."""
        import struct

        exc = _SentinelError(SENTINEL)

        # Build a valid StartupMessage so the first read succeeds
        params = {"user": "run-test-user", "database": "mydb"}
        proto_bytes = struct.pack("!I", 0x00030000)
        body = proto_bytes
        for k, v in params.items():
            body += k.encode() + b"\x00" + v.encode() + b"\x00"
        body += b"\x00"
        length = struct.pack("!I", len(body) + 4)
        startup_bytes = length + body

        reader = asyncio.StreamReader()
        reader.feed_data(startup_bytes)
        writer = _make_mock_writer()

        with patch(
            "gateway.dbt_proxy.auth.read_password_message",
            new=AsyncMock(side_effect=exc),
        ):
            with caplog.at_level(logging.WARNING, logger="gateway.dbt_proxy.auth"):
                with pytest.raises(AuthFailed) as exc_info:
                    from gateway.dbt_proxy.auth import handle_startup
                    await handle_startup(reader, writer, _make_mock_token_store())

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, "expected at least one WARNING record"

        for record in warning_records:
            rendered = record.getMessage()
            assert SENTINEL not in rendered, (
                f"sentinel found in log message: {rendered!r}"
            )

        combined = " ".join(r.getMessage() for r in warning_records)
        assert "_SentinelError" in combined, (
            f"exc_type name not found in log messages: {combined!r}"
        )
        assert "id=" in combined, "err_id not found in log messages"

        # Verify err_id in log matches the ref in AuthFailed message
        auth_failed_msg = str(exc_info.value)
        ref_parts = auth_failed_msg.split("ref=")
        assert len(ref_parts) == 2, f"expected ref= in AuthFailed message: {auth_failed_msg!r}"
        err_id = ref_parts[1].rstrip(")")
        assert err_id in combined, (
            f"AuthFailed ref={err_id!r} not found in log: {combined!r}"
        )
