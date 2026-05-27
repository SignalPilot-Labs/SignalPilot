# Copyright 2026 SignalPilot. All rights reserved.
"""Notebook file management and storage abstractions."""

from __future__ import annotations

from signalpilot._session.notebook.file_manager import (
    AppFileManager,
    read_css_file,
    read_html_head_file,
)
from signalpilot._session.notebook.loader import (
    load_notebook,
    new_notebook,
)
from signalpilot._session.notebook.serializer import (
    MarkdownNotebookSerializer,
    NotebookSerializer,
    PythonNotebookSerializer,
)
from signalpilot._session.notebook.storage import (
    FilesystemStorage,
    StorageInterface,
)

__all__ = [
    "AppFileManager",
    "FilesystemStorage",
    "MarkdownNotebookSerializer",
    "NotebookSerializer",
    "PythonNotebookSerializer",
    "StorageInterface",
    "load_notebook",
    "new_notebook",
    "read_css_file",
    "read_html_head_file",
]
