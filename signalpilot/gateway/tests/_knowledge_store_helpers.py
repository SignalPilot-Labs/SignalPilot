"""Shared mock builders for the Knowledge Base store tests.

All helpers build mocked SQLAlchemy rows / sessions; no live DB required.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock


def _make_doc_row(
    *,
    doc_id: str | None = None,
    org_id: str = "test-org",
    scope: str = "org",
    scope_ref: str | None = None,
    category: str = "rules",
    title: str = "test-doc",
    body: str = "hello world",
    status: str = "active",
    bytes_val: int | None = None,
    view_count: int = 0,
) -> MagicMock:
    row = MagicMock()
    row.id = doc_id or str(uuid.uuid4())
    row.org_id = org_id
    row.scope = scope
    row.scope_ref = scope_ref
    row.category = category
    row.title = title
    row.body = body
    row.status = status
    row.bytes = bytes_val if bytes_val is not None else len(body.encode("utf-8"))
    row.view_count = view_count
    row.created_at = time.time()
    row.updated_at = time.time()
    row.created_by = None
    row.updated_by = None
    row.proposed_by_agent = None
    return row


def _make_limits(storage_mb: int = 0, history_versions: int = 5):
    limits = MagicMock()
    limits.knowledge_storage_mb = storage_mb
    limits.knowledge_history_versions = history_versions
    return limits


def _make_settings(override: int | None = None):
    settings = MagicMock()
    settings.knowledge_history_versions_override = override
    return settings


def _make_insert_session(existing_bytes: int = 0) -> AsyncMock:
    """Build a session mock suitable for insert_knowledge_doc."""
    session = AsyncMock()
    row = MagicMock()
    row.id = str(uuid.uuid4())
    row.org_id = "test-org"
    row.scope = "org"
    row.scope_ref = None
    row.category = "rules"
    row.title = "test-doc"
    row.body = "content"
    row.status = "active"
    row.bytes = len(b"content")
    row.view_count = 0
    row.created_at = time.time()
    row.updated_at = time.time()
    row.created_by = None
    row.updated_by = None
    row.proposed_by_agent = None

    scalar_result = MagicMock()
    scalar_result.scalar.return_value = existing_bytes
    session.execute = AsyncMock(return_value=scalar_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda r: None)

    return session, row
