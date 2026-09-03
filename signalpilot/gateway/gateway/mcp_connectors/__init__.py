"""Connectors domain: SSRF guard, probe, upstream client pool, OAuth, policy, proxy."""

from __future__ import annotations

from gateway.mcp_connectors.slugs import SlugCollisionError, allocate_slug, slugify
from gateway.mcp_connectors.ssrf import UnsafeUrlError, validate_remote_url, validate_url_syntax

__all__ = [
    "SlugCollisionError",
    "UnsafeUrlError",
    "allocate_slug",
    "slugify",
    "validate_remote_url",
    "validate_url_syntax",
]
