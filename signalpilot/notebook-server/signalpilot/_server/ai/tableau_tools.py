"""Tableau tools for the standalone chat agent.

Each tool is a thin HTTP client for the gateway's ``/api/tableau/runtime/*``
routes. The gateway owns the Tableau PAT and every Tableau REST and VizQL
Data Service call; the run authenticates with its scoped ``gateway_token``.
Workbook XML never passes through the model: the download tool writes the
``.twb`` into the scratch directory and returns a compact summary, and the
publish tool reads a scratch file and uploads it. The view image tool saves
the PNG under ``artifacts/`` and also returns it as an image block.

Every failure raises ``ValueError`` with the gateway's ``detail`` so the MCP
server marks the tool result as an error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

import httpx

from signalpilot._server.ai.tableau_summary import summarize_twb

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

TABLEAU_TOOL_NAMES = (
    "tableau_search",
    "tableau_get_workbook",
    "tableau_download_workbook",
    "tableau_publish_workbook",
    "tableau_publish_datasource",
    "tableau_datasource_fields",
    "tableau_query_datasource",
    "tableau_view_image",
    "tableau_view_data",
    "tableau_connection_info",
)
TABLEAU_ALLOWED_TOOLS = tuple(
    f"mcp__standalone-chat__{name}" for name in TABLEAU_TOOL_NAMES
)

RUNTIME_PREFIX = "/api/tableau/runtime"
TEXT_LIMIT = 40_000
NOT_ENABLED_MESSAGE = "The Tableau integration is not enabled for this org"
_DEFAULT_TIMEOUT = 120.0
_LONG_TIMEOUT = 600.0
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class TableauGateway:
    """HTTP client for the gateway Tableau runtime routes of one run."""

    def __init__(
        self,
        gateway_url: str,
        gateway_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = gateway_url.rstrip("/")
        self._token = gateway_token
        self._transport = transport

    async def request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send one request; raise ``ValueError`` for every failure."""
        if not self._url or not self._token:
            raise ValueError(
                "This run has no gateway identity, so Tableau cannot be reached."
            )
        async with httpx.AsyncClient(
            base_url=self._url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=httpx.Timeout(timeout),
            transport=self._transport,
        ) as client:
            try:
                response = await client.request(
                    method, f"{RUNTIME_PREFIX}{path}", **kwargs
                )
            except httpx.TimeoutException as exc:
                raise ValueError(
                    f"The Tableau request timed out after {timeout:.0f} s."
                ) from exc
            except httpx.HTTPError as exc:
                raise ValueError(
                    f"The gateway could not be reached for Tableau: {exc}"
                ) from exc
        if response.status_code >= 400:
            raise ValueError(_error_message(response))
        return response

    async def json(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        response = await self.request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                "The gateway Tableau answer is not JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError("The gateway Tableau answer is not an object.")
        return payload


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, dict):
        detail = detail.get("message") or json.dumps(detail)
    elif isinstance(detail, list):
        detail = json.dumps(detail)
    return str(detail or response.text or "").strip()[:500]


def _error_message(response: httpx.Response) -> str:
    detail = _detail(response)
    status = response.status_code
    if status == 403:
        lowered = detail.lower()
        if not detail or any(
            word in lowered
            for word in (
                "integration",
                "capability",
                "not enabled",
                "tableau access",
            )
        ):
            return f"{NOT_ENABLED_MESSAGE}. {detail}".strip()
        return f"Tableau denied access (403): {detail}"
    if status == 401:
        return f"The gateway rejected this run's token (401): {detail or 'no detail'}"
    if status == 404:
        return f"Not found in Tableau (404): {detail or 'no detail'}"
    return f"The Tableau request failed ({status}): {detail or 'no detail'}"


