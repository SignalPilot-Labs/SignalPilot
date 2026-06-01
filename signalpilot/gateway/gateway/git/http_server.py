"""Git smart HTTP server — proxies to git http-backend CGI.

Security:
- HTTP Basic Auth required on every request (token validated against DB)
- Org isolation enforced: project must belong to caller's org
- Read vs write scope enforced based on git operation type
- Path traversal blocked: project_id validated as UUID
- CGI env vars sanitized: no user-controlled data in shell-sensitive vars
- Generic error messages: no internal paths or repo structure leaked
- Push size limited to SP_GIT_MAX_PUSH_BYTES (default 500MB)
"""

import base64
import logging
import os
import re
import subprocess

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .repos import repo_path, repo_exists, REPOS_ROOT

logger = logging.getLogger(__name__)

router = APIRouter()

_UUID_RE = re.compile(r"^[a-f0-9\-]{36}$")
_PATH_RE = re.compile(r"^[a-zA-Z0-9/_\-\.]+$")
_MAX_PUSH_BYTES = int(os.getenv("SP_GIT_MAX_PUSH_BYTES", str(500 * 1024 * 1024)))


async def _authenticate(request: Request) -> dict:
    """Extract and validate HTTP Basic Auth credentials.

    Returns auth dict with user_id, org_id, scopes.
    Raises HTTPException on failure.
    """
    auth_header = request.headers.get("authorization", "")

    if not auth_header.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="SignalPilot Git"'},
        )

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, token = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    # Local dev key check (fast path, no DB)
    from ..store import get_local_api_key
    import hmac

    local_key = get_local_api_key()
    if local_key and hmac.compare_digest(token, local_key):
        return {"user_id": "local", "org_id": "local", "scopes": ["read", "write"], "auth_method": "local_key"}

    # Stored API key validation
    from ..db.engine import get_session_factory
    from ..store import Store

    factory = get_session_factory()
    async with factory() as session:
        store = Store(session)
        matched = await store.validate_stored_api_key(token)
        if matched:
            return {
                "user_id": matched.user_id,
                "org_id": matched.org_id or "local",
                "scopes": matched.scopes or [],
                "auth_method": "api_key",
            }

    # Session JWT validation (for notebook pods)
    try:
        from ..auth.notebook_jwt import verify_session_jwt
        claims = verify_session_jwt(token)
        return {
            "user_id": claims["sub"],
            "org_id": claims["org_id"],
            "scopes": claims.get("scopes", ["read", "write"]),
            "auth_method": "notebook_session",
        }
    except Exception:
        pass

    raise HTTPException(status_code=403, detail="Invalid credentials")


async def _authorize_project(auth: dict, project_id: str) -> None:
    """Verify the caller's org owns this project. Raises HTTPException if not."""
    from ..db.engine import get_session_factory
    from ..db.models import GatewayWorkspaceProject
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == project_id,
                GatewayWorkspaceProject.org_id == auth["org_id"],
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Repository not found")


def _is_write_operation(method: str, remainder: str, query: str) -> bool:
    """Determine if this git request is a write (push) operation."""
    if "git-receive-pack" in remainder:
        return True
    if "service=git-receive-pack" in query:
        return True
    return False


