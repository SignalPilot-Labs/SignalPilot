"""Filesystem HTTP handlers for the sandbox.

Exposes read/write/mkdir/exists/ls over HTTP so the agent container can
manipulate files in the sandbox without piping shell commands through /exec.
"""

from pathlib import Path

from aiohttp import web

from constants import FS_READ_MAX_BYTES


async def handle_write(request: web.Request) -> web.Response:
    """Write or append text content to a path. Creates parent dirs."""
    body = await request.json()
    path = Path(body["path"])
    content: str = body["content"]
    append: bool = bool(body.get("append", False))

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        written = f.write(content)
    return web.json_response({"ok": True, "bytes": written})


async def handle_read(request: web.Request) -> web.Response:
    """Read text content from a path. Returns exists=False if missing."""
    body = await request.json()
    path = Path(body["path"])
    if not path.exists():
        return web.json_response({"exists": False, "content": ""})
    if not path.is_file():
        return web.json_response(
            {"error": f"{path} is not a file"}, status=400,
        )
    size = path.stat().st_size
    if size > FS_READ_MAX_BYTES:
        return web.json_response(
            {"error": f"file too large ({size} > {FS_READ_MAX_BYTES})"},
            status=413,
        )
    content = path.read_text(encoding="utf-8")
    return web.json_response({"exists": True, "content": content})


async def handle_mkdir(request: web.Request) -> web.Response:
    """Create a directory with parents."""
    body = await request.json()
    path = Path(body["path"])
    path.mkdir(parents=True, exist_ok=True)
    return web.json_response({"ok": True})


async def handle_exists(request: web.Request) -> web.Response:
    """Check if a path exists."""
    body = await request.json()
    path = Path(body["path"])
    return web.json_response({
        "exists": path.exists(),
        "is_file": path.is_file() if path.exists() else False,
        "is_dir": path.is_dir() if path.exists() else False,
    })


async def handle_ls(request: web.Request) -> web.Response:
    """List names in a directory (sorted). Empty list if missing."""
    body = await request.json()
    path = Path(body["path"])
    if not path.exists() or not path.is_dir():
        return web.json_response({"entries": []})
    entries = sorted(p.name for p in path.iterdir())
    return web.json_response({"entries": entries})


async def handle_read_dir(request: web.Request) -> web.Response:
    """Read every regular file directly under a dir. Non-recursive."""
    body = await request.json()
    path = Path(body["path"])
    if not path.exists() or not path.is_dir():
        return web.json_response({"exists": False, "files": {}})
    files: dict[str, str] = {}
    total = 0
    for entry in sorted(path.iterdir()):
        if not entry.is_file():
            continue
        size = entry.stat().st_size
        total += size
        # Guard against a rogue multi-MB dir blowing the response.
        if total > FS_READ_MAX_BYTES:
            return web.json_response(
                {"error": f"dir too large (>{FS_READ_MAX_BYTES})"},
                status=413,
            )
        files[entry.name] = entry.read_text(encoding="utf-8")
    return web.json_response({"exists": True, "files": files})


async def handle_write_dir(request: web.Request) -> web.Response:
    """Create a dir and write a filename→content map into it."""
    body = await request.json()
    path = Path(body["path"])
    files: dict[str, str] = body["files"]
    path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        # Filename must be a plain basename — no traversal out of `path`.
        if "/" in name or name in ("", ".", ".."):
            return web.json_response(
                {"error": f"invalid filename: {name}"}, status=400,
            )
        (path / name).write_text(content, encoding="utf-8")
    return web.json_response({"ok": True, "count": len(files)})


def register(app: web.Application) -> None:
    """Attach all /file_system/* routes to the aiohttp app."""
    app.router.add_post("/file_system/write", handle_write)
    app.router.add_post("/file_system/read", handle_read)
    app.router.add_post("/file_system/mkdir", handle_mkdir)
    app.router.add_post("/file_system/exists", handle_exists)
    app.router.add_post("/file_system/ls", handle_ls)
    app.router.add_post("/file_system/read_dir", handle_read_dir)
    app.router.add_post("/file_system/write_dir", handle_write_dir)
