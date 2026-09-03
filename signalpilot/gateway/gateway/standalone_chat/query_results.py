"""Row loader for stored structured query results.

Small results keep their rows inline in ``rows_json``. Larger ones spill to
object storage and keep only a preview inline; the full rows live under
``object_key`` with a sha256 recorded in ``content_hash``. Both the SDK route
(``GET /api/query/results/{id}``) and the chat-scoped route
(``GET /api/chat/conversations/{id}/results/{id}``) load rows through here so
the integrity check is enforced in exactly one place.
"""

from __future__ import annotations

import hashlib
import json

from gateway.db.models import GatewayStructuredQueryResult

from .object_storage import chat_object_storage

_MAX_RESULT_BYTES = 10 * 1024 * 1024


class QueryResultUnavailable(RuntimeError):
    """The stored rows cannot be served. Routes map this to HTTP 500."""


async def load_result_rows(stored: GatewayStructuredQueryResult) -> list:
    """Return every saved row for ``stored``, verifying the hash for object-backed results."""
    if stored.storage_kind != "object":
        return list(stored.rows_json or [])
    if not stored.object_key:
        raise QueryResultUnavailable("Stored query result is unavailable")
    data = await chat_object_storage().get_bytes(stored.object_key, max_bytes=_MAX_RESULT_BYTES)
    if stored.content_hash and hashlib.sha256(data).hexdigest() != stored.content_hash:
        raise QueryResultUnavailable("Stored query result failed integrity validation")
    loaded = json.loads(data)
    if not isinstance(loaded, list):
        raise QueryResultUnavailable("Stored query result is invalid")
    return loaded
