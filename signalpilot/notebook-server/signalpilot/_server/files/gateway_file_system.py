"""S3-native file system proxied through the gateway Workspace Files API.

Notebook Runtime v2 storage plane: files are pulled on demand and every
mutation is a write-through commit that creates a new revision. There is no
local working tree — the browser holds unsaved buffers, S3 holds the saved
working copy, and this class is the seam between them.

Contract (gateway/api/workspace_files.py — the source of truth):

    GET/PUT/DELETE /api/workspace-projects/{project_id}/files/{path}?branch=
    POST .../files:list|files:search|files:copy|files:move   {branch, ...}
    POST .../files:batch  {branch, base_revision, upserts, deletes, message}

The branch always travels as a query/body parameter (it may contain '/'),
never a path segment. A 409 from files:batch is a compare-and-swap conflict
(another writer committed first) and surfaces as
:class:`GatewayConflictError`.
"""

from __future__ import annotations

import base64
import mimetypes
import posixpath
from typing import Any, Literal

import httpx

from signalpilot import _loggers
from signalpilot._server.files.file_system import FileSystem
from signalpilot._server.models.files import FileDetailsResponse, FileInfo

LOGGER = _loggers.sp_logger()

NOTEBOOK_EXTENSIONS = {".py", ".md", ".qmd"}
IGNORE_NAMES = {"__pycache__", ".git", "node_modules", ".venv", "target"}

_DIR_PLACEHOLDER = ".gitkeep"


