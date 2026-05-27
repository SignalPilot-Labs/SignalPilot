# Copyright 2026 SignalPilot. All rights reserved.
"""Server-side notebook workspace abstractions.

A :class:`NotebookWorkspace` represents the set of notebooks a server is
hosting. Concrete subclasses cover:

- :class:`EmptyWorkspace` — untitled (``__new__``) notebook
- :class:`SingleFileWorkspace` — single notebook (``sp edit nb.py``)
- :class:`FixedFilesWorkspace` — fixed allowlist (``sp run a.py b.py``)
- :class:`DirectoryWorkspace` — lazy directory scan (``sp edit ./``)
"""

import os

from signalpilot import _loggers
from signalpilot._server.workspace._base import (
    NEW_FILE,
    SpFileKey,
    NotebookWorkspace,
    count_files,
    flatten_files,
)
from signalpilot._server.workspace._directory import DirectoryWorkspace
from signalpilot._server.workspace._empty import EmptyWorkspace
from signalpilot._server.workspace._fixed import FixedFilesWorkspace
from signalpilot._server.workspace._single import SingleFileWorkspace
from signalpilot._utils.http import HTTPException, HTTPStatus
from signalpilot._utils.sp_path import SpPath

LOGGER = _loggers.sp_logger()


def infer_workspace(path: str) -> NotebookWorkspace:
    """Pick a concrete workspace for a user-supplied file or directory path."""
    if os.path.isfile(path):
        LOGGER.debug("Routing to file %s", path)
        return SingleFileWorkspace.from_path(SpPath(path))
    if os.path.isdir(path):
        LOGGER.debug("Routing to directory %s", path)
        return DirectoryWorkspace(path, include_markdown=False)
    raise HTTPException(
        status_code=HTTPStatus.BAD_REQUEST,
        detail=f"Path {path} is not a valid file or directory",
    )


__all__ = [
    "NEW_FILE",
    "DirectoryWorkspace",
    "EmptyWorkspace",
    "FixedFilesWorkspace",
    "SpFileKey",
    "NotebookWorkspace",
    "SingleFileWorkspace",
    "count_files",
    "flatten_files",
    "infer_workspace",
]
