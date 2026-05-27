# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from starlette.authentication import has_required_scope, requires
from starlette.exceptions import HTTPException
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.staticfiles import StaticFiles

from signalpilot import _loggers
from signalpilot._config.manager import get_default_config_manager
from signalpilot._config.settings import GLOBAL_SETTINGS
from signalpilot._output.utils import uri_decode_component
from signalpilot._runtime.virtual_file import (
    EMPTY_VIRTUAL_FILE,
    read_virtual_file_chunked,
)
from signalpilot._server.api.auth import TOKEN_QUERY_PARAM
from signalpilot._server.api.deps import AppState
from signalpilot._server.files.path_validator import PathValidator
from signalpilot._server.router import APIRouter
from signalpilot._utils.paths import (
    normalize_path,
    sp_package_path,
)

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

# Router for serving static assets
router = APIRouter()

# Root directory for static assets
root = normalize_path(sp_package_path() / "_static")

server_config = (
    get_default_config_manager(current_path=None)
    .get_config()
    .get("server", {})
)

assets_dir = root / "assets"
follow_symlinks = server_config.get("follow_symlink", False)


def _missing_index_html_detail() -> str:
    repo_root = sp_package_path().parent
    if (repo_root / "frontend").exists() and (
        repo_root / "pyproject.toml"
    ).exists():
        return (
            "index.html not found. Did you run `make fe`? "
            "Restart sp after building."
        )
    return "index.html not found and no asset_url configured"


def _has_symlinks(directory: Path) -> bool:
    """Check if a directory is a symlink or contains symlinked files."""
    if directory.is_symlink():
        return True
    try:
        for i, child in enumerate(directory.iterdir()):
            if child.is_symlink():
                return True
            if i >= 1:
                break
    except OSError:
        pass
    return False


if not follow_symlinks and _has_symlinks(assets_dir):
    LOGGER.error(
        "Assets directory contains symlinks but follow_symlink=false.\n"
        "This commonly happens with package managers like pdm/uv "
        "that use symlinks for installed packages.\n"
        "To fix this:\n"
        "1. Run 'sp config show' to see your current config\n"
        "2. Add 'follow_symlink = true' under the [server] section in your config\n"
        "3. Restart sp\n\n"
        "Example config:\n"
        "[server]\n"
        "follow_symlink = true"
    )

try:
    router.mount(
        "/assets",
        app=StaticFiles(
            directory=assets_dir,
            follow_symlink=follow_symlinks,
        ),
        name="assets",
    )
except RuntimeError:
    LOGGER.error("Static files not found, skipping mount")

try:
    router.mount(
        "/_next",
        app=StaticFiles(directory=root / "_next", follow_symlink=follow_symlinks),
        name="next-static",
    )
except RuntimeError:
    LOGGER.debug("_next directory not present yet (pre-build); skipping mount")

FILE_QUERY_PARAM_KEY = "file"

