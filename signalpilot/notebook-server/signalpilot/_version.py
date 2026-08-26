from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sp-notebook")
except PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"
