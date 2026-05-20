"""AST test (C4): only pod_exec_io.py may import the K8s exec API.

Walks every .py file under gateway/ with ast.parse. Asserts that the set of
files importing 'connect_get_namespaced_pod_exec', 'WsApiClient', or 'stream'
from 'kubernetes_asyncio.stream' equals exactly {'orchestrator/pod_exec_io.py'}.

Also asserts (via regex over file bytes) that no other file contains the string
'connect_get_namespaced_pod_exec'.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_GATEWAY_PACKAGE = Path(__file__).parent.parent / "gateway"
_SOLE_AUTHORIZED_FILE = "orchestrator/pod_exec_io.py"

_EXEC_API_NAMES = frozenset(
    ["connect_get_namespaced_pod_exec", "WsApiClient"]
)
_K8S_STREAM_MODULE = "kubernetes_asyncio.stream"
_EXEC_API_PATTERN = re.compile(rb"connect_get_namespaced_pod_exec")


def _relative_path(file: Path) -> str:
    """Return path relative to gateway package root (always forward slashes)."""
    return file.relative_to(_GATEWAY_PACKAGE).as_posix()


def _collect_exec_imports(file: Path) -> bool:
    """Return True if the file imports any exec API names from kubernetes_asyncio.stream."""
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _K8S_STREAM_MODULE in module or module == "kubernetes_asyncio":
                imported_names = {alias.name for alias in node.names}
                if imported_names & _EXEC_API_NAMES:
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _K8S_STREAM_MODULE or alias.name.startswith(
                    "kubernetes_asyncio.stream"
                ):
                    return True

    return False


class TestPodExecCallerInvariant:
    def test_pod_exec_callers_are_only_pod_exec_io(self):
        """Only orchestrator/pod_exec_io.py may import the kubernetes_asyncio exec API (C4)."""
        assert _GATEWAY_PACKAGE.is_dir(), (
            f"Gateway package not found at {_GATEWAY_PACKAGE}. "
            "Run tests from the repo root."
        )

        all_py_files = list(_GATEWAY_PACKAGE.rglob("*.py"))
        assert all_py_files, "No .py files found in gateway package"

        importing_files: set[str] = set()
        for py_file in all_py_files:
            rel = _relative_path(py_file)
            if _collect_exec_imports(py_file):
                importing_files.add(rel)

        expected = {_SOLE_AUTHORIZED_FILE}
        # Use equality (not subset) so that:
        #   - Removing the import from pod_exec_io.py fails (importing_files would be empty).
        #   - Adding it to another file also fails.
        assert importing_files == expected, (
            f"Expected exactly {expected} to import kubernetes_asyncio exec API. "
            f"Got: {importing_files}. "
            "Only orchestrator/pod_exec_io.py is allowed to use pods/exec (C4)."
        )

    def test_no_other_file_contains_exec_api_string(self):
        """No file other than pod_exec_io.py contains 'connect_get_namespaced_pod_exec'."""
        all_py_files = list(_GATEWAY_PACKAGE.rglob("*.py"))
        violating: list[str] = []

        for py_file in all_py_files:
            rel = _relative_path(py_file)
            if rel == _SOLE_AUTHORIZED_FILE:
                continue
            content = py_file.read_bytes()
            if _EXEC_API_PATTERN.search(content):
                violating.append(rel)

        assert not violating, (
            f"Files containing 'connect_get_namespaced_pod_exec' outside pod_exec_io: "
            f"{violating}. This string must only appear in orchestrator/pod_exec_io.py (C4)."
        )
