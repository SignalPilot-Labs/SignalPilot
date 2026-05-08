"""
Stateful Python REPL kernel.

Reads length-prefixed JSON requests from stdin, executes in a persistent
namespace, writes length-prefixed JSON results to stdout. Variables persist
between cells.

Wire protocol: 4-byte big-endian length prefix + UTF-8 JSON payload.
Request:  {"code": "x = 1", "timeout": 30, "cell_id": "abc"}
Response: {"success": true, "output": "", "error": null, "cell_id": "abc"}

Zero external dependencies — stdlib only.
"""

from __future__ import annotations

import ast
import io
import json
import signal
import struct
import sys
import traceback

_stdin = sys.stdin.buffer
_stdout = sys.stdout.buffer

MAX_OUTPUT_BYTES = 1_000_000


class CellTimeout(Exception):
    pass


def _alarm_handler(_signum, _frame):
    raise CellTimeout()


def read_message() -> dict | None:
    header = _stdin.read(4)
    if len(header) < 4:
        return None
    length = struct.unpack(">I", header)[0]
    data = b""
    while len(data) < length:
        chunk = _stdin.read(length - len(data))
        if not chunk:
            return None
        data += chunk
    return json.loads(data)


def write_message(msg: dict) -> None:
    payload = json.dumps(msg).encode("utf-8")
    _stdout.write(struct.pack(">I", len(payload)))
    _stdout.write(payload)
    _stdout.flush()


def execute_cell(code: str, namespace: dict, timeout: int = 30) -> dict:
    old_stdout, old_stderr = sys.stdout, sys.stderr
    capture_out = io.StringIO()
    capture_err = io.StringIO()
    sys.stdout = capture_out
    sys.stderr = capture_err

    error = None
    success = True

    try:
        if timeout > 0:
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(timeout)

        tree = ast.parse(code, mode="exec")

        if not tree.body:
            pass
        elif len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
            node = ast.Interactive(body=[tree.body[0]])
            ast.fix_missing_locations(node)
            exec(compile(node, "<cell>", "single"), namespace)
        else:
            *stmts, last = tree.body

            if stmts:
                module = ast.Module(body=stmts, type_ignores=[])
                ast.fix_missing_locations(module)
                exec(compile(module, "<cell>", "exec"), namespace)

            if isinstance(last, ast.Expr):
                node = ast.Interactive(body=[last])
                ast.fix_missing_locations(node)
                exec(compile(node, "<cell>", "single"), namespace)
            else:
                module = ast.Module(body=[last], type_ignores=[])
                ast.fix_missing_locations(module)
                exec(compile(module, "<cell>", "exec"), namespace)

    except CellTimeout:
        success = False
        error = f"Cell timed out after {timeout}s"
    except SyntaxError as e:
        success = False
        error = f"SyntaxError: {e.msg} (line {e.lineno})"
    except Exception:
        success = False
        error = traceback.format_exc()
    finally:
        signal.alarm(0)
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    output = capture_out.getvalue()[:MAX_OUTPUT_BYTES]
    stderr_text = capture_err.getvalue()[:MAX_OUTPUT_BYTES]
    if stderr_text and not error:
        output = (output + stderr_text) if output else stderr_text

    return {"success": success, "output": output, "error": error}


def main() -> None:
    namespace: dict = {"__name__": "__main__", "__builtins__": __builtins__}

    write_message({"status": "ready"})

    while True:
        msg = read_message()
        if msg is None:
            break

        code = msg.get("code", "")
        timeout = msg.get("timeout", 30)
        cell_id = msg.get("cell_id")

        result = execute_cell(code, namespace, timeout=timeout)
        if cell_id is not None:
            result["cell_id"] = cell_id

        write_message(result)


if __name__ == "__main__":
    main()
