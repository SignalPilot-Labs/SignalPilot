from __future__ import annotations

import msgspec

from signalpilot._server.models.files import FileInfo
from signalpilot._tutorials import Tutorial  # type: ignore
from signalpilot._types.ids import SessionId


class SpFile(msgspec.Struct, rename="camel"):
    # Name of the file
    name: str
    # Absolute path to the file
    path: str
    # Last modified time of the file
    last_modified: float | None = None
    # Session id
    session_id: SessionId | None = None
    # Session initialization id
    # This is the ID for when the session was initialized
    initialization_id: str | None = None


class RecentFilesResponse(msgspec.Struct, rename="camel"):
    files: list[SpFile]


class RunningNotebooksResponse(msgspec.Struct, rename="camel"):
    files: list[SpFile]


class OpenTutorialRequest(msgspec.Struct, rename="camel"):
    tutorial_id: Tutorial


class WorkspaceFilesRequest(msgspec.Struct, rename="camel"):
    include_markdown: bool = False


class WorkspaceFilesResponse(msgspec.Struct, rename="camel"):
    root: str
    files: list[FileInfo]
    # Indicates if limit was reached
    has_more: bool = False
    # Total files found
    file_count: int = 0


class ShutdownSessionRequest(msgspec.Struct, rename="camel"):
    session_id: SessionId
