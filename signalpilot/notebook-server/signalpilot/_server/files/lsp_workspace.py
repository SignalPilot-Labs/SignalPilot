# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from signalpilot._config.reader import find_nearest_pyproject_toml

DEFAULT_NOTEBOOK_NAME = "__signalpilot_notebook__.py"


class LspWorkspace(TypedDict):
    rootUri: str
    documentUri: str


def resolve_lsp_workspace(
    filename: str | None, directory: str | None
) -> LspWorkspace:
    directory_path = Path(directory or ".").absolute()

    if filename:
        document_path = Path(filename)
        if not document_path.is_absolute():
            document_path = directory_path.joinpath(filename)
        start_path = document_path.parent
    else:
        document_path = directory_path.joinpath(DEFAULT_NOTEBOOK_NAME)
        start_path = directory_path

    if pyproject_path := find_nearest_pyproject_toml(start_path):
        root_path = pyproject_path.parent
    else:
        root_path = directory_path if directory else start_path

    return {
        "rootUri": root_path.as_uri(),
        "documentUri": document_path.as_uri(),
    }
