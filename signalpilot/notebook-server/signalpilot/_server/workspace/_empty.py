"""Workspace for an untitled (new) notebook."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from signalpilot._server.workspace._base import (
    NEW_FILE,
    SpFileKey,
    NotebookWorkspace,
    file_not_found,
)
from signalpilot._utils.paths import normalize_path

if TYPE_CHECKING:
    from signalpilot._server.models.files import FileInfo
    from signalpilot._server.models.home import SpFile


class EmptyWorkspace(NotebookWorkspace):
    """An empty (untitled) workspace, used by ``sp new``.

    The workspace key is the ``__new__`` sentinel; concrete file paths are
    accepted as a fallback so that callers which bootstrap with
    ``EmptyWorkspace`` and later open a real file (e.g. via the homepage)
    continue to work.
    """

    def get_unique_file_key(self) -> SpFileKey | None:
        return NEW_FILE

    def single_file(self) -> SpFile | None:
        return None

    @property
    def files(self) -> list[FileInfo]:
        return []

    def resolve(self, key: SpFileKey) -> str | None:
        if key.startswith(NEW_FILE):
            return None
        if os.path.exists(key):
            # Match sibling workspaces: return an absolute normalized path so
            # downstream comparisons (e.g. session lookups) don't trip on
            # relative-vs-absolute mismatches.
            return str(normalize_path(Path(key)))
        raise file_not_found(key)
