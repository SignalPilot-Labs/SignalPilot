"""F-9 gate test (S8): AST-walk to detect persisted git config http.extraHeader.

Walks every .py file under signalpilot/_server/ and flags any ast.Call node that:
  - calls _run_git, run_git, or a method named either, AND
  - has "config" as an argument, AND
  - has "http.extraHeader" as an argument.

This pattern indicates an auth header being persisted into .git/config, which
is forbidden. The auth header must only ever be passed via
  git -c http.extraHeader=...
(per-invocation, not persisted).

Round-4 lesson: use AST (not tokenize) for docstring exclusion.
Tokenize-based STRING-token exclusion swallows the exact pattern being guarded
against. AST correctly identifies docstrings as Module/Function/Class body[0]
being an Expr(Constant(str)) node.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

# Root of the code to scan
_SCAN_ROOT = (
    Path(__file__).parent.parent.parent.parent  # tests/ → notebook-server/
    / "signalpilot"
    / "_server"
)


def _is_docstring(node: ast.stmt) -> bool:
    """Return True if the node is a docstring (Expr wrapping a string Constant)."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_git_config_with_extra_header(node: ast.Call) -> bool:
    """Return True if this Call looks like:
        _run_git(repo, "config", ..., "http.extraHeader", ...)
      or
        run_git(repo, "config", ..., "http.extraHeader", ...)

    We inspect positional args only (the persisted-header pattern uses positional args).
    Minimum shape: func(repo, "config", <any>, "http.extraHeader")
    """
    # Check the function name
    func = node.func
    func_name: str | None = None
    if isinstance(func, ast.Name):
        func_name = func.id
    elif isinstance(func, ast.Attribute):
        func_name = func.attr

    if func_name not in ("_run_git", "run_git"):
        return False

    # Need at least 4 positional args: (repo, "config", ..., "http.extraHeader")
    args = node.args
    if len(args) < 4:
        return False

    # args[1] must be "config"
    if not (isinstance(args[1], ast.Constant) and args[1].value == "config"):
        return False

    # Any of args[2:] must be "http.extraHeader"
    for arg in args[2:]:
        if isinstance(arg, ast.Constant) and arg.value == "http.extraHeader":
            return True

    return False


def _collect_violations(source_root: Path) -> list[str]:
    """Walk all .py files under source_root and return violation messages."""
    violations: list[str] = []

    for py_file in sorted(source_root.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            continue

        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_git_config_with_extra_header(node):
                rel = py_file.relative_to(source_root.parent.parent)
                violations.append(
                    f"{rel}:{node.lineno} — persisted git config http.extraHeader detected"
                )

    return violations


class TestNoPersistedHttpExtraHeader:
    def test_no_persisted_http_extraheader_in_server_code(self):
        """No .py file under signalpilot/_server/ persists http.extraHeader via git config."""
        if not _SCAN_ROOT.exists():
            # If scan root doesn't exist (e.g. running outside the repo), skip gracefully.
            import pytest
            pytest.skip(f"Scan root not found: {_SCAN_ROOT}")

        violations = _collect_violations(_SCAN_ROOT)

        assert not violations, (
            "Persisted git config http.extraHeader detected:\n"
            + "\n".join(f"  {v}" for v in violations)
            + "\n\nAuth headers MUST be passed per-invocation via "
            "'git -c http.extraHeader=...' — never written to .git/config."
        )

    def test_scanner_detects_injection(self, tmp_path):
        """Meta-test: the scanner catches an injected violation."""
        injected = textwrap.dedent("""
            from pathlib import Path
            import subprocess

            def some_function(repo: Path) -> None:
                # This simulates a regression
                subprocess.run(["git", "config", "--local", "http.extraHeader", "Authorization: Basic X"])
                _run_git(repo, "config", "--local", "http.extraHeader", "Authorization: Basic X")
        """)

        fake_file = tmp_path / "fake_module.py"
        fake_file.write_text(injected)

        # Build a fake scan root with just this file
        violations = _collect_violations(tmp_path)
        assert violations, (
            "Scanner should have detected the injected http.extraHeader persistence"
        )
        assert "fake_module.py" in violations[0]

    def test_scanner_ignores_docstrings(self, tmp_path):
        """Scanner does not flag strings in docstrings."""
        docstring_only = textwrap.dedent('''
            def safe_function() -> None:
                """This function mentions http.extraHeader in docs only.

                Example of what NOT to do:
                    _run_git(repo, "config", "--local", "http.extraHeader", "value")
                But the above is in a docstring, not in code.
                """
                pass
        ''')

        fake_file = tmp_path / "docstring_module.py"
        fake_file.write_text(docstring_only)

        violations = _collect_violations(tmp_path)
        # Docstring content is not parsed as AST Call nodes — no violations
        assert not violations, (
            "Scanner incorrectly flagged content inside a docstring"
        )

    def test_scanner_ignores_non_config_calls(self, tmp_path):
        """Scanner only flags calls with 'config' and 'http.extraHeader' together."""
        safe_code = textwrap.dedent("""
            from pathlib import Path

            def safe_function(repo: Path) -> None:
                # Fetch is fine — no config, no extraHeader
                _run_git(repo, "fetch", "origin")
                # Config without extraHeader is fine
                _run_git(repo, "config", "user.email", "x@example.com")
        """)

        fake_file = tmp_path / "safe_module.py"
        fake_file.write_text(safe_code)

        violations = _collect_violations(tmp_path)
        assert not violations, f"Unexpected violations: {violations}"
