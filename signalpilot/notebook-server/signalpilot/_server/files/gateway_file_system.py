# Copyright 2026 SignalPilot. All rights reserved.
"""
Cloud file system backed by the SignalPilot Gateway workspace-projects API.

All file operations are proxied to the gateway's S3-backed storage.
Paths are project-relative (e.g., "models/staging/stg_orders.sql").
"""
from __future__ import annotations

import mimetypes
import os
from typing import Any, Literal

import httpx

from signalpilot import _loggers
from signalpilot._server.files.file_system import FileSystem
from signalpilot._server.models.files import FileDetailsResponse, FileInfo

LOGGER = _loggers.sp_logger()

NOTEBOOK_EXTENSIONS = {".py", ".md", ".qmd"}
IGNORE_NAMES = {"__pycache__", ".git", "node_modules", ".venv", "target"}


class GatewayFileSystem(FileSystem):
    """FileSystem implementation backed by the SignalPilot Gateway API."""

    def __init__(
        self,
        gateway_url: str,
        api_key: str,
        project_id: str,
        branch: str = "main",
    ) -> None:
        from signalpilot._utils.localhost import fix_localhost_url
        self._gateway_url = fix_localhost_url(gateway_url).rstrip("/")
        self._api_key = api_key
        self._project_id = project_id
        self._branch = branch
        self._base = f"{self._gateway_url}/api/workspace-projects/{project_id}/branches/{branch}"
        jwt = os.environ.get("SP_SESSION_JWT", "")
        if jwt:
            self._headers = {"Authorization": f"Bearer {jwt}"}
        elif api_key:
            self._headers = {"X-API-Key": api_key}
        else:
            self._headers = {}

    # ── Helpers ──────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        content: bytes | str | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = f"{self._base}/{path}"
        hdrs = {**self._headers}
        if headers:
            hdrs.update(headers)
        return httpx.request(
            method,
            url,
            json=json,
            content=content,
            params=params,
            headers=hdrs,
            timeout=30.0,
        )

    def _strip_s3_prefix(self, key: str) -> str:
        """Strip the projects/<id>/ prefix from an S3 key."""
        prefix = f"projects/{self._project_id}/"
        if key.startswith(prefix):
            return key[len(prefix):]
        return key

    def _make_file_info(
        self,
        relative_path: str,
        *,
        is_directory: bool = False,
        size: int = 0,
        last_modified: float | None = None,
    ) -> FileInfo:
        name = relative_path.rstrip("/").rsplit("/", 1)[-1] if "/" in relative_path else relative_path
        ext = os.path.splitext(name)[1].lower()
        is_sp = ext in NOTEBOOK_EXTENSIONS and not is_directory
        return FileInfo(
            id=relative_path,
            path=relative_path,
            name=name,
            is_directory=is_directory,
            is_sp_file=is_sp,
            last_modified=last_modified,
        )

    # ── FileSystem interface ─────────────────────────────────────────

    def get_root(self) -> str:
        return ""

    def list_files(self, path: str) -> list[FileInfo]:
        prefix = path.strip("/")
        params = {}
        if prefix:
            params["prefix"] = prefix + "/"

        resp = self._request("GET", "files", params=params)
        if resp.status_code != 200:
            LOGGER.error(f"Gateway list_files failed: {resp.status_code} {resp.text}")
            return []

        data = resp.json()
        raw_files: list[dict[str, Any]] = data.get("files", [])

        # Build immediate children from flat file list
        dirs: dict[str, float] = {}
        files: list[FileInfo] = []
        strip_prefix = (prefix + "/") if prefix else ""

        for f in raw_files:
            rel = self._strip_s3_prefix(f["key"])
            if strip_prefix and rel.startswith(strip_prefix):
                rel = rel[len(strip_prefix):]
            elif strip_prefix:
                continue

            if not rel:
                continue

            name = rel.split("/")[0]
            if name in IGNORE_NAMES:
                continue

            if "/" in rel:
                # Nested item → this is a subdirectory
                dir_path = f"{prefix}/{name}" if prefix else name
                ts = f.get("last_modified")
                if dir_path not in dirs or (ts and ts > (dirs[dir_path] or 0)):
                    dirs[dir_path] = ts
            else:
                file_path = f"{prefix}/{rel}" if prefix else rel
                files.append(self._make_file_info(
                    file_path,
                    size=f.get("size", 0),
                    last_modified=f.get("last_modified"),
                ))

        dir_infos = [
            self._make_file_info(d, is_directory=True, last_modified=dirs[d])
            for d in sorted(dirs)
        ]
        files.sort(key=lambda fi: fi.name.lower())
        return dir_infos + files

    def get_details(
        self,
        path: str,
        encoding: str | None = None,
        contents: str | None = None,
    ) -> FileDetailsResponse:
        rel = path.strip("/")
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

        resp = self._request("GET", f"files/{rel}")
        if resp.status_code == 404:
            raise FileNotFoundError(f"File not found: {rel}")
        resp.raise_for_status()

        text = resp.text
        mime = mimetypes.guess_type(rel)[0] or "text/plain"
        return FileDetailsResponse(
            file=self._make_file_info(rel, size=len(text)),
            contents=text,
            mime_type=mime,
        )

    def open_file(self, path: str, encoding: str | None = None) -> str | bytes:
        rel = path.strip("/")
        resp = self._request("GET", f"files/{rel}")
        resp.raise_for_status()
        return resp.text

    def create_file_or_directory(
        self,
        path: str,
        file_type: Literal["file", "directory"],
        name: str,
        contents: bytes | None,
    ) -> FileInfo:
        parent = path.strip("/")
        new_path = f"{parent}/{name}" if parent else name

        if file_type == "directory":
            # S3 has no real directories; create a placeholder
            self._request(
                "PUT",
                f"files/{new_path}/.gitkeep",
                content=b"",
                headers={"Content-Type": "text/plain"},
            )
            return self._make_file_info(new_path, is_directory=True)

        body = contents or b""
        ext = os.path.splitext(name)[1].lower()
        ct = {
            ".sql": "text/sql",
            ".yml": "text/yaml",
            ".yaml": "text/yaml",
            ".py": "text/x-python",
            ".json": "application/json",
            ".csv": "text/csv",
        }.get(ext, "text/plain")

        resp = self._request(
            "PUT",
            f"files/{new_path}",
            content=body,
            headers={"Content-Type": ct},
        )
        resp.raise_for_status()
        return self._make_file_info(new_path, size=len(body))

    def delete_file_or_directory(self, path: str) -> bool:
        rel = path.strip("/")
        resp = self._request("DELETE", f"files/{rel}")
        return resp.status_code == 204

    def copy_file_or_directory(self, path: str, new_path: str) -> FileInfo:
        resp = self._request("POST", "files:copy", json={
            "source": path.strip("/"),
            "destination": new_path.strip("/"),
        })
        resp.raise_for_status()
        return self._make_file_info(new_path.strip("/"))

    def move_file_or_directory(self, path: str, new_path: str) -> FileInfo:
        resp = self._request("POST", "files:move", json={
            "source": path.strip("/"),
            "destination": new_path.strip("/"),
        })
        resp.raise_for_status()
        return self._make_file_info(new_path.strip("/"))

    def update_file(self, path: str, contents: str) -> FileInfo:
        rel = path.strip("/")
        ext = os.path.splitext(rel)[1].lower()
        ct = {
            ".sql": "text/sql",
            ".yml": "text/yaml",
            ".yaml": "text/yaml",
            ".py": "text/x-python",
            ".json": "application/json",
            ".csv": "text/csv",
        }.get(ext, "text/plain")

        resp = self._request(
            "PUT",
            f"files/{rel}",
            content=contents.encode("utf-8"),
            headers={"Content-Type": ct},
        )
        resp.raise_for_status()
        return self._make_file_info(rel, size=len(contents))

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
        resp = self._request("POST", "files:search", json={
            "q": query,
            "max_results": limit,
        })
        if resp.status_code != 200:
            return []

        results: list[FileInfo] = []
        for item in resp.json().get("results", []):
            rel = item.get("key", "")
            is_dir = rel.endswith("/")
            if is_dir and not include_directories:
                continue
            if not is_dir and not include_files:
                continue
            results.append(self._make_file_info(
                rel.rstrip("/"),
                is_directory=is_dir,
                size=item.get("size", 0),
                last_modified=item.get("last_modified"),
            ))
        return results[:limit]
