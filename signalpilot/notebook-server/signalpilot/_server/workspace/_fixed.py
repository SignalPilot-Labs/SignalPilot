"""Workspace for a fixed list of notebooks (``sp run a.py b.py``)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from signalpilot._server.models.files import FileInfo
from signalpilot._server.workspace._base import (
    NEW_FILE,
    SpFileKey,
    NotebookWorkspace,
    file_not_found,
    normalize_allowlist_entry,
)
from signalpilot._utils.paths import normalize_path

if TYPE_CHECKING:
    from signalpilot._server.models.home import SpFile


class FixedFilesWorkspace(NotebookWorkspace):
    """A workspace pointing at a fixed allowlist of notebooks.

    Used by ``sp run a.py b.py`` and ``sp run dir/`` snapshots. The
    allowlist is set at construction time and never grows.
    """

    def __init__(
        self,
        files: list[SpFile],
        directory: str | None = None,
    ) -> None:
        self._files = files
        self._directory = directory
        self._allowed_paths = {
            normalize_allowlist_entry(file.path) for file in files
        }

    @property
    def directory(self) -> str | None:
        return self._directory

    @property
    def files(self) -> list[FileInfo]:
        return [
            FileInfo(
                id=file.path,
                name=file.name,
                path=file.path,
                last_modified=file.last_modified,
                is_directory=False,
                is_sp_file=True,
            )
            for file in self._files
        ]

    def single_file(self) -> SpFile | None:
        return None

    def get_unique_file_key(self) -> SpFileKey | None:
        return None

    def resolve(self, key: SpFileKey) -> str | None:
        if key.startswith(NEW_FILE):
            raise file_not_found(key)

        filepath = Path(key)
        if not filepath.is_absolute() and self._directory:
            filepath = Path(self._directory) / filepath
        normalized_path = normalize_path(filepath)
        absolute_path = str(normalized_path)
        if absolute_path not in self._allowed_paths:
            raise file_not_found(key)

        if normalized_path.exists():
            return absolute_path

        raise file_not_found(key)
