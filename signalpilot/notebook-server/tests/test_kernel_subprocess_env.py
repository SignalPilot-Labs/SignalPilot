"""Regression test: kernel subprocess env must not contain SP_SESSION_JWT.

All tests that require the full notebook-server venv (markdown, narwhals, etc.)
run as subprocesses and skip gracefully when the venv is incomplete.
The load_session_jwt tests run directly using the conftest's lightweight stub.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from signalpilot._server.auth.session_token import _reset_for_test, load_session_jwt


_NOTEBOOK_ROOT = str(__import__("pathlib").Path(__file__).parent.parent)


def _run_isolated(code: str) -> subprocess.CompletedProcess:
    """Run code in a subprocess with PYTHONPATH pointing at notebook-server root."""
    return subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": _NOTEBOOK_ROOT},
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture(autouse=True)
def _clean_env_and_cache():
    """Ensure clean state before and after each test."""
    _reset_for_test()
    saved = os.environ.pop("SP_SESSION_JWT", None)
    yield
    _reset_for_test()
    if saved is not None:
        os.environ["SP_SESSION_JWT"] = saved
    else:
        os.environ.pop("SP_SESSION_JWT", None)


class TestKernelSubprocessEnv:
    def test_load_session_jwt_then_env_is_clean(self):
        """After load_session_jwt pops env-var, os.environ no longer contains SP_SESSION_JWT."""
        os.environ["SP_SESSION_JWT"] = "secret-token"
        load_session_jwt()
        assert "SP_SESSION_JWT" not in os.environ

    def test_construct_kernel_env_never_leaks_jwt(self):
        """construct_kernel_env defensively pops SP_SESSION_JWT from base_env.

        Runs as subprocess — ipc.py has a heavy import chain requiring the full venv.
        """
        code = (
            "import os, sys\n"
            "from signalpilot._session.managers.ipc import construct_kernel_env\n"
            "base_env = dict(os.environ)\n"
            "base_env['SP_SESSION_JWT'] = 'should-be-removed'\n"
            "result = construct_kernel_env("
            "base_env=base_env, venv_python='/tmp/p', "
            "is_ephemeral_sandbox=False, writable=False)\n"
            "assert 'SP_SESSION_JWT' not in result, "
            "'SP_SESSION_JWT leaked into kernel env'"
        )
        result = _run_isolated(code)
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip(
                "Full notebook-server venv not available; skipping. "
                f"stderr: {result.stderr[:200]}"
            )
        assert result.returncode == 0, (
            f"Subprocess failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_full_boot_sequence_jwt_absent_in_kernel_env(self):
        """Full sequence: load_session_jwt pops env → kernel env is clean.

        Runs as subprocess — both start.py and ipc.py require the full venv.
        """
        code = (
            "import os\n"
            "os.environ['SP_SESSION_JWT'] = 'secret'\n"
            "from signalpilot._server.auth.session_token import load_session_jwt\n"
            "load_session_jwt()\n"
            "from signalpilot._session.managers.ipc import construct_kernel_env\n"
            "result = construct_kernel_env("
            "base_env=os.environ.copy(), venv_python='/tmp/p', "
            "is_ephemeral_sandbox=False, writable=False)\n"
            "assert 'SP_SESSION_JWT' not in result, "
            "'SP_SESSION_JWT leaked into kernel env after boot sequence'"
        )
        result = _run_isolated(code)
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip(
                "Full notebook-server venv not available; skipping. "
                f"stderr: {result.stderr[:200]}"
            )
        assert result.returncode == 0, (
            f"Subprocess failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_start_import_pops_jwt_subprocess(self):
        """Importing signalpilot._server.start pops SP_SESSION_JWT (subprocess test)."""
        code = (
            "import os\n"
            "os.environ['SP_SESSION_JWT'] = 'abc'\n"
            "import signalpilot._server.start\n"
            "assert 'SP_SESSION_JWT' not in os.environ, "
            "'SP_SESSION_JWT still in env after start import'"
        )
        result = _run_isolated(code)
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip(
                "Full notebook-server venv not available; skipping start import test. "
                f"stderr: {result.stderr[:200]}"
            )
        assert result.returncode == 0, (
            f"Subprocess failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
