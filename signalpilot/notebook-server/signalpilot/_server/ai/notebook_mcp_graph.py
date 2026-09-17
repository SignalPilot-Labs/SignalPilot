"""Graph validation and rejection payloads for the notebook MCP tools.

Every edit batch is compiled into a candidate dataflow graph before the
document changes. A rejection carries marimo's own message plus a hint that
names the defining cell and the two valid moves, so the agent does not loop
on the same rejection.
"""

from __future__ import annotations

import ast
import json
import symtable
from typing import TYPE_CHECKING, Any, NoReturn

from signalpilot import _loggers

if TYPE_CHECKING:
    from collections.abc import Collection

    from signalpilot._types.ids import CellId_t

LOGGER = _loggers.sp_logger()

__all__ = [
    "NotebookToolError",
    "_graph_error_payload",
    "_is_markdown_only_cell",
    "_raise_notebook_failure",
    "_record_notebook_failure",
    "_validate_candidate_graph",
]


class NotebookToolError(ValueError):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        # Insertion order is the agent-facing order: exception type and
        # message before the traceback text.
        super().__init__(json.dumps(payload, default=str))


def _graph_error_payload(
    *,
    error_type: str,
    cell_ids: list[str],
    variable: str | None = None,
    message: str | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "type": error_type,
        "variable": variable,
        "cell_ids": sorted(set(cell_ids)),
    }
    if message:
        error["message"] = message[:500]
    if hint:
        error["hint"] = hint[:500]
    return {"status": "rejected", "has_errors": True, "error": error}


def _private_names(code: str) -> tuple[set[str], set[str]]:
    table = symtable.symtable(code, "<notebook-cell>", "exec")
    definitions = {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.get_name().startswith("_")
        and (
            symbol.is_assigned()
            or symbol.is_imported()
            or symbol.is_namespace()
        )
    }
    references: set[str] = set()

    def collect_references(scope: symtable.SymbolTable, *, root: bool) -> None:
        for symbol in scope.get_symbols():
            if (
                symbol.get_name().startswith("_")
                and symbol.is_referenced()
                and (root or symbol.is_global())
            ):
                references.add(symbol.get_name())
        for child in scope.get_children():
            collect_references(child, root=False)

    collect_references(table, root=True)
    return definitions, references


def _validate_private_cross_cell_references(
    cells: list[tuple[CellId_t, str]],
) -> None:
    private_by_cell = {
        str(cell_id): _private_names(code) for cell_id, code in cells
    }
    defining_cells: dict[str, set[str]] = {}
    for cell_id, (definitions, _references) in private_by_cell.items():
        for name in definitions:
            defining_cells.setdefault(name, set()).add(cell_id)

    for cell_id, (definitions, references) in private_by_cell.items():
        for name in sorted(references - definitions):
            sources = defining_cells.get(name, set()) - {cell_id}
            if sources:
                source_list = ", ".join(sorted(sources))
                raise NotebookToolError(
                    _graph_error_payload(
                        error_type="PrivateVariableCrossCellReference",
                        variable=name,
                        cell_ids=[cell_id, *sorted(sources)],
                        message=(
                            f"{name} is private to cell(s) {sorted(sources)} and "
                            f"cannot be referenced from cell {cell_id}; rename it "
                            "to one unique public name or keep its use in the defining cell"
                        ),
                        hint=(
                            "Give the value a name without a leading "
                            f"underscore in cell {source_list}."
                        ),
                    )
                )


def _multiple_definition_hint(
    variable: str,
    involved: set[str],
    *,
    batch_cell_ids: Collection[str],
    new_cell_ids: Collection[str],
) -> str:
    """Name the cell that already defines ``variable`` and the two valid moves."""
    batch = set(batch_cell_ids)
    already = sorted(involved - batch) if batch else sorted(involved)
    offending = sorted(involved & batch)
    if offending and all(cell in set(new_cell_ids) for cell in offending):
        target = "the new cell"
    elif offending:
        target = f"cell {', '.join(offending)}"
    else:
        target = "one of them"
    if len(already) == 1:
        return (
            f"cell {already[0]} already defines `{variable}`. Either include "
            f"update_cell for {already[0]} in this batch, or use a different "
            f"name in {target}."
        )
    if already:
        return (
            f"cells {', '.join(already)} already define `{variable}`. Either "
            "include update_cell or delete_cell for them in this batch, or "
            f"use a different name in {target}."
        )
    return (
        f"cells {', '.join(sorted(involved))} in this batch all define "
        f"`{variable}`. Use a different name in all but one of them."
    )


