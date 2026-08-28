"""Bounded in-memory Python evaluator for standalone chat scratch work."""

from __future__ import annotations

import ast
import json
import math
import statistics
from typing import Any

MAX_PYTHON_SOURCE_CHARS = 12_000

_FORBIDDEN_AST_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Global,
    ast.Nonlocal,
)
_FORBIDDEN_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "vars",
}


def _run_restricted_python(source: str, data: Any) -> dict[str, Any]:
    if len(source) > MAX_PYTHON_SOURCE_CHARS:
        raise ValueError("Python source is too large")
    if len(json.dumps(data, default=str).encode("utf-8")) > 1_000_000:
        raise ValueError("Scratch input is too large")
    tree = ast.parse(source, mode="exec")
    nodes = list(ast.walk(tree))
    if len(nodes) > 2_000:
        raise ValueError("Python source is too complex")
    for node in nodes:
        if isinstance(node, _FORBIDDEN_AST_NODES):
            raise ValueError(
                f"{type(node).__name__} is unavailable in scratch analysis"
            )
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError(
                "Dunder names are unavailable in scratch analysis"
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError(
                "Dunder attributes are unavailable in scratch analysis"
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FORBIDDEN_CALLS
        ):
            raise ValueError(
                f"{node.func.id} is unavailable in scratch analysis"
            )
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and abs(node.value) > 10_000_000
        ):
            raise ValueError(
                "Large integer constants are unavailable in scratch analysis"
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left_is_sequence = isinstance(
                node.left, (ast.List, ast.Tuple)
            ) or (
                isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, (str, bytes))
            )
            right_is_sequence = isinstance(
                node.right, (ast.List, ast.Tuple)
            ) or (
                isinstance(node.right, ast.Constant)
                and isinstance(node.right.value, (str, bytes))
            )
            if left_is_sequence or right_is_sequence:
                raise ValueError(
                    "Sequence multiplication is unavailable in scratch analysis"
                )

    def safe_range(*args: int) -> range:
        value = range(*args)
        if len(value) > 10_000:
            raise ValueError("Scratch range is too large")
        return value

    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": safe_range,
        "reversed": reversed,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
    namespace: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "data": data,
        "json": json,
        "math": math,
        "statistics": statistics,
    }
    # The parsed tree is bounded and rejects imports, dunder access, dynamic
    # execution, file access, and other unsafe calls before this point.
    exec(  # nosec B102  # nosemgrep: python.lang.security.audit.exec-detected.exec-detected
        compile(tree, "<standalone-chat-scratch>", "exec"),
        namespace,
        namespace,
    )
    if "result" not in namespace:
        raise ValueError(
            "Set a JSON-serializable value in the variable 'result'"
        )
    serialized = json.dumps(namespace["result"], default=str)
    if len(serialized.encode("utf-8")) > 1_000_000:
        raise ValueError("Scratch result is too large")
    return {"result": json.loads(serialized)}
