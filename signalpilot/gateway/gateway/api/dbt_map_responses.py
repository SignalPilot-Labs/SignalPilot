"""Response helpers for the dbt-map routes: ETags, conditional GETs, gzip bodies.

Every dbt-map GET carries a weak ETag derived from the immutable graph_key
(or revision) plus the row's updated_at, honors If-None-Match with 304, and
sets `Cache-Control: private, max-age=0, must-revalidate`. The security
headers middleware leaves this path's Cache-Control alone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import Request, Response
from pydantic import BaseModel

CACHE_CONTROL = "private, max-age=0, must-revalidate"
_JSON_SEPARATORS = (",", ":")


def etag_for_row(row) -> str:
    if row is None:
        return 'W/"none"'
    stamp = datetime.fromtimestamp(float(row.updated_at or 0), tz=UTC).isoformat()
    ident = row.graph_key or f"rev{row.revision}"
    return f'W/"{ident}-{stamp}"'


def _strip_weak(tag: str) -> str:
    return tag.strip().removeprefix("W/")


def etag_matches(request: Request, etag: str) -> bool:
    header = request.headers.get("if-none-match")
    if not header:
        return False
    if header.strip() == "*":
        return True
    wanted = _strip_weak(etag)
    return any(_strip_weak(tag) == wanted for tag in header.split(","))


def accepts_gzip(request: Request) -> bool:
    header = request.headers.get("accept-encoding", "")
    for part in header.split(","):
        token, _, params = part.strip().partition(";")
        if token.strip().lower() != "gzip":
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        return quality > 0
    return False


def _base_headers(etag: str) -> dict[str, str]:
    return {"ETag": etag, "Cache-Control": CACHE_CONTROL, "Vary": "Accept-Encoding"}


def not_modified(etag: str) -> Response:
    return Response(status_code=304, headers=_base_headers(etag))


def json_bytes_response(body: bytes, etag: str, *, gzip_body: bytes | None = None) -> Response:
    """JSON bytes with caching headers; `gzip_body` swaps in the compressed form."""
    headers = _base_headers(etag)
    if gzip_body is not None:
        headers["Content-Encoding"] = "gzip"
        body = gzip_body
    return Response(content=body, media_type="application/json", headers=headers)


def json_response(payload, etag: str) -> Response:
    if isinstance(payload, BaseModel):
        body = payload.model_dump_json().encode("utf-8")
    else:
        body = json.dumps(payload, separators=_JSON_SEPARATORS, default=str).encode("utf-8")
    return json_bytes_response(body, etag)


def envelope_prefix(status: str, map_info: BaseModel) -> bytes:
    """`{"status":...,"map":{...},"graph":` so the raw graph JSON can be appended."""
    return (
        b'{"status":'
        + json.dumps(status).encode("utf-8")
        + b',"map":'
        + map_info.model_dump_json().encode("utf-8")
        + b',"graph":'
    )
