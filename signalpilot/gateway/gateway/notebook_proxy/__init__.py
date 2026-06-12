"""Notebook proxy package — gateway reverse proxy for notebook pods.

Exports the FastAPI router registered in api/__init__.py.
"""

from __future__ import annotations

from .routes import router

__all__ = ["router"]
