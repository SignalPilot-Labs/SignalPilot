"""Tests for kernel_runner — stateful REPL kernel."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

KERNEL_PATH = str(Path(__file__).resolve().parent.parent / "kernel_runner.py")


def _encode(msg: dict) -> bytes:
    payload = json.dumps(msg).encode()
    return struct.pack(">I", len(payload)) + payload


def _decode(data: bytes, offset: int = 0) -> tuple[dict, int]:
    length = struct.unpack(">I", data[offset : offset + 4])[0]
    payload = data[offset + 4 : offset + 4 + length]
    return json.loads(payload), offset + 4 + length


def _run_cells(cells: list[dict]) -> list[dict]:
    proc = subprocess.Popen(
        [sys.executable, KERNEL_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdin_bytes = b"".join(_encode(c) for c in cells)
    stdout, _ = proc.communicate(input=stdin_bytes, timeout=10)

    results = []
    ready, offset = _decode(stdout)
    assert ready == {"status": "ready"}
    while offset < len(stdout):
        msg, offset = _decode(stdout, offset)
        results.append(msg)
    return results


def test_variable_persistence():
    results = _run_cells([
        {"code": "x = 42", "cell_id": "1"},
        {"code": "print(x)", "cell_id": "2"},
    ])
    assert len(results) == 2
    assert results[0]["success"] is True
    assert results[1]["success"] is True
    assert results[1]["output"].strip() == "42"


def test_last_expression_display():
    results = _run_cells([
        {"code": "1 + 1", "cell_id": "expr"},
    ])
    assert results[0]["output"].strip() == "2"


def test_multi_statement_last_expr():
    results = _run_cells([
        {"code": "a = 10\nb = 20\na + b", "cell_id": "multi"},
    ])
    assert results[0]["success"] is True
    assert results[0]["output"].strip() == "30"


def test_syntax_error():
    results = _run_cells([
        {"code": "def foo(", "cell_id": "bad"},
    ])
    assert results[0]["success"] is False
    assert "SyntaxError" in results[0]["error"]


def test_runtime_error():
    results = _run_cells([
        {"code": "1 / 0", "cell_id": "div0"},
    ])
    assert results[0]["success"] is False
    assert "ZeroDivisionError" in results[0]["error"]


def test_cell_id_passthrough():
    results = _run_cells([
        {"code": "True", "cell_id": "abc-123"},
    ])
    assert results[0]["cell_id"] == "abc-123"


def test_no_cell_id():
    results = _run_cells([
        {"code": "True"},
    ])
    assert "cell_id" not in results[0]


def test_empty_cell():
    results = _run_cells([
        {"code": "", "cell_id": "empty"},
    ])
    assert results[0]["success"] is True
    assert results[0]["output"] == ""


def test_multiline_function():
    results = _run_cells([
        {"code": "def greet(name):\n    return f'hello {name}'", "cell_id": "1"},
        {"code": "greet('world')", "cell_id": "2"},
    ])
    assert results[0]["success"] is True
    assert results[1]["output"].strip() == "'hello world'"


def test_import_persistence():
    results = _run_cells([
        {"code": "import math", "cell_id": "1"},
        {"code": "math.pi", "cell_id": "2"},
    ])
    assert results[1]["success"] is True
    assert "3.14159" in results[1]["output"]


def test_stderr_capture():
    results = _run_cells([
        {"code": "import sys; print('warn', file=sys.stderr)", "cell_id": "1"},
    ])
    assert results[0]["success"] is True
    assert "warn" in results[0]["output"]
