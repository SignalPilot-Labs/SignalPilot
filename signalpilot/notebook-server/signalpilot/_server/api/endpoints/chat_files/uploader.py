"""Multipart upload of captured scratch files to the gateway.

Bounded concurrency, one retry, and no exception ever leaves this module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from signalpilot import _loggers

if TYPE_CHECKING:
    from collections.abc import Sequence

    from signalpilot._server.api.endpoints.chat_files.capture import (
        CapturedFile,
    )

LOGGER = _loggers.sp_logger()

RUNTIME_FILES_PATH = "/api/chat/runtime-files"
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class UploadOutcome:
    """Result of one upload attempt. `ok` is False when the file was lost."""

    path: str
    ok: bool
    status_code: int | None = None
    unchanged: bool = False
    deleted: bool = False
    retried: bool = False


class RuntimeFileUploader:
    """POST captured files to `/api/chat/runtime-files`."""

    def __init__(
        self,
        *,
        gateway_api_url: str,
        scoped_token: str,
        run_id: str,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = f"{gateway_api_url.rstrip('/')}{RUNTIME_FILES_PATH}"
        self._token = scoped_token
        self.run_id = run_id
        self.concurrency = max(1, int(concurrency))
        self.timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def upload_many(
        self,
        files: Sequence[CapturedFile],
        *,
        reason: str,
        tool_call_id: str | None,
    ) -> list[UploadOutcome]:
        """Upload every file with bounded concurrency. Never raises."""
        if not files:
            return []
        semaphore = asyncio.Semaphore(self.concurrency)

        async def bounded(file: CapturedFile) -> UploadOutcome:
            async with semaphore:
                return await self.upload_one(
                    file, reason=reason, tool_call_id=tool_call_id
                )

        try:
            return list(
                await asyncio.gather(*(bounded(file) for file in files))
            )
        except Exception:
            # upload_one already catches everything. This guard covers a
            # cancelled gather so the stream never sees an error.
            LOGGER.warning(
                "Chat file upload batch failed run_id=%s",
                self.run_id,
                exc_info=True,
            )
            return [UploadOutcome(path=file.path, ok=False) for file in files]

    async def upload_one(
        self,
        file: CapturedFile,
        *,
        reason: str,
        tool_call_id: str | None,
    ) -> UploadOutcome:
        """Upload one file. One retry on a connection error or a 5xx."""
        try:
            return await self._upload_with_retry(
                file, reason=reason, tool_call_id=tool_call_id
            )
        except Exception:
            LOGGER.warning(
                "Chat file upload failed run_id=%s path=%s reason=%s",
                self.run_id,
                file.path,
                reason,
                exc_info=True,
            )
            return UploadOutcome(path=file.path, ok=False, deleted=file.deleted)

    async def _upload_with_retry(
        self,
        file: CapturedFile,
        *,
        reason: str,
        tool_call_id: str | None,
    ) -> UploadOutcome:
        retried = False
        for attempt in (1, 2):
            try:
                response = await self._post(
                    file, reason=reason, tool_call_id=tool_call_id
                )
            except httpx.TransportError as exc:
                if attempt == 1:
                    retried = True
                    continue
                LOGGER.warning(
                    "Chat file upload connection error run_id=%s path=%s "
                    "error_type=%s",
                    self.run_id,
                    file.path,
                    type(exc).__name__,
                )
                return UploadOutcome(
                    path=file.path,
                    ok=False,
                    deleted=file.deleted,
                    retried=True,
                )
            status = int(getattr(response, "status_code", 0) or 0)
            if status >= 500 and attempt == 1:
                retried = True
                continue
            if status in {200, 201}:
                return UploadOutcome(
                    path=file.path,
                    ok=True,
                    status_code=status,
                    unchanged=_is_unchanged(response),
                    deleted=file.deleted,
                    retried=retried,
                )
            LOGGER.warning(
                "Chat file upload rejected run_id=%s path=%s status=%s "
                "detail=%s",
                self.run_id,
                file.path,
                status,
                _safe_detail(response),
            )
            return UploadOutcome(
                path=file.path,
                ok=False,
                status_code=status,
                deleted=file.deleted,
                retried=retried,
            )
        return UploadOutcome(path=file.path, ok=False, deleted=file.deleted)

    async def _post(
        self,
        file: CapturedFile,
        *,
        reason: str,
        tool_call_id: str | None,
    ) -> httpx.Response:
        fields: dict[str, str] = {
            "path": file.path,
            "content_hash": file.content_hash,
            "reason": reason,
        }
        if tool_call_id:
            fields["tool_call_id"] = tool_call_id
        if file.deleted:
            fields["deleted"] = "1"
        # Every field travels as a multipart part, so a delete with no file
        # part is still `multipart/form-data` for the gateway route.
        parts: dict[str, Any] = {
            name: (None, value) for name, value in fields.items()
        }
        if not file.deleted:
            parts["file"] = (
                file.path.rsplit("/", 1)[-1],
                file.data,
                "application/octet-stream",
            )
        async with self._client() as client:
            return await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self._token}"},
                files=parts,
            )


def _is_unchanged(response: Any) -> bool:
    try:
        body = response.json()
    except Exception:
        return False
    return isinstance(body, dict) and bool(body.get("unchanged"))


def _safe_detail(response: Any) -> str:
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    return str(body.get("detail") or "")[:200]
