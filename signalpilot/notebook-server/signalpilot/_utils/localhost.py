"""Normalize localhost URLs to 127.0.0.1 on Windows.

Windows resolves 'localhost' to ::1 (IPv6) first, and the 2-second TCP
connect timeout before falling back to 127.0.0.1 adds a catastrophic
delay to every new HTTP connection.
"""
from __future__ import annotations

import sys


def fix_localhost_url(url: str) -> str:
    if sys.platform == "win32" and "://localhost" in url:
        return url.replace("://localhost", "://127.0.0.1", 1)
    return url
