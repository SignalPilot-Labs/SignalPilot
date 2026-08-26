"""Redact secret-bearing URL segments before they reach application logs."""

from __future__ import annotations

import logging
import re

_SHARE_TOKEN_PATH = re.compile(r"(/api/chat/(?:shared-reports|shared)/)[^/?\s]+")
_LIBRARY_QUERY = re.compile(r"(/api/chat/library)\?[^\s]+")


def redact_secret_path(value: str) -> str:
    """Keep the route shape useful while removing fixed-link bearer tokens."""
    value = _SHARE_TOKEN_PATH.sub(r"\1[redacted]", value)
    return _LIBRARY_QUERY.sub(r"\1?[redacted]", value)


class SecretPathLogFilter(logging.Filter):
    """Redact paths embedded in uvicorn's positional access-log arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secret_path(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_secret_path(value) if isinstance(value, str) else value for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_secret_path(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def install_uvicorn_secret_path_filter() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, SecretPathLogFilter) for item in access_logger.filters):
        access_logger.addFilter(SecretPathLogFilter())