def _ref(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Pass the {what} id or name.")
    if len(text) > 300:
        raise ValueError(f"The {what} reference is too long.")
    return quote(text, safe="")


def slugify(value: str, default: str = "workbook") -> str:
    slug = _SLUG_RE.sub("-", str(value or "").lower()).strip("-")[:60]
    return slug.strip("-") or default


def resolve_scratch_path(scratch: Path, raw: Any) -> Path:
    """Resolve a tool path inside the scratch directory, or raise.

    Relative paths resolve against the scratch. Absolute paths are accepted
    only when they point inside it. Any ``..`` segment is rejected.
    """
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("Pass a file path relative to the scratch directory.")
    candidate = Path(text)
    if ".." in candidate.parts:
        raise ValueError("The path must not contain '..'.")
    root = scratch.resolve()
    target = (
        candidate if candidate.is_absolute() else root / candidate
    ).resolve()
    if not target.is_relative_to(root):
        raise ValueError("The path must stay inside the scratch directory.")
    return target


def _relative(scratch: Path, target: Path) -> str:
    return target.relative_to(scratch.resolve()).as_posix()


def _text_result(payload: Any) -> list[Any]:
    from mcp.types import TextContent

    text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, default=str)
    )
    if len(text) > TEXT_LIMIT:
        omitted = len(text) - TEXT_LIMIT
        text = (
            text[:TEXT_LIMIT]
            + f"\n[truncated: {omitted} more characters were omitted. "
            "Narrow the request, for example with a lower limit.]"
        )
    return [TextContent(type="text", text=text)]


