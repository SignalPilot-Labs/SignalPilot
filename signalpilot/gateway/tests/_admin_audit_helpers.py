"""Shared helpers for the admin audit-logging test modules (F-22).

Builds mock Requests and Stores so no live database is required, and asserts
that no credential material leaks into audit metadata.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock


def _make_request(
    client_host: str = "10.0.0.1",
    forwarded_for: str | None = None,
    user_agent: str = "test-agent/1.0",
) -> MagicMock:
    """Build a minimal mock Request matching FastAPI's interface."""
    request = MagicMock()
    headers: dict[str, str] = {"user-agent": user_agent}
    if forwarded_for:
        headers["x-forwarded-for"] = forwarded_for
    request.headers = headers
    request.client = MagicMock()
    request.client.host = client_host
    return request


def _make_store(org_id: str = "test-org", user_id: str = "test-user") -> AsyncMock:
    """Build a mock Store that captures append_audit calls."""
    store = AsyncMock()
    store.org_id = org_id
    store.user_id = user_id
    store.append_audit = AsyncMock()
    return store


def _assert_no_credential_material(metadata: dict[str, Any]) -> None:
    """Assert that no raw credential bytes or secrets appear in metadata."""
    forbidden_keys = {"connection_string", "password", "provider_config", "dek", "wrapped_dek", "raw_key"}
    for key in forbidden_keys:
        assert key not in metadata, f"Credential material '{key}' found in audit metadata"
    for value in metadata.values():
        if isinstance(value, str):
            # Crude check: real connection strings contain ://
            assert "://" not in value or value.startswith("byok"), (
                f"Possible connection string in audit metadata value: {value!r}"
            )
