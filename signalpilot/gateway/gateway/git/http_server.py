"""Git smart HTTP server — proxies to git http-backend CGI.

Security:
- HTTP Basic Auth required on every request (token validated against DB)
- Org isolation enforced: project must belong to caller's org
- Read vs write scope enforced based on git operation type
- Path traversal blocked: project_id validated as UUID
- CGI env vars sanitized: no user-controlled data in shell-sensitive vars
- Generic error messages: no internal paths or repo structure leaked
- Push size limited to SP_GIT_MAX_PUSH_BYTES (default 500MB); fetch requests to
  SP_GIT_MAX_UPLOAD_PACK_BYTES (default 8MB). Both apply to the inflated body.
- Eval credentials (connection-pinned keys) never reach git
- Chat run tokens (execution_identity "chat:<run_id>") may only create or
  update refs/heads/signalpilot/** (ref_policy.py); git itself refuses their
  force pushes and deletes. Each accepted branch is recorded and mirrored to
  GitHub before the push returns.
"""

import base64
import logging
import os
import re
import subprocess
import zlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .ref_policy import (
    RefUpdate,
    build_rejection_report,
    check_chat_push,
    parse_receive_pack_commands,
    pushed_branches,
    reason_exists_on_github,
    reason_other_chat,
)
from .repos import repo_path, repo_exists, REPOS_ROOT

logger = logging.getLogger(__name__)

router = APIRouter()

_UUID_RE = re.compile(r"^[a-f0-9\-]{36}$")
_PATH_RE = re.compile(r"^[a-zA-Z0-9/_\-\.]+$")
_MAX_PUSH_BYTES = int(os.getenv("SP_GIT_MAX_PUSH_BYTES", str(500 * 1024 * 1024)))
_MAX_UPLOAD_PACK_BYTES = int(os.getenv("SP_GIT_MAX_UPLOAD_PACK_BYTES", str(8 * 1024 * 1024)))
# Scopes a notebook-session token can exercise here: the same REST ceiling as
# scope_guard, so the admin claim on chat run tokens never reaches git.
_SESSION_SCOPE_ALLOWLIST = frozenset({"read", "write", "query", "execute"})


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
                "eval_run_id": matched.eval_run_id,
            }

    # Session JWT validation (for notebook pods)
    try:
        from ..auth.notebook_jwt import verify_session_jwt
        claims = verify_session_jwt(token)
        return {
            "user_id": claims["sub"],
            "org_id": claims["org_id"],
            "scopes": [s for s in claims.get("scopes", ["read", "write"]) if s in _SESSION_SCOPE_ALLOWLIST],
            "auth_method": "notebook_session",
            "execution_identity": claims.get("execution_identity"),
        }
    except Exception:
        pass

    raise HTTPException(status_code=403, detail="Invalid credentials")


def chat_run_id(auth: dict) -> str | None:
    """The chat run behind a session token, or None for every other identity.

    Only a notebook-session token whose execution_identity is ``chat:<run_id>``
    is a chat identity; API keys and plain notebook sessions keep the open
    policy (they push signalpilot-agent/* working branches).
    """
    if auth.get("auth_method") != "notebook_session":
        return None
    identity = auth.get("execution_identity") or ""
    if not identity.startswith("chat:") or len(identity) <= 5:
        return None
    return identity[5:]


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


