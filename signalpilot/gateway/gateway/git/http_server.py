"""Git smart HTTP server — proxies to git http-backend CGI."""

import logging
import os
import subprocess

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .repos import repo_path, repo_exists

logger = logging.getLogger(__name__)

router = APIRouter()


@router.api_route(
    "/git/{project_id}.git/{remainder:path}",
    methods=["GET", "POST"],
)
async def git_http_handler(project_id: str, remainder: str, request: Request):
    """Serve git smart HTTP protocol via git-http-backend CGI.

    Supports clone (git-upload-pack), push (git-receive-pack),
    info/refs, HEAD, and loose object/pack access.
    """
    if not repo_exists(project_id):
        raise HTTPException(status_code=404, detail="Repository not found")

    path = repo_path(project_id)
    body = await request.body()

    env = os.environ.copy()
    env["GIT_PROJECT_ROOT"] = str(path.parent)
    env["GIT_HTTP_EXPORT_ALL"] = "1"
    env["PATH_INFO"] = f"/{project_id}.git/{remainder}"
    env["QUERY_STRING"] = str(request.url.query) if request.url.query else ""
    env["REQUEST_METHOD"] = request.method
    env["CONTENT_TYPE"] = request.headers.get("content-type", "")
    env["CONTENT_LENGTH"] = str(len(body)) if body else "0"
    env["SERVER_PROTOCOL"] = "HTTP/1.1"
    env["REMOTE_ADDR"] = request.client.host if request.client else "127.0.0.1"

    try:
        proc = subprocess.run(
            ["git", "http-backend"],
            input=body,
            capture_output=True,
            env=env,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git operation timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="git not installed on server")

    if not proc.stdout:
        logger.warning("git http-backend returned empty response for %s %s", request.method, remainder)
        raise HTTPException(status_code=500, detail="Git backend returned empty response")

    # Parse CGI response: headers separated from body by \r\n\r\n
    raw = proc.stdout
    header_end = raw.find(b"\r\n\r\n")
    if header_end == -1:
        header_end = raw.find(b"\n\n")
        header_sep_len = 2
    else:
        header_sep_len = 4

    if header_end == -1:
        return Response(content=raw, status_code=200)

    header_bytes = raw[:header_end]
    body_bytes = raw[header_end + header_sep_len:]

    status_code = 200
    headers: dict[str, str] = {}

    for line in header_bytes.decode("utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("status:"):
            status_str = line.split(":", 1)[1].strip()
            status_code = int(status_str.split(" ", 1)[0])
        elif ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    if proc.stderr:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        if stderr:
            logger.debug("git http-backend stderr: %s", stderr[:200])

    return Response(content=body_bytes, status_code=status_code, headers=headers)