@router.api_route(
    "/git/{project_id}.git/{remainder:path}",
    methods=["GET", "POST"],
)
async def git_http_handler(project_id: str, remainder: str, request: Request):
    """Serve git smart HTTP protocol via git-http-backend CGI."""

    # 1. Validate project_id format (prevent path traversal)
    if not _UUID_RE.match(project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID")

    # 2. Validate remainder path (no shell metacharacters)
    if remainder and not _PATH_RE.match(remainder):
        raise HTTPException(status_code=400, detail="Invalid path")

    # 3. Authenticate
    auth = await _authenticate(request)

    # 4. Authorize: project must belong to caller's org
    await _authorize_project(auth, project_id)

    # 5. Check repo exists on disk
    if not repo_exists(project_id):
        raise HTTPException(status_code=404, detail="Repository not found")

    # 6. Enforce read/write scope
    query_string = str(request.url.query) if request.url.query else ""
    is_write = _is_write_operation(request.method, remainder, query_string)

    if is_write and "write" not in auth.get("scopes", []):
        raise HTTPException(status_code=403, detail="Write access required")

    # 7. Read body with size limit for pushes
    body = await request.body()
    if is_write and len(body) > _MAX_PUSH_BYTES:
        raise HTTPException(status_code=413, detail="Push too large")

    # 8. Resolve repo path and verify it's within REPOS_ROOT
    path = repo_path(project_id)
    if not str(path.resolve()).startswith(str(REPOS_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="Invalid project ID")

    # 9. Build sanitized CGI environment
    env = {
        "GIT_PROJECT_ROOT": str(path.parent),
        "GIT_HTTP_EXPORT_ALL": "1",
        "PATH_INFO": f"/{project_id}.git/{remainder}",
        "QUERY_STRING": query_string,
        "REQUEST_METHOD": request.method,
        "CONTENT_TYPE": request.headers.get("content-type", ""),
        "CONTENT_LENGTH": str(len(body)) if body else "0",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": request.client.host if request.client else "127.0.0.1",
        "REMOTE_USER": auth.get("user_id", ""),
        "PATH": os.environ.get("PATH", "/usr/bin"),
        # Repos under /repos are created by notebook pods (uid 10001) and served by
        # the gateway (also uid 10001), but git's safe-directory check still flags
        # them "dubious ownership" and then git-http-backend writes nothing to
        # stdout — the client sees "remote end hung up unexpectedly". Mark the repos
        # root safe via GIT_CONFIG env (inherited by http-backend and its
        # upload-pack/receive-pack children); --global config does not work because
        # the app user has no writable HOME.
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": "*",
    }

    # Forward the git wire-protocol version. Modern git clients (>=2.26) default to
    # protocol v2 and send `Git-Protocol: version=2`. git-http-backend only speaks
    # v2 when GIT_PROTOCOL is set; without it the server answers v0 while the client
    # expects v2 → the clone fails "fatal: the remote end hung up unexpectedly".
    git_protocol = request.headers.get("git-protocol")
    if git_protocol:
        # Constrain to the documented "version=N[:...]" shape; never forward
        # arbitrary client bytes into the CGI environment.
        if re.fullmatch(r"version=[0-9]+(:[A-Za-z0-9=_.-]+)*", git_protocol):
            env["GIT_PROTOCOL"] = git_protocol

    # 10. Execute git http-backend
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
        raise HTTPException(status_code=503, detail="Service unavailable")

    if not proc.stdout:
        logger.warning("git http-backend empty response: project=%s op=%s", project_id, remainder.split("/")[0] if remainder else "?")
        raise HTTPException(status_code=500, detail="Git operation failed")

    # 11. Parse CGI response
    raw = proc.stdout
    header_end = raw.find(b"\r\n\r\n")
    header_sep_len = 4
    if header_end == -1:
        header_end = raw.find(b"\n\n")
        header_sep_len = 2

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

    if proc.stderr and logger.isEnabledFor(logging.DEBUG):
        logger.debug("git stderr for project %s: %s", project_id, proc.stderr.decode("utf-8", errors="replace")[:100])

    # Auto-mirror to GitHub after a successful push
    if is_write and status_code < 400:
        import asyncio
        from .sync import mirror_push_to_github
        org_id = auth.get("org_id", "local")
        for branch in _detect_pushed_branches(body):
            asyncio.ensure_future(mirror_push_to_github(project_id, org_id, branch))

    return Response(content=body_bytes, status_code=status_code, headers=headers)


def _detect_pushed_branches(request_body: bytes) -> list[str]:
    """Extract branch names from git-receive-pack request body.

    The pkt-line format contains refs like:
    old_sha new_sha refs/heads/main\0capabilities...
    old_sha new_sha refs/heads/feat/my-branch
    """
    branches = []
    text = request_body.decode("utf-8", errors="replace")
    for match in re.finditer(r"refs/heads/([\w/.@_-]+)", text):
        branch = match.group(1)
        if branch not in branches:
            branches.append(branch)
    if not branches:
        branches.append("main")
    return branches
