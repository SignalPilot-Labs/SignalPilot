"""Shared error types for kernel management."""

from __future__ import annotations


class KernelStartupError(Exception):
    """Raised when a kernel subprocess fails to start or connect.

    Caught by the WebSocket handler to send a clean close frame
    with the error details instead of crashing.
    """