def _optional(arguments: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {
        key: arguments[key]
        for key in keys
        if arguments.get(key) is not None and arguments.get(key) != ""
    }


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def build_tableau_handlers(
    *,
    scratch_directory: Path | None,
    gateway_url: str,
    gateway_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Callable[[dict[str, Any]], Awaitable[list[Any]]]]:
    """Map each Tableau tool name to its async handler for one run."""
    gateway = TableauGateway(gateway_url, gateway_token, transport)

    def scratch() -> Path:
        if scratch_directory is None:
            raise ValueError(
                "The scratch directory is unavailable in this run, so "
                "Tableau files cannot be read or written."
            )
        return scratch_directory

    async def search(arguments: dict[str, Any]) -> list[Any]:
        params = {
            "q": str(arguments.get("query") or ""),
            "kind": str(arguments.get("kind") or "all"),
            "limit": _bounded_int(arguments.get("limit"), 25, 1, 100),
        }
        return _text_result(
            await gateway.json("GET", "/search", params=params)
        )

    async def get_workbook(arguments: dict[str, Any]) -> list[Any]:
        ref = _ref(arguments.get("workbook"), "workbook")
        return _text_result(await gateway.json("GET", f"/workbooks/{ref}"))

    async def download_workbook(arguments: dict[str, Any]) -> list[Any]:
        root = scratch()
        raw_ref = str(arguments.get("workbook") or "").strip()
        ref = _ref(raw_ref, "workbook")
        target = None
        if arguments.get("path"):
            target = resolve_scratch_path(root, arguments["path"])
            if target.suffix.lower() != ".twb":
                raise ValueError("The download path must end with .twb.")
        response = await gateway.request(
            "GET", f"/workbooks/{ref}/content", timeout=_LONG_TIMEOUT
        )
        name = unquote(response.headers.get("X-Tableau-Workbook-Name") or "")
        name = name or raw_ref
        workbook_id = response.headers.get("X-Tableau-Workbook-Id") or ""
        if target is None:
            target = resolve_scratch_path(root, f"tableau/{slugify(name)}.twb")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return _text_result(
            {
                "path": _relative(root, target),
                "absolute_path": str(target),
                "bytes": len(response.content),
                "workbook_id": workbook_id,
                "name": name,
                "summary": summarize_twb(target),
            }
        )

    async def publish_workbook(arguments: dict[str, Any]) -> list[Any]:
        root = scratch()
        source = resolve_scratch_path(root, arguments.get("path"))
        if source.suffix.lower() not in (".twb", ".twbx"):
            raise ValueError("Publish a .twb or .twbx file.")
        if not source.is_file():
            raise ValueError(f"No file at {_relative(root, source)}.")
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ValueError("Pass the workbook name to publish as.")
        form = {
            "name": name,
            "overwrite": _flag(arguments.get("overwrite"), True),
            "show_tabs": _flag(arguments.get("show_tabs"), True),
            **{
                key: str(value)
                for key, value in _optional(
                    arguments, "project", "connection", "description"
                ).items()
            },
        }
        content_type = (
            "application/xml"
            if source.suffix.lower() == ".twb"
            else "application/octet-stream"
        )
        files = {"file": (source.name, source.read_bytes(), content_type)}
        return _text_result(
            await gateway.json(
                "POST",
                "/workbooks",
                data=form,
                files=files,
                timeout=_LONG_TIMEOUT,
            )
        )

    async def publish_datasource(arguments: dict[str, Any]) -> list[Any]:
        has_table = bool(arguments.get("table"))
        has_sql = bool(arguments.get("sql"))
        if has_table == has_sql:
            raise ValueError("Pass exactly one of table or sql.")
        for key in ("name", "connection"):
            if not str(arguments.get(key) or "").strip():
                raise ValueError(f"Pass the {key}.")
        body: dict[str, Any] = {
            **_optional(
                arguments,
                "name",
                "connection",
                "database",
                "schema",
                "table",
                "sql",
                "project",
                "description",
            ),
            "overwrite": bool(
                True
                if arguments.get("overwrite") is None
                else arguments.get("overwrite")
            ),
        }
        return _text_result(
            await gateway.json(
                "POST", "/datasources", json=body, timeout=_LONG_TIMEOUT
            )
        )

    async def datasource_fields(arguments: dict[str, Any]) -> list[Any]:
        ref = _ref(arguments.get("datasource"), "data source")
        return _text_result(
            await gateway.json("GET", f"/datasources/{ref}/fields")
        )

    async def query_datasource(arguments: dict[str, Any]) -> list[Any]:
        ref = _ref(arguments.get("datasource"), "data source")
        fields = arguments.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError("Pass at least one field object in fields.")
        body: dict[str, Any] = {
            "fields": fields,
            "limit": _bounded_int(arguments.get("limit"), 500, 1, 5000),
        }
        if isinstance(arguments.get("filters"), list):
            body["filters"] = arguments["filters"]
        return _text_result(
            await gateway.json(
                "POST",
                f"/datasources/{ref}/query",
                json=body,
                timeout=_LONG_TIMEOUT,
            )
        )

    async def view_image(arguments: dict[str, Any]) -> list[Any]:
        from mcp.types import TextContent

        root = scratch()
        raw_ref = str(arguments.get("view") or "").strip()
        ref = _ref(raw_ref, "view")
        params: dict[str, Any] = {"max_age": 1}
        for key in ("width", "height"):
            if arguments.get(key) is not None:
                params[key] = _bounded_int(arguments[key], 1600, 200, 4000)
        response = await gateway.request(
            "GET", f"/views/{ref}/image", params=params, timeout=_LONG_TIMEOUT
        )
        png = response.content
        slug = slugify(str(arguments.get("name") or raw_ref), "view")
        target = resolve_scratch_path(root, f"artifacts/tableau-{slug}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png)
        status: dict[str, Any] = {
            "view": raw_ref,
            "path": _relative(root, target),
            "bytes": len(png),
        }
        # Return the path, not the image: the file is on this machine, and the
        # agent opens it with the Read tool when it needs to look at it. An
        # inline image can exceed the SDK's per-message JSON limit.
        status["next"] = f"Open {status['path']} with the Read tool to look at the render."
        return [TextContent(type="text", text=json.dumps(status))]

    async def view_data(arguments: dict[str, Any]) -> list[Any]:
        raw_ref = str(arguments.get("view") or "").strip()
        ref = _ref(raw_ref, "view")
        max_rows = _bounded_int(arguments.get("max_rows"), 200, 1, 10_000)
        response = await gateway.request(
            "GET",
            f"/views/{ref}/data",
            params={"max_rows": max_rows},
            timeout=_LONG_TIMEOUT,
        )
        return _text_result(response.text)

    async def connection_info(arguments: dict[str, Any]) -> list[Any]:
        ref = _ref(arguments.get("connection"), "connection")
        return _text_result(await gateway.json("GET", f"/connections/{ref}"))

    return {
        "tableau_search": search,
        "tableau_get_workbook": get_workbook,
        "tableau_download_workbook": download_workbook,
        "tableau_publish_workbook": publish_workbook,
        "tableau_publish_datasource": publish_datasource,
        "tableau_datasource_fields": datasource_fields,
        "tableau_query_datasource": query_datasource,
        "tableau_view_image": view_image,
        "tableau_view_data": view_data,
        "tableau_connection_info": connection_info,
    }


def _flag(value: Any, default: bool) -> str:
    """Multipart form boolean as the gateway reads it: "true" or "false"."""
    return "true" if (default if value is None else bool(value)) else "false"
