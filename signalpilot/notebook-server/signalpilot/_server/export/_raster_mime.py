from __future__ import annotations

from typing import Final

from signalpilot._messaging.mimetypes import KnownMimeType

TEXT_HTML: Final[KnownMimeType] = "text/html"
TEXT_PLAIN: Final[KnownMimeType] = "text/plain"
TEXT_MARKDOWN: Final[KnownMimeType] = "text/markdown"

VEGA_MIME_TYPES: Final[set[KnownMimeType]] = {
    "application/vnd.vegalite.v5+json",
    "application/vnd.vega.v5+json",
    "application/vnd.vegalite.v6+json",
    "application/vnd.vega.v6+json",
}

MIME_TYPES_REPLACED_BY_PNG: Final[set[KnownMimeType]] = {
    TEXT_HTML,
    TEXT_PLAIN,
    TEXT_MARKDOWN,
    *VEGA_MIME_TYPES,
}
