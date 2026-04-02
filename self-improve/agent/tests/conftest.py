"""Shared test configuration — runs before any test module is collected.

Stubs external dependencies (claude_agent_sdk) that aren't installed in
the test environment. Uses setdefault so the real module is preferred if
it happens to be available.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Make agent package importable from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub the Claude Agent SDK — it's not installed in the test environment.
# The @tool decorator in session_gate.py must be a passthrough.
_sdk_mock = MagicMock()
_sdk_mock.tool = lambda *args, **kwargs: (lambda f: f)
_sdk_mock.create_sdk_mcp_server = MagicMock()
sys.modules.setdefault("claude_agent_sdk", _sdk_mock)
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())