async def _read_body(request: Request, limit: int, *, is_write: bool) -> bytes:
    """Buffer the request body up to ``limit`` inflated bytes.

    git clients gzip the upload-pack/receive-pack POST body and send
    `Content-Encoding: gzip`. git-http-backend does NOT inflate it, so the raw
    gzip bytes reach upload-pack as pkt-lines → "fatal: protocol error: bad line
    length character" and the clone hangs ("the remote end hung up"). Inflate
    here, incrementally, so a small compressed body cannot expand past the
    ceiling in memory; gzip and deflate both occur in the wild.
    """
    content_encoding = request.headers.get("content-encoding", "").lower().strip()
    inflater = None
    if content_encoding in ("gzip", "x-gzip"):
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif content_encoding == "deflate":
        inflater = zlib.decompressobj()
    too_large = HTTPException(status_code=413, detail="Push too large" if is_write else "Request too large")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        if inflater is not None:
            try:
                chunk = inflater.decompress(chunk, limit + 1 - total)
            except zlib.error as exc:
                logger.warning("git: failed to inflate %s body: %s", content_encoding, exc)
                raise HTTPException(status_code=400, detail="Malformed request encoding")
        total += len(chunk)
        if total > limit or (inflater is not None and inflater.unconsumed_tail):
            raise too_large
        chunks.append(chunk)
    if inflater is not None:
        try:
            tail = inflater.flush()
        except zlib.error as exc:
            logger.warning("git: failed to inflate %s body: %s", content_encoding, exc)
            raise HTTPException(status_code=400, detail="Malformed request encoding")
        if total + len(tail) > limit:
            raise too_large
        chunks.append(tail)
        if total + len(tail) and not inflater.eof:
            raise HTTPException(status_code=400, detail="Malformed request encoding")
    return b"".join(chunks)


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

    # 6. Enforce read/write scope. Eval keys are pinned to one connection and a
    # document set; workspace repositories are outside that boundary.
    if auth.get("eval_run_id"):
        raise HTTPException(status_code=403, detail="Eval credentials cannot access git")
    query_string = str(request.url.query) if request.url.query else ""
    is_write = _is_write_operation(request.method, remainder, query_string)
    scopes = auth.get("scopes", [])

    if is_write and "write" not in scopes:
        raise HTTPException(status_code=403, detail="Write access required")
    if not is_write and "read" not in scopes:
        raise HTTPException(status_code=403, detail="Read access required")

    # 7. Read the body with a size ceiling (inflated bytes), for reads and writes.
    body = await _read_body(request, _MAX_PUSH_BYTES if is_write else _MAX_UPLOAD_PACK_BYTES, is_write=is_write)

    # 7b. Chat identities: refuse the whole push when any command leaves
    # refs/heads/signalpilot/** or deletes a ref. The refusal is a valid
    # report-status so the git client prints "! [remote rejected] ... (reason)".
    run_id = chat_run_id(auth)
    commands: list[RefUpdate] = []
    if is_write and run_id and remainder.endswith("git-receive-pack"):
        commands, capabilities = parse_receive_pack_commands(body)
        reasons = check_chat_push(commands)
        if commands and not reasons:
            reasons = await chat_branch_ownership_reasons(auth, project_id, run_id, commands)
        if reasons:
            logger.info(
                "git: chat push rejected: run=%s user=%s project=%s refs=%s",
                run_id, auth.get("user_id"), project_id, dict(reasons),
            )
            return Response(
                content=build_rejection_report(commands, reasons, capabilities),
                media_type="application/x-git-receive-pack-result",
                headers={"Cache-Control": "no-cache"},
            )

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
    if run_id and is_write:
        # git refuses force pushes and deletes itself, with its normal
        # "(non-fast-forward)" / "(deletion prohibited)" message.
        env.update({
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_1": "receive.denyNonFastForwards",
            "GIT_CONFIG_VALUE_1": "true",
            "GIT_CONFIG_KEY_2": "receive.denyDeletes",
            "GIT_CONFIG_VALUE_2": "true",
        })

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
    # git sends `Git-Protocol: version=2` on the info/refs GET but NOT on the
    # subsequent git-upload-pack POST. http-backend is stateless, so without
    # GIT_PROTOCOL on the POST it runs upload-pack in v0 mode and chokes on the
    # v2 `command=fetch` body ("the remote end hung up unexpectedly"). Detect a v2
    # request from the body and set GIT_PROTOCOL=version=2 so the POST is handled
    # in the same protocol the client used to negotiate.
    if "GIT_PROTOCOL" not in env and b"command=" in body[:40]:
        env["GIT_PROTOCOL"] = "version=2"

    # 10. Execute git http-backend
    try:
        proc = subprocess.run(
            ["git", "http-backend"],
            input=body,
            capture_output=True,
            env=env,
            timeout=120,
        )
        if proc.returncode != 0:
            logger.warning(
                "git http-backend failed: op=%s rc=%d err=%s",
                remainder, proc.returncode,
                proc.stderr.decode("utf-8", errors="replace")[:200],
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

    if is_write and status_code < 400:
        if run_id:
            # Chat push: record + publish the accepted signalpilot/** branches
            # before answering so the branch is on GitHub when `git push` returns.
            # mirror_push_to_github must NOT also run here (it would push twice).
            if commands:
                await publish_chat_push(auth, project_id, run_id, commands)
        else:
            # Auto-mirror to GitHub after a successful push (fire and forget).
            import asyncio
            from .sync import mirror_push_to_github
            org_id = auth.get("org_id", "local")
            for branch in pushed_branches(body) or ["main"]:
                asyncio.ensure_future(mirror_push_to_github(project_id, org_id, branch))

    # The git smart-HTTP Content-Type (e.g. application/x-git-upload-pack-advertisement)
    # MUST reach the client or git rejects the stream and the clone hangs
    # ("remote end hung up unexpectedly"). Starlette's Response derives Content-Type
    # from its media_type arg and overrides any Content-Type left in the headers dict,
    # so extract it and pass it as media_type. Match case-insensitively (CGI emits
    # "Content-Type").
    media_type = None
    for k in list(headers):
        if k.lower() == "content-type":
            media_type = headers.pop(k)
            break

    return Response(
        content=body_bytes,
        status_code=status_code,
        headers=headers,
        media_type=media_type,
    )


async def github_remote_url(session, org_id: str, link) -> str | None:
    """Credentialed push URL for the project's active GitHub link, or None."""
    from ..store import github as gh_store

    installation = await gh_store.get_installation(session, org_id=org_id, installation_id=link.installation_id)
    if not installation or installation.status != "active":
        logger.warning("git: GitHub installation %s unavailable for %s", link.installation_id, link.project_id)
        return None
    try:
        token = await gh_store.get_valid_token(session, installation)
    except Exception as exc:
        logger.warning("git: no GitHub token for project %s (%s)", link.project_id, type(exc).__name__)
        return None
    return f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"


async def chat_run_conversation(session, org_id: str, run_id: str) -> str | None:
    from sqlalchemy import select

    from ..db.models import GatewayChatRun

    run = (
        await session.execute(
            select(GatewayChatRun).where(GatewayChatRun.id == run_id, GatewayChatRun.org_id == org_id)
        )
    ).scalar_one_or_none()
    return run.conversation_id if run else None


async def chat_branch_ownership_reasons(
    auth: dict, project_id: str, run_id: str, commands: list[RefUpdate]
) -> dict[str, str]:
    """Pre-receive checks that need the database: refname -> reason.

    - A branch whose push record belongs to another conversation is refused.
    - A branch creation (old sha all zeros) with no record of ours, on a
      project with a usable GitHub link, is refused when GitHub already has
      that branch (one ls-remote). No link or no token: the push proceeds
      and is recorded unpublished.
    """
    import asyncio

    from ..db.engine import get_session_factory
    from ..store import github as gh_store
    from ..store import github_prs
    from .sync import remote_branch_exists

    org_id = auth.get("org_id", "local")
    reasons: dict[str, str] = {}
    factory = get_session_factory()
    async with factory() as session:
        conversation_id = await chat_run_conversation(session, org_id, run_id)
        link = await gh_store.get_repo_link_for_project(session, org_id=org_id, project_id=project_id)
        remote_url: str | None = None
        for command in commands:
            branch = command.branch
            if not branch:
                continue
            record = await github_prs.get_branch_record(
                session, org_id=org_id, project_id=project_id, github_branch=branch
            )
            if record is not None:
                if record.conversation_id and record.conversation_id != conversation_id:
                    reasons[command.refname] = reason_other_chat(branch)
                continue
            if not command.is_create or link is None:
                continue
            if remote_url is None:
                remote_url = await github_remote_url(session, org_id, link)
                if remote_url is None:
                    break
            exists = await asyncio.to_thread(remote_branch_exists, project_id, remote_url, branch)
            if exists:
                reasons[command.refname] = reason_exists_on_github(branch)
    return reasons


async def publish_chat_push(auth: dict, project_id: str, run_id: str, commands: list[RefUpdate]) -> list[dict]:
    """Record and mirror every branch a chat push actually updated.

    A command counts as accepted when the mirror's head now equals its new
    sha (git may have refused some, e.g. non-fast-forward). Each accepted
    branch gets an upserted push record; when the project has an active
    GitHub link the branch is pushed under the same name (fast-forward
    only). A branch that exists on GitHub without a push record of ours is
    left alone and not recorded: we never touch branches we did not create.
    Returns one result dict per accepted branch (for logs and tests).
    """
    import asyncio

    from ..db.engine import get_session_factory
    from ..store import github as gh_store
    from ..store import github_prs
    from .repos import branch_head_sha
    from .sync import publish_agent_branch

    org_id = auth.get("org_id", "local")
    actor = auth.get("user_id", "")
    accepted = [
        (c.branch, c.new_sha) for c in commands
        if c.branch and branch_head_sha(project_id, c.branch) == c.new_sha
    ]
    if not accepted:
        logger.info("git: chat push accepted no refs: run=%s project=%s", run_id, project_id)
        return []

    results: list[dict] = []
    factory = get_session_factory()
    async with factory() as session:
        conversation_id = await chat_run_conversation(session, org_id, run_id)
        link = await gh_store.get_repo_link_for_project(session, org_id=org_id, project_id=project_id)
        remote_url = await github_remote_url(session, org_id, link) if link else None

        for branch, sha in accepted:
            existing = await github_prs.get_branch_record(
                session, org_id=org_id, project_id=project_id, github_branch=branch
            )
            result: dict = {"branch": branch, "sha": sha, "published": False}
            if remote_url:
                outcome = await asyncio.to_thread(
                    publish_agent_branch, project_id, remote_url, branch, known_branch=existing is not None
                )
                if outcome.get("exists"):
                    logger.warning(
                        "git: chat push not mirrored, branch exists on GitHub and is not ours: "
                        "run=%s project=%s branch=%s", run_id, project_id, branch,
                    )
                    results.append({**result, "error": outcome["error"], "exists": True})
                    continue
                result["published"] = bool(outcome.get("pushed"))
                result["error"] = outcome.get("error")
            record = await github_prs.record_branch_push(
                session,
                org_id=org_id,
                project_id=project_id,
                conversation_id=conversation_id,
                repo_full_name=link.repo_full_name if link else "",
                github_branch=branch,
                base_branch=(link.default_branch if link else None) or "main",
                sha=sha,
                actor=actor,
                error_message=result.get("error"),
            )
            result["record_id"] = record.id
            results.append(result)
            logger.info(
                "git: chat push accepted: run=%s user=%s project=%s branch=%s sha=%s conversation=%s "
                "published=%s%s",
                run_id, actor, project_id, branch, sha[:12], conversation_id, result["published"],
                f" error={result['error']}" if result.get("error") else "",
            )
    return results