# Hardening headers for HTML page responses.
_HTML_SECURITY_HEADERS: dict[str, str] = {
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _strip_access_token_redirect(request: Request) -> RedirectResponse:
    """Build a redirect to the current URL with access_token removed."""
    stripped = request.url.remove_query_params(TOKEN_QUERY_PARAM)
    target = stripped.path
    if stripped.query:
        target = f"{target}?{stripped.query}"
    return RedirectResponse(
        url=target,
        status_code=303,
        headers=_HTML_SECURITY_HEADERS,
    )


def _login_redirect(request: Request) -> RedirectResponse:
    """Build a relative redirect to the login page for unauthenticated users."""
    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    login_path = request.app.url_path_for("auth:login_page")
    return RedirectResponse(
        url=f"{login_path}?{urlencode({'next': next_url})}",
        status_code=303,
    )


@router.get("/og/thumbnail", include_in_schema=False)
@requires("read")
def og_thumbnail(*, request: Request) -> Response:
    """Serve a notebook thumbnail for gallery/OpenGraph use."""
    from pathlib import Path

    from signalpilot._metadata.opengraph import (
        DEFAULT_OPENGRAPH_PLACEHOLDER_IMAGE_GENERATOR,
        OpenGraphContext,
        is_https_url,
        resolve_opengraph_metadata,
    )
    from signalpilot._utils.http import HTTPException, HTTPStatus
    from signalpilot._utils.paths import (
        SP_DIR_NAME,
        normalize_path,
        notebook_output_dir,
    )

    app_state = AppState(request)
    file_key = (
        app_state.query_params(FILE_QUERY_PARAM_KEY)
        or app_state.session_manager.workspace.get_unique_file_key()
    )
    if not file_key:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="File not found"
        )

    notebook_path = app_state.session_manager.workspace.resolve(file_key)
    if notebook_path is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="File not found"
        )

    notebook_dir = normalize_path(Path(notebook_path)).parent
    signalpilot_dir = notebook_output_dir(notebook_path)

    opengraph = resolve_opengraph_metadata(
        notebook_path,
        context=OpenGraphContext(
            filepath=notebook_path,
            file_key=file_key,
            base_url=app_state.base_url,
            mode=app_state.mode.value,
        ),
    )
    title = opengraph.title or "sp"
    image = opengraph.image

    validator = PathValidator()
    if image:
        if is_https_url(image):
            return RedirectResponse(
                url=image,
                status_code=307,
                headers={"Cache-Control": "max-age=3600"},
            )

        rel_path = Path(image)
        if not rel_path.is_absolute():
            parts = rel_path.parts
            if parts and parts[0] == SP_DIR_NAME:
                file_path = normalize_path(signalpilot_dir / Path(*parts[1:]))
            else:
                file_path = normalize_path(notebook_dir / rel_path)
            try:
                if file_path.is_file():
                    validator.validate_inside_directory(signalpilot_dir, file_path)
                    return FileResponse(
                        file_path,
                        headers={"Cache-Control": "max-age=3600"},
                    )
            except HTTPException:
                pass

    placeholder = DEFAULT_OPENGRAPH_PLACEHOLDER_IMAGE_GENERATOR(title)
    return Response(
        content=placeholder.content,
        media_type=placeholder.media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/")
async def index(request: Request) -> Response:
    if not has_required_scope(request, ["read"]):
        return _login_redirect(request)

    if TOKEN_QUERY_PARAM in request.query_params:
        return _strip_access_token_redirect(request)

    index_html = root / "index.html"
    if not index_html.exists():
        raise HTTPException(
            status_code=500,
            detail=_missing_index_html_detail(),
        )

    return HTMLResponse(
        content=index_html.read_text(encoding="utf-8"),
        headers=_HTML_SECURITY_HEADERS,
    )


STATIC_FILES = [
    r"(favicon\.ico)",
    r"(favicon\.svg)",
    r"(favicon-96x96\.png)",
    r"(manifest\.json)",
    r"(android-chrome-(192x192|512x512)\.png)",
    r"(apple-touch-icon\.png)",
    r"(logo\.png)",
    r"(logo\.svg)",
    r"(logo-192\.png)",
]


@router.get("/@file/{filename_and_length:path}")
def virtual_file(
    request: Request,
) -> Response:
    """
    parameters:
        - in: path
          name: filename_and_length
          required: true
          schema:
            type: string
          description: The filename and byte length of the virtual file
    responses:
        200:
            description: Get a virtual file
            content:
                application/octet-stream:
                    schema:
                        type: string
        404:
            description: Invalid virtual file request
        404:
            description: Invalid byte length in virtual file request
    """
    if not GLOBAL_SETTINGS.DISABLE_AUTH_ON_VIRTUAL_FILES:
        if not has_required_scope(request, ["read"]):
            raise HTTPException(status_code=403)

    filename_and_length = request.path_params["filename_and_length"]

    LOGGER.debug("Getting virtual file: %s", filename_and_length)
    if filename_and_length == EMPTY_VIRTUAL_FILE.filename:
        return Response(content=b"", media_type="application/octet-stream")
    if "-" not in filename_and_length:
        raise HTTPException(
            status_code=404,
            detail="Invalid virtual file request",
        )

    byte_length_str, filename = filename_and_length.split("-", 1)
    if not byte_length_str.isdigit():
        raise HTTPException(
            status_code=404,
            detail="Invalid byte length in virtual file request",
        )
    total_size = int(byte_length_str)

    mimetype, _ = mimetypes.guess_type(filename)
    headers = {
        "Cache-Control": "max-age=86400",
        "Accept-Ranges": "bytes",
    }
    if request.query_params.get("download") == "1":
        from signalpilot._convert.common.filename import make_download_headers

        download_filename = request.query_params.get("filename") or filename
        headers.update(make_download_headers(download_filename))

    range_header = request.headers.get("range")
    if range_header is not None:
        parsed = _parse_range_header(range_header, total_size)
        if parsed is None:
            return Response(
                status_code=416,
                headers={**headers, "Content-Range": f"bytes */{total_size}"},
            )
        start, end = parsed
        length = end - start + 1
        chunks = read_virtual_file_chunked(filename, length, start=start)
        partial_headers = {
            **headers,
            "Content-Range": f"bytes {start}-{end}/{total_size}",
            "Content-Length": str(length),
        }
        return StreamingResponse(
            content=chunks,
            status_code=206,
            media_type=mimetype,
            headers=partial_headers,
        )

    chunks = read_virtual_file_chunked(filename, total_size)
    return StreamingResponse(
        content=chunks,
        media_type=mimetype,
        headers=headers,
    )


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$", re.IGNORECASE)


def _parse_range_header(
    range_header: str, total_size: int
) -> tuple[int, int] | None:
    """Parse a single-range HTTP ``Range`` header."""
    match = _RANGE_RE.match(range_header.strip())
    if match is None or total_size == 0:
        return None
    start_str, end_str = match.group(1), match.group(2)
    if start_str == "" and end_str == "":
        return None
    if start_str == "":
        suffix = int(end_str)
        if suffix == 0:
            return None
        start = max(total_size - suffix, 0)
        end = total_size - 1
    else:
        start = int(start_str)
        end = int(end_str) if end_str else total_size - 1
    if start >= total_size or end < start:
        return None
    end = min(end, total_size - 1)
    return start, end


@router.get("/public/{filepath:path}")
@requires("read")
async def serve_public_file(request: Request) -> Response:
    """Serve files from the notebook's directory under /public/"""
    app_state = AppState(request)
    filepath = str(request.path_params["filepath"])
    notebook_id = request.headers.get("X-Notebook-Id")
    if notebook_id:
        notebook_id = uri_decode_component(notebook_id)
        app_manager = app_state.session_manager.app_manager(notebook_id)
        if app_manager.filename:
            notebook_dir = Path(app_manager.filename).parent
        else:
            notebook_dir = Path.cwd()
        public_dir = notebook_dir / "public"
        file_path = public_dir / filepath

        try:
            PathValidator().validate_inside_directory(public_dir, file_path)
        except HTTPException:
            return Response(status_code=403, content="Access denied")

        try:
            resolved_file = file_path.resolve(strict=True)
            resolved_public = public_dir.resolve(strict=True)
            resolved_file.relative_to(resolved_public)
        except (OSError, ValueError):
            raise HTTPException(
                status_code=404, detail="File not found"
            ) from None

        if resolved_file.is_file():
            return FileResponse(resolved_file)

    raise HTTPException(status_code=404, detail="File not found")


# Catch all for serving static files
@router.get("/{path:path}")
async def serve_static(request: Request) -> FileResponse:
    path = str(request.path_params["path"])
    if any(re.fullmatch(pattern, path) for pattern in STATIC_FILES):
        file_path = Path(path)
        try:
            PathValidator().validate_inside_directory(root, file_path)
        except Exception:
            raise HTTPException(status_code=404, detail="Not Found") from None
        resolved = root / path
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(resolved)

    raise HTTPException(status_code=404, detail="Not Found")