class GatewayFileSystemError(OSError):
    """A workspace-files call failed at the gateway."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GatewayConflictError(GatewayFileSystemError):
    """Compare-and-swap conflict: another writer committed a newer revision."""


def _error_from_response(resp: httpx.Response) -> GatewayFileSystemError:
    detail: Any
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = resp.text[:500]
    message = f"Gateway workspace files request failed ({resp.status_code}): {detail}"
    if resp.status_code == 409:
        return GatewayConflictError(message, status_code=409)
    return GatewayFileSystemError(message, status_code=resp.status_code)


class GatewayFileSystem(FileSystem):
    """FileSystem over the gateway Workspace Files API (S3 storage plane)."""

    def __init__(
        self,
        *,
        gateway_url: str,
        token: str,
        project_id: str,
        branch: str = "main",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        from signalpilot._utils.localhost import fix_localhost_url

        base = fix_localhost_url(gateway_url).rstrip("/")
        self._project_id = project_id
        self._branch = branch
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=f"{base}/api/workspace-projects/{project_id}",
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        # Manifest cache keyed by revision: listings dominate UI traffic and
        # the manifest only changes when a commit lands, so a cheap
        # head-revision probe replaces refetching thousands of entries per
        # directory click.
        self._entries_cache: tuple[int, list[dict[str, Any]]] | None = None

    @property
    def branch(self) -> str:
        return self._branch

    @property
    def project_id(self) -> str:
        return self._project_id

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _rel(path: str) -> str:
        rel = posixpath.normpath(path.replace("\\", "/").strip("/"))
        if rel in (".", ""):
            return ""
        if rel.startswith(".."):
            raise ValueError(f"Path escapes the workspace: {path!r}")
        return rel

    def _get_file(self, rel: str) -> httpx.Response:
        return self._client.get(f"/files/{rel}", params={"branch": self._branch})

    # ── Raw byte access (session materialization / write-through) ────

    def read_bytes(self, path: str) -> bytes | None:
        """Fetch one file's exact bytes; None when it does not exist."""
        resp = self._get_file(self._rel(path))
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise _error_from_response(resp)
        return resp.content

    @staticmethod
    def _reject_if_read_only() -> None:
        from signalpilot._server.files.workspace import is_read_only_workspace

        if is_read_only_workspace():
            raise GatewayFileSystemError(
                "This session is read-only; changes are not saved.",
                status_code=403,
            )

    def write_bytes(self, path: str, content: bytes) -> None:
        """Write-through one file's exact bytes as a new revision."""
        self._put_file(self._rel(path), content)
        self._entries_cache = None

    def write_many(self, files: dict[str, bytes], *, message: str | None = None) -> int:
        """Write-through several files as ONE revision (batch commit)."""
        import base64

        upserts = [
            {
                "path": self._rel(path),
                "content_b64": base64.b64encode(content).decode(),
            }
            for path, content in files.items()
        ]
        return self._batch(upserts=upserts, message=message)

    def _put_file(self, rel: str, content: bytes) -> None:
        self._reject_if_read_only()
        resp = self._client.put(
            f"/files/{rel}",
            params={"branch": self._branch},
            content=content,
            headers={
                "Content-Type": mimetypes.guess_type(rel)[0]
                or "application/octet-stream"
            },
        )
        if resp.status_code != 200:
            raise _error_from_response(resp)
        self._entries_cache = None

    def _post(self, op: str, body: dict[str, Any]) -> httpx.Response:
        return self._client.post(op, json={"branch": self._branch, **body})

    def _head_revision(self) -> int | None:
        resp = self._client.get(
            "/revisions", params={"branch": self._branch, "limit": 1}
        )
        if resp.status_code != 200:
            raise _error_from_response(resp)
        revisions = resp.json().get("revisions", [])
        return int(revisions[0]["revision"]) if revisions else None

    def _list_entries(self, prefix: str = "") -> list[dict[str, Any]]:
        head = self._head_revision()
        if head is None:
            return []
        if self._entries_cache is None or self._entries_cache[0] != head:
            resp = self._post("/files:list", {})
            if resp.status_code != 200:
                raise _error_from_response(resp)
            self._entries_cache = (head, list(resp.json().get("files", [])))
        entries = self._entries_cache[1]
        if not prefix:
            return list(entries)
        wanted = prefix.rstrip("/") + "/"
        return [e for e in entries if str(e["path"]).startswith(wanted)]

    def _batch(
        self,
        *,
        upserts: list[dict[str, Any]] | None = None,
        deletes: list[str] | None = None,
        message: str | None = None,
    ) -> int:
        self._reject_if_read_only()
        # base_revision is a CAS token: None means "first commit on the
        # branch", so mutations must name the current head. One retry absorbs
        # the (lease-guarded, therefore rare) race with a concurrent commit.
        last: httpx.Response | None = None
        for _ in range(2):
            resp = self._post(
                "/files:batch",
                {
                    "base_revision": self._head_revision(),
                    "upserts": upserts or [],
                    "deletes": deletes or [],
                    "message": message,
                },
            )
            if resp.status_code == 409:
                last = resp
                continue
            if resp.status_code != 200:
                raise _error_from_response(resp)
            self._entries_cache = None
            return int(resp.json()["revision"])
        raise _error_from_response(last)

    def _make_file_info(
        self,
        rel: str,
        *,
        is_directory: bool = False,
        last_modified: float | None = None,
    ) -> FileInfo:
        name = rel.rstrip("/").rsplit("/", 1)[-1] if rel else ""
        ext = posixpath.splitext(name)[1].lower()
        return FileInfo(
            id=rel,
            path=rel,
            name=name,
            is_directory=is_directory,
            is_sp_file=not is_directory and ext in NOTEBOOK_EXTENSIONS,
            last_modified=last_modified,
        )

    def _is_directory(self, rel: str) -> bool:
        return bool(rel == "" or self._list_entries(rel))

    # ── FileSystem interface ─────────────────────────────────────────

    def get_root(self) -> str:
        return ""

    def list_files(self, path: str) -> list[FileInfo]:
        prefix = self._rel(path)
        try:
            entries = self._list_entries(prefix)
        except GatewayFileSystemError as exc:
            LOGGER.error("Gateway list_files failed: %s", exc)
            return []

        strip = f"{prefix}/" if prefix else ""
        dirs: dict[str, float | None] = {}
        files: list[FileInfo] = []
        for entry in entries:
            rel = str(entry.get("path", ""))
            if strip:
                if not rel.startswith(strip):
                    continue
                rel = rel[len(strip):]
            if not rel:
                continue
            name = rel.split("/", 1)[0]
            if name in IGNORE_NAMES:
                continue
            child = f"{prefix}/{name}" if prefix else name
            mtime = entry.get("mtime") or None
            if "/" in rel:
                prev = dirs.get(child)
                if child not in dirs or (mtime and mtime > (prev or 0)):
                    dirs[child] = mtime
            elif name != _DIR_PLACEHOLDER:
                files.append(self._make_file_info(child, last_modified=mtime))

        dir_infos = [
            self._make_file_info(d, is_directory=True, last_modified=dirs[d])
            for d in sorted(dirs)
        ]
        files.sort(key=lambda info: info.name.lower())
        return dir_infos + files

    def get_details(
        self,
        path: str,
        encoding: str | None = None,
        contents: str | None = None,
    ) -> FileDetailsResponse:
        rel = self._rel(path)
        if not rel:
            return FileDetailsResponse(
                file=self._make_file_info("", is_directory=True),
                contents=None,
            )
        if contents is not None:
            return FileDetailsResponse(
                file=self._make_file_info(rel),
                contents=contents,
                mime_type=mimetypes.guess_type(rel)[0],
            )

        resp = self._get_file(rel)
        if resp.status_code == 404:
            if self._is_directory(rel):
                return FileDetailsResponse(
                    file=self._make_file_info(rel, is_directory=True),
                    contents=None,
                )
            raise FileNotFoundError(f"File not found: {rel}")
        if resp.status_code != 200:
            raise _error_from_response(resp)

        raw = resp.content
        is_base64 = False
        try:
            text = raw.decode(encoding or "utf-8")
        except UnicodeDecodeError:
            text = base64.b64encode(raw).decode("utf-8")
            is_base64 = True
        return FileDetailsResponse(
            file=self._make_file_info(rel),
            contents=text,
            mime_type=mimetypes.guess_type(rel)[0] or "text/plain",
            is_base64=is_base64,
        )

    def open_file(self, path: str, encoding: str | None = None) -> str | bytes:
        rel = self._rel(path)
        resp = self._get_file(rel)
        if resp.status_code == 404:
            raise FileNotFoundError(f"File not found: {rel}")
        if resp.status_code != 200:
            raise _error_from_response(resp)
        try:
            return resp.content.decode(encoding or "utf-8")
        except UnicodeDecodeError:
            return resp.content

    def create_file_or_directory(
        self,
        path: str,
        file_type: Literal["file", "directory", "notebook"],
        name: str,
        contents: bytes | None,
    ) -> FileInfo:
        if not name.strip():
            raise ValueError("Cannot create file or directory with empty name")
        if (
            "/" in name
            or "\\" in name
            or "\x00" in name
            or name in (".", "..")
        ):
            raise ValueError(
                f"Invalid name {name!r}: must not contain path separators "
                "or refer to a parent directory"
            )
        parent = self._rel(path)
        rel = f"{parent}/{name}" if parent else name

        if file_type == "directory":
            # The manifest has no empty directories; commit a placeholder.
            self._put_file(f"{rel}/{_DIR_PLACEHOLDER}", b"")
            return self._make_file_info(rel, is_directory=True)

        body = contents or b""
        if file_type == "notebook" and not contents:
            from signalpilot._convert.converters import SpConvert
            from signalpilot._session.notebook.file_manager import (
                AppFileManager,
            )

            ir = AppFileManager(None).app.to_ir()
            converter = SpConvert.from_ir(ir)
            if posixpath.splitext(name)[1].lower() in (".md", ".qmd"):
                code = converter.to_markdown(name)
            else:
                code = converter.to_py()
            body = code.encode("utf-8")

        self._put_file(rel, body)
        return self._make_file_info(rel)

    def delete_file_or_directory(self, path: str) -> bool:
        rel = self._rel(path)
        if not rel:
            return False
        resp = self._client.delete(
            f"/files/{rel}", params={"branch": self._branch}
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            # Not a file — delete every file under the prefix in one commit.
            paths = [str(e["path"]) for e in self._list_entries(rel)]
            if not paths:
                return False
            self._batch(deletes=paths, message=f"delete {rel}/")
            return True
        raise _error_from_response(resp)

    def copy_file_or_directory(self, path: str, new_path: str) -> FileInfo:
        return self._copy_or_move(path, new_path, op="/files:copy")

    def move_file_or_directory(self, path: str, new_path: str) -> FileInfo:
        return self._copy_or_move(path, new_path, op="/files:move")

    def _copy_or_move(self, path: str, new_path: str, *, op: str) -> FileInfo:
        source = self._rel(path)
        destination = self._rel(new_path)
        resp = self._post(op, {"source": source, "destination": destination})
        if resp.status_code == 404 and self._is_directory(source):
            # Directory copy/move: one batch of reference upserts (+ deletes).
            entries = self._list_entries(source)
            upserts = [
                {
                    "path": f"{destination}/{str(e['path'])[len(source) + 1:]}",
                    "sha256": e["sha256"],
                    "size": e["size"],
                    "mode": e.get("mode", 0o644),
                    "mtime": e.get("mtime"),
                }
                for e in entries
            ]
            deletes = (
                [str(e["path"]) for e in entries]
                if op == "/files:move"
                else []
            )
            self._batch(
                upserts=upserts,
                deletes=deletes,
                message=f"{op.rsplit(':', 1)[-1]} {source} -> {destination}",
            )
            return self._make_file_info(destination, is_directory=True)
        if resp.status_code != 200:
            raise _error_from_response(resp)
        return self._make_file_info(destination)

    def update_file(self, path: str, contents: str) -> FileInfo:
        # Write-through save: a single-file PUT is a new revision. It either
        # committed (durable) or raised (the caller sees the failure).
        rel = self._rel(path)
        self._put_file(rel, contents.encode("utf-8"))
        return self._make_file_info(rel)

    def search(
        self,
        query: str,
        *,
        path: str | None = None,
        include_directories: bool = True,
        include_files: bool = True,
        depth: int = 3,
        limit: int = 100,
    ) -> list[FileInfo]:
        del depth  # manifest search is flat; depth is a disk-walk concept
        if not query.strip():
            return []
        resp = self._post("/files:search", {"query": query})
        if resp.status_code != 200:
            LOGGER.error(
                "Gateway search failed: %s %s", resp.status_code, resp.text[:200]
            )
            return []

        prefix = f"{self._rel(path)}/" if path and self._rel(path) else ""
        needle = query.lower()
        results: list[FileInfo] = []
        seen_dirs: set[str] = set()
        for entry in resp.json().get("files", []):
            rel = str(entry.get("path", ""))
            if prefix and not rel.startswith(prefix):
                continue
            if include_files and needle in rel.rsplit("/", 1)[-1].lower():
                results.append(
                    self._make_file_info(
                        rel, last_modified=entry.get("mtime") or None
                    )
                )
            if include_directories:
                parts = rel.split("/")[:-1]
                for i, part in enumerate(parts):
                    if needle in part.lower():
                        dir_path = "/".join(parts[: i + 1])
                        if dir_path not in seen_dirs:
                            seen_dirs.add(dir_path)
                            results.append(
                                self._make_file_info(
                                    dir_path, is_directory=True
                                )
                            )
        results.sort(
            key=lambda info: (
                0
                if info.name.lower() == needle
                else 1
                if info.name.lower().startswith(needle)
                else 2,
                info.name,
            )
        )
        return results[:limit]

    # ── Branch operations (S3 has every branch) ──────────────────────

    def fork_branch(self, new_branch: str, *, message: str | None = None) -> int:
        """Create ``new_branch`` from this filesystem's branch head.

        Blobs are content-addressed per project, so the fork is a single
        batch commit of reference upserts — no bytes move.
        """
        entries = self._list_entries()
        if not entries:
            raise GatewayFileSystemError(
                f"Branch {self._branch!r} has no files to fork from"
            )
        fork = GatewayFileSystem.__new__(GatewayFileSystem)
        fork._project_id = self._project_id
        fork._branch = new_branch
        fork._client = self._client
        return fork._batch(
            upserts=[
                {
                    "path": e["path"],
                    "sha256": e["sha256"],
                    "size": e["size"],
                    "mode": e.get("mode", 0o644),
                    "mtime": e.get("mtime"),
                }
                for e in entries
            ],
            message=message or f"fork from {self._branch}",
        )
