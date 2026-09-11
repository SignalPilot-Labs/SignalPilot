"""Shared safe diagnostics for MCP chat reads."""

import logging
import os
import re
import uuid

from mcp.types import CallToolResult, TextContent

from gateway.standalone_chat.worker_errors import public_raw_error_fields

logger = logging.getLogger(__name__)


def chat_failure(exc, operation):
    message = str(exc)
    for name in ("SP_CHAT_OBJECTS_S3_ACCESS_KEY", "SP_CHAT_OBJECTS_S3_SECRET_KEY", "SP_CHAT_OBJECTS_BUCKET",
                 "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        value = os.environ.get(name)
        if value:
            message = message.replace(value, "[REDACTED]")
    message = re.sub(r"organizations/[^\s\"']+", "[STORAGE KEY REDACTED]", message)
    fields = public_raw_error_fields(RuntimeError(message))
    correlation_id = uuid.uuid4().hex
    safe_message = fields["raw_error"][:2000]
    logger.warning("Chat request failure id=%s operation=%s type=%s detail=%s",
                   correlation_id, operation.__name__, type(exc).__name__, safe_message[:500])
    return CallToolResult(isError=True,
        content=[TextContent(type="text", text=f"Chat request failed. Reference: {correlation_id}")],
        structuredContent={"error": safe_message, "error_type": type(exc).__name__,
                           "correlation_id": correlation_id, **fields})