def _validate_candidate_graph(
    cells: list[tuple[CellId_t, str]],
    *,
    batch_cell_ids: Collection[str] = (),
    new_cell_ids: Collection[str] = (),
) -> None:
    """Compile every cell into one graph and raise on the first marimo error.

    ``batch_cell_ids`` are the cells this edit batch adds or updates and
    ``new_cell_ids`` the subset that does not exist yet. Both only shape the
    hint text; the graph rules are marimo's own.
    """
    import linecache

    from signalpilot._ast.compiler import compile_cell, get_filename
    from signalpilot._lint.validate_graph import check_for_errors
    from signalpilot._runtime.dataflow import DirectedGraph

    filenames = {get_filename(cell_id) for cell_id, _code in cells}
    previous_cache = {
        filename: linecache.cache.get(filename) for filename in filenames
    }
    try:
        graph = DirectedGraph()
        for cell_id, code in cells:
            try:
                graph.register_cell(
                    cell_id, compile_cell(code, cell_id=cell_id)
                )
            except SyntaxError as exc:
                raise NotebookToolError(
                    _graph_error_payload(
                        error_type="SyntaxError",
                        cell_ids=[str(cell_id)],
                        message=exc.msg,
                    )
                ) from exc

        _validate_private_cross_cell_references(cells)
        graph_errors = check_for_errors(graph)
        for cell_id in sorted(graph_errors, key=str):
            for error in graph_errors[cell_id]:
                error_type = type(error).__name__
                variable = str(getattr(error, "name", "") or "") or None
                involved = {str(cell_id)}
                involved.update(
                    str(value) for value in getattr(error, "cells", ())
                )
                edge_variables: set[str] = set()
                for source, variables, target in getattr(
                    error, "edges_with_vars", ()
                ):
                    involved.update((str(source), str(target)))
                    edge_variables.update(str(value) for value in variables)
                if variable is None and edge_variables:
                    variable = sorted(edge_variables)[0]
                hint = None
                if error_type == "MultipleDefinitionError" and variable:
                    hint = _multiple_definition_hint(
                        variable,
                        involved,
                        batch_cell_ids=batch_cell_ids,
                        new_cell_ids=new_cell_ids,
                    )
                raise NotebookToolError(
                    _graph_error_payload(
                        error_type=error_type,
                        variable=variable,
                        cell_ids=sorted(involved),
                        message=error.describe(),
                        hint=hint,
                    )
                )
    finally:
        for filename, cached in previous_cache.items():
            if cached is None:
                linecache.cache.pop(filename, None)
            else:
                linecache.cache[filename] = cached


def _record_notebook_failure(
    session: Any,
    payload: dict[str, Any],
    *,
    dirty: bool,
) -> None:
    session._signalpilot_last_notebook_failure = payload
    recorded = list(getattr(session, "_signalpilot_notebook_failures", ()))
    recorded.append(payload)
    session._signalpilot_notebook_failures = recorded[-20:]
    if dirty:
        session._signalpilot_notebook_dirty = True
    error = payload.get("error") or {}
    LOGGER.error(
        "Notebook operation failed run_id=%s session_id=%s attempt=%s "
        "error_type=%s variable=%s cell_ids=%s dirty=%s",
        getattr(session, "_signalpilot_chat_run_id", ""),
        getattr(session, "_signalpilot_chat_session_id", ""),
        getattr(session, "_signalpilot_chat_attempt", ""),
        error.get("type"),
        error.get("variable"),
        error.get("cell_ids"),
        dirty,
    )


def _raise_notebook_failure(
    session: Any,
    payload: dict[str, Any],
    *,
    dirty: bool,
) -> NoReturn:
    _record_notebook_failure(session, payload, dirty=dirty)
    raise NotebookToolError(payload)


def _is_markdown_call(value: ast.AST) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr == "md":
        return isinstance(func.value, ast.Name) and func.value.id in {
            "sp",
            "mo",
        }
    return False


def _is_markdown_only_cell(code: str) -> bool:
    try:
        parsed = ast.parse(code)
    except SyntaxError:
        return False

    has_markdown_call = False
    for node in parsed.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and _is_markdown_call(node.value):
            has_markdown_call = True
            continue
        return False
    return has_markdown_call
