"""AST/grep gate: no direct os.environ reads of SP_SESSION_JWT outside the two allowed files.

Allowed files (relative to the notebook-server/signalpilot/ directory):
- _server/auth/session_token.py  (single source of truth)
- _server/entrypoint.py           (boot-time shim)

Comments and docstrings are excluded from the check.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path


_ALLOWED_RELATIVE = {
    "_server/auth/session_token.py",
    "_server/entrypoint.py",
}

# Pattern that matches actual code lines referencing both os.environ and SP_SESSION_JWT.
# We exclude lines that are pure comments (stripped line starts with #) or
# are inside docstrings (detected via tokenize).
_SP_SESSION_JWT_RE = re.compile(r"SP_SESSION_JWT")
_OS_ENVIRON_RE = re.compile(r"os\.environ")


def _code_lines_with_both(py_file: Path) -> list[tuple[int, str]]:
    """Return (lineno, line) for lines that are non-comment, non-docstring
    and match both SP_SESSION_JWT and os.environ."""
    text = py_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    candidates: list[tuple[int, str]] = []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip pure comment lines.
        if stripped.startswith("#"):
            continue
        if _SP_SESSION_JWT_RE.search(line) and _OS_ENVIRON_RE.search(line):
            candidates.append((lineno, line))

    if not candidates:
        return []

    excluded_rows: set[int] = set()

    # Comment tokens: exclude their (single) row.
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        for tok_type, _tok_string, (srow, _), (erow, _), _ in tokens:
            if tok_type == tokenize.COMMENT:
                for row in range(srow, erow + 1):
                    excluded_rows.add(row)
    except tokenize.TokenError:
        pass

    # Docstrings: walk AST and exclude rows spanned by module/class/function docstrings.
    try:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                start = first.lineno
                end = getattr(first, "end_lineno", start) or start
                for row in range(start, end + 1):
                    excluded_rows.add(row)
    except SyntaxError:
        pass

    return [
        (lineno, line)
        for lineno, line in candidates
        if lineno not in excluded_rows
    ]


class TestNoDirectEnvReads:
    def test_sp_session_jwt_only_in_allowed_files(self):
        """No code in notebook-server touches SP_SESSION_JWT via os.environ except allowed files."""
        root = Path(__file__).parent.parent / "signalpilot"
        violations: list[str] = []

        for py_file in root.rglob("*.py"):
            # Compute relative path from the signalpilot/ directory.
            rel = py_file.relative_to(root)
            rel_str = str(rel)

            if rel_str in _ALLOWED_RELATIVE:
                continue

            for lineno, line in _code_lines_with_both(py_file):
                violations.append(f"{rel_str}:{lineno}: {line.strip()}")

        assert not violations, (
            "Direct os.environ reads of SP_SESSION_JWT found outside allowed files:\n"
            + "\n".join(violations)
        )
