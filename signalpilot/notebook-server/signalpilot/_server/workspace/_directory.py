"""Workspace that lazily scans a directory of notebooks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from signalpilot import _loggers
from signalpilot._server.files.directory_scanner import DirectoryScanner
from signalpilot._server.files.path_validator import PathValidator
from signalpilot._server.workspace._base import (
    NEW_FILE,
    SpFileKey,
    NotebookWorkspace,
    file_not_found,
)
from signalpilot._utils.http import HTTPException, HTTPStatus

if TYPE_CHECKING:
    from signalpilot._server.models.files import FileInfo
    from signalpilot._server.models.home import SpFile

LOGGER = _loggers.sp_logger()


class DirectoryWorkspace(NotebookWorkspace):
    """A workspace backed by a directory, scanned lazily on demand.

    Used by ``sp edit ./`` and ``sp run ./``. File access is validated
    via :class:`PathValidator` to ensure paths stay within the directory (or an
    explicitly registered temp directory).
    """

    def __init__(self, directory: str, include_markdown: bool) -> None:
        # Make absolute but don't resolve symlinks — preserve user paths.
        abs_directory = Path(directory).absolute()
        self._directory = str(abs_directory)
        self._include_markdown = include_markdown
        self._lazy_files: list[FileInfo] | None = None
        self._validator = PathValidator(abs_directory)
        self._scanner = DirectoryScanner(str(abs_directory), include_markdown)
        # Allow access to cloud project sync directories
        try:
            from signalpilot._server.files.project_sync import PROJECTS_ROOT
            if PROJECTS_ROOT.exists():
                self._validator.register_temp_dir(str(PROJECTS_ROOT))
        except Exception:
            pass

    @property
    def directory(self) -> str:
        return self._directory

    @property
    def include_markdown(self) -> bool:
        return self._include_markdown

    def set_include_markdown(self, include_markdown: bool) -> None:
        """Toggle markdown inclusion in place; rescans on next access."""
        if include_markdown == self._include_markdown:
            return
        self._include_markdown = include_markdown
        self._scanner = DirectoryScanner(self._directory, include_markdown)
        self._lazy_files = None

    def invalidate(self) -> None:
        self._lazy_files = None

    def register_temp_dir(self, temp_dir: str) -> None:
        self._validator.register_temp_dir(temp_dir)

    def is_in_allowed_temp_dir(self, path: str) -> bool:
        return self._validator.is_file_in_allowed_temp_dir(path)

    def single_file(self) -> SpFile | None:
        return None

    def get_unique_file_key(self) -> SpFileKey | None:
        return None

    def resolve(self, key: SpFileKey) -> str | None:
        if key.startswith(NEW_FILE):
            return None

        directory = Path(self._directory)
        filepath = Path(key)

        # Resolve relative paths against the workspace directory.
        if not filepath.is_absolute():
            filepath = directory / filepath

        if filepath.exists():
            return str(filepath)

        # Fallback: check cloud project sync directories
        # (structured as ~/.sp/projects/{id}/{name}/)
        if not Path(key).is_absolute():
            try:
                from signalpilot._server.files.project_sync import PROJECTS_ROOT

                if PROJECTS_ROOT.exists():
                    for project_dir in PROJECTS_ROOT.glob("*/*"):
                        if not project_dir.is_dir():
                            continue
                        candidate = project_dir / key
                        if candidate.is_file():
                            return str(candidate)
            except Exception:
                pass

        raise file_not_found(key)

    @property
    def files(self) -> list[FileInfo]:
        if self._lazy_files is None:
            try:
                self._lazy_files = self._scanner.scan()
            except HTTPException as e:
                if e.status_code == HTTPStatus.REQUEST_TIMEOUT:
                    LOGGER.warning(
                        "Timeout during file scan, returning partial results"
                    )
                    self._lazy_files = self._scanner.partial_results
                else:
                    raise
        return self._lazy_files
