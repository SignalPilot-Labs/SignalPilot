"""Assert that importing signalpilot._server.start pops SP_SESSION_JWT from os.environ.

Uses subprocess isolation to avoid pytest's module-cache polluting the test.
Skipped if the full notebook-server venv is not available.
"""
from __future__ import annotations

import os
import subprocess
import sys


class TestServerStartPopsJwt:
    def test_import_start_pops_jwt(self):
        """After importing _server.start, SP_SESSION_JWT must not be in os.environ."""
        notebook_root = str(
            __import__("pathlib").Path(__file__).parent.parent
        )
        code = (
            "import os; "
            "os.environ['SP_SESSION_JWT'] = 'abc'; "
            "import signalpilot._server.start; "
            "assert 'SP_SESSION_JWT' not in os.environ, "
            "'SP_SESSION_JWT still in env after start import'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "SP_SESSION_JWT": "abc", "PYTHONPATH": notebook_root},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            import pytest
            pytest.skip(
                "Full notebook-server venv not available; skipping. "
                f"stderr: {result.stderr[:200]}"
            )
        assert result.returncode == 0, (
            f"Subprocess failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
