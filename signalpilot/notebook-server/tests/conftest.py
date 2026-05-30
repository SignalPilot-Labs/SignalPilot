"""Test configuration for notebook-server tests.

Inserts a lightweight signalpilot package shim into sys.modules so that
importing signalpilot._server.auth.session_token and related modules does not
trigger the heavy signalpilot.__init__ import chain (which requires narwhals,
markdown, msgspec, etc. to be installed in the test environment).

The shim only patches the top-level 'signalpilot' module object so that
submodule imports (signalpilot._server.*, signalpilot._session.*, etc.) work
correctly via the file system.
"""
from __future__ import annotations

import os
import sys
import types

# Ensure the notebook-server source is on PYTHONPATH.
_NOTEBOOK_SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _NOTEBOOK_SERVER_ROOT not in sys.path:
    sys.path.insert(0, _NOTEBOOK_SERVER_ROOT)

# Create a lightweight stub for the 'signalpilot' package so that the heavy
# signalpilot/__init__.py is not executed during test collection.
# Submodule imports work because we set __path__ to the real package directory.
if "signalpilot" not in sys.modules:
    _pkg = types.ModuleType("signalpilot")
    _pkg.__path__ = [os.path.join(_NOTEBOOK_SERVER_ROOT, "signalpilot")]
    _pkg.__package__ = "signalpilot"
    _pkg.__spec__ = None  # type: ignore[assignment]
    sys.modules["signalpilot"] = _pkg
