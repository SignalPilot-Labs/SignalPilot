from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from signalpilot import _loggers
from signalpilot._ast.app import App, InternalApp
from signalpilot._ast.app_config import _AppConfig
from signalpilot._ast.parse import (
    SpFileError,
    NonSignalPilotPythonScriptError,
    all_violations_soft,
    is_non_signalpilot_python_script,
)
from signalpilot._schemas.serialization import (
    CellDef,
    NotebookSerialization,
    UnparsableCell,
)
from signalpilot._session.notebook.serializer import get_notebook_serializer
from signalpilot._utils.sp_path import SpPath

LOGGER = _loggers.sp_logger()

# Notebooks have 4 entry points:
# 1. edit mode
# 2. run mode
# 3. as a script
# 4. loaded as a module
#
# When being run as a script or module, the expectation is to run _as_ python.
# However for "managed" sp (i.e. run/ edit), the expectation is to not fail
# on startup and defer errors to the runtime.


@dataclass
class LoadResult:
    """Result of attempting to load a sp notebook.

    status can be one of:
     - empty: No content, or only comments / a doc string
     - has_warnings: Parsed, but has soft issues auto-corrected on save
     - has_errors: Parsed, but has errors that may lose data on save (**can load!!**)
     - invalid: Could not be parsed as a sp notebook (**cannot load**)
     - valid: Parsed and valid sp notebook
    """

    status: Literal[
        "empty", "has_warnings", "has_errors", "invalid", "valid"
    ] = "empty"
    notebook: NotebookSerialization | None = None
    contents: str | None = None


def _maybe_contents(filename: str | Path | None) -> str | None:
    if filename is None:
        return None

    return Path(filename).read_text(encoding="utf-8", errors="replace").strip()


def find_cell(filename: str, lineno: int) -> CellDef | None:
    """Find the cell at the given line number in the notebook.

    Args:
        filename: Path to a sp notebook file (.py or .md)
        lineno: Line number to search for
    """
    load_result = get_notebook_status(filename)
    if load_result.notebook is None:
        raise OSError("Could not resolve notebook.")
    previous = None
    for cell in load_result.notebook.cells:
        if cell.lineno > lineno:
            break
        previous = cell
    return previous


def load_notebook_ir(
    notebook: NotebookSerialization, filepath: str | None = None
) -> App:
    """Load a notebook IR into an App."""
    # Use filepath from notebook if not explicitly provided
    if filepath is None:
        filepath = notebook.filename

    # Markdown frontmatter may contain non-config metadata (e.g., author,
    # description). Filter to only pass recognized config keys to App().
    options = notebook.app.options
    if filepath and SpPath(filepath).is_markdown():
        options = _AppConfig.sanitize(options)

    app = App(**options, _filename=filepath)
    for cell in notebook.cells:
        if isinstance(cell, UnparsableCell):
            app._unparsable_cell(cell.code, **cell.options)
            continue
        app._cell_manager.register_ir_cell(cell, InternalApp(app))
    if notebook.header and notebook.header.value:
        app._header = notebook.header.value
    return app


def get_notebook_status(filename: str) -> LoadResult:
    """Attempts to parse an app- should raise SyntaxError on failure.

    Args:
        filename: Path to a sp notebook file (.py or .md)

    Returns:
        True if a falid code path.

    Raises:
        SyntaxError: If the file contains a syntax error
    """
    path = Path(filename)

    contents = _maybe_contents(filename)
    if not contents:
        return LoadResult(status="empty", contents=contents)

    notebook: NotebookSerialization | None = None
    handler = get_notebook_serializer(path)
    notebook = handler.deserialize(contents, filepath=filename)

    # NB. A invalid notebook can still be opened.
    if notebook is None:
        return LoadResult(status="empty", contents=contents)
    if not notebook.valid:
        if is_non_signalpilot_python_script(notebook):
            return LoadResult(
                status="invalid", notebook=notebook, contents=contents
            )
        # Only comments or a doc string — treat as empty per status definition
        return LoadResult(status="empty", notebook=notebook, contents=contents)
    if len(notebook.violations) > 0:
        LOGGER.debug(
            "Notebook has violations: \n%s",
            "\n".join(map(repr, notebook.violations)),
        )
        if all_violations_soft(notebook.violations):
            return LoadResult(
                status="has_warnings", notebook=notebook, contents=contents
            )
        return LoadResult(
            status="has_errors", notebook=notebook, contents=contents
        )
    return LoadResult(status="valid", notebook=notebook, contents=contents)


FAILED_LOAD_NOTEBOOK_MESSAGE = (
    "Static loading of notebook failed. "
    "Please report this issue to the sp team and include your notebook if possible — "
    "https://docs.signalpilot.ai/docs/"
)


def load_app(filename: str | Path | None) -> App | None:
    """Load and return app from a sp-generated module.

    Args:
        filename: Path to a sp notebook file (.py or .md)

    Returns:
        The sp App instance if the file exists and contains valid code,
        None if the file is empty or contains only comments.

    Raises:
        SpFileError: If the file exists but doesn't define a valid sp app
        RuntimeError: If there are issues loading the module
        SyntaxError: If the file contains a syntax error
        FileNotFoundError: If the file doesn't exist
    """

    if filename is None:
        return None

    path = Path(filename)
    handler = get_notebook_serializer(path)

    contents = _maybe_contents(filename)
    if not contents:
        return None

    try:
        notebook_ir = handler.deserialize(contents, filepath=str(path))
        if notebook_ir and is_non_signalpilot_python_script(notebook_ir):
            # Should fail instead of overriding contents
            raise NonSignalPilotPythonScriptError(
                f"Python script {path} is not a sp notebook."
            )

        if not notebook_ir.valid:
            LOGGER.error(f"Notebook {path} is not a valid sp notebook.")
            return None

        app = load_notebook_ir(notebook_ir)
        app._cell_manager.ensure_one_cell()
        return app
    except SpFileError as e:
        LOGGER.error(FAILED_LOAD_NOTEBOOK_MESSAGE)
        raise SpFileError(FAILED_LOAD_NOTEBOOK_MESSAGE) from e
