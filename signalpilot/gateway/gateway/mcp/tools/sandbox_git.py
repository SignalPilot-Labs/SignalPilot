"""Git checkout support for the agent sandbox VM.

The chat agent edits models in the sandbox created by ``sandbox_vm.py``.
``_seed_project`` hydrates ``/workspace`` there from the S3 snapshot; this
module adds the step that turns the same directory into a git checkout whose
``origin`` is the gateway's own git server, so the agent can commit and
``git push origin HEAD:signalpilot/<name>`` with plain git through
``sandbox_exec``.

Credential model
----------------
The git server (``gateway/git/http_server.py::_authenticate``) accepts HTTP
Basic auth with any username and a notebook session JWT as the password. The
gateway mints a short-lived JWT per exec (``mint_git_token``) and injects it
as ``SP_GIT_TOKEN`` into the env of every ``runtime.exec`` for the sandbox.
A credential helper reads that variable at call time, so the token is never
written to ``.git/config``, to disk, or into a command string.
"""

from __future__ import annotations

import logging
import shlex
from urllib.parse import urlparse

from gateway.auth.notebook_jwt import mint_session_jwt, verify_session_jwt
from gateway.config.gateway import _LOCAL_GATEWAY_URL_DEFAULT, get_gateway_settings
from gateway.mcp.context import (
    mcp_allowed_connection_var,
    mcp_branch_var,
    mcp_capabilities_var,
    mcp_execution_identity_var,
    mcp_org_id_var,
    mcp_project_id_var,
    mcp_raw_key_var,
    mcp_user_id_var,
)
from gateway.runtime.mode import is_cloud_mode

logger = logging.getLogger(__name__)

GIT_TOKEN_ENV = "SP_GIT_TOKEN"
GIT_REMOTE_URL_ENV = "SP_GIT_REMOTE_URL"
GIT_BASE_BRANCH_ENV = "SP_GIT_BASE_BRANCH"

GIT_TOKEN_TTL_SECONDS = 30 * 60
GIT_TOKEN_SCOPES = ["read", "write"]

GIT_AUTHOR_NAME = "SignalPilot Agent"
GIT_AUTHOR_EMAIL = "agent@signalpilot.ai"

# dbt build output and tooling caches that must never land in a commit. The
# project's own .gitignore (when it ships one) still applies; this is additive.
GIT_EXCLUDE_PATTERNS = ("target/", "dbt_packages/", "logs/", ".venv/", "__pycache__/")
_EXCLUDE_MARKER = "# sp-managed"

CREDENTIAL_HELPER = (
    f'!f() {{ echo username=x-access-token; echo "password=${GIT_TOKEN_ENV}"; }}; f'
)


def _is_loopback(url: str) -> bool:
    try:
        hostname = urlparse(url).hostname
    except ValueError:
        return False
    return hostname in {"localhost", "127.0.0.1", "::1"}


def git_remote_url(project_id: str | None) -> str | None:
    """The gateway git URL for ``project_id``, or None when git publishing is
    unavailable for this sandbox.

    Mirrors ``workspace_projects.get_clone_url``: cloud mode always uses the
    configured public URL; local mode uses it only when it is a real,
    non-loopback address a sandbox can reach.
    """
    if not project_id:
        return None
    configured = (get_gateway_settings().sp_public_gateway_url or "").rstrip("/")
    if not configured:
        return None
    if not is_cloud_mode() and (
        configured == _LOCAL_GATEWAY_URL_DEFAULT or _is_loopback(configured)
    ):
        return None
    return f"{configured}/git/{project_id}.git"


def git_seed_env(project_id: str | None, branch: str) -> dict[str, str]:
    """Env additions for the seed exec; empty when git is unavailable."""
    remote = git_remote_url(project_id)
    if not remote:
        return {}
    return {GIT_REMOTE_URL_ENV: remote, GIT_BASE_BRANCH_ENV: branch}


def git_setup_lines(workspace: str = "/workspace") -> list[str]:
    """The shell lines that convert ``workspace`` into a checkout.

    The working tree stays exactly as hydrated from S3 and the index points
    at the base branch tree, so ``git status`` shows precisely what the
    workspace changed relative to the base. Every step runs inside a subshell
    on the left of ``||``, so a failure logs to stderr and the seed continues
    even under ``set -e``.
    """
    exclude_lines = " ".join(f"'{pattern}'" for pattern in GIT_EXCLUDE_PATTERNS)
    return [
        "sp_git_setup() {",
        "  export GIT_TERMINAL_PROMPT=0;",
        f"  cd {shlex.quote(workspace)} || return 1;",
        "  if [ ! -d .git ]; then git init -q || return 1; fi;",
        "  git remote remove origin >/dev/null 2>&1;",
        f'  git remote add origin "${GIT_REMOTE_URL_ENV}" || return 1;',
        f'  git config user.name "{GIT_AUTHOR_NAME}";',
        f"  git config user.email {GIT_AUTHOR_EMAIL};",
        f"  git config credential.helper '{CREDENTIAL_HELPER}';",
        "  mkdir -p .git/info;",
        f"  grep -qs '{_EXCLUDE_MARKER}' .git/info/exclude "
        f"|| printf '%s\\n' '{_EXCLUDE_MARKER}' {exclude_lines} >> .git/info/exclude;",
        f'  git fetch -q --depth=50 origin "${GIT_BASE_BRANCH_ENV}" || return 1;',
        f'  git symbolic-ref HEAD "refs/heads/${GIT_BASE_BRANCH_ENV}" || return 1;',
        "  git reset -q --mixed FETCH_HEAD || return 1;",
        "};",
        "( sp_git_setup ) "
        '|| echo "sp: git checkout setup failed; git publish is unavailable" >&2;',
    ]


def git_setup_command(workspace: str = "/workspace") -> str:
    """One shell fragment (trailing space) to splice into the seed command."""
    return " ".join(git_setup_lines(workspace)) + " "


def mint_git_token() -> str | None:
    """A fresh short-lived session JWT for git pushes from this sandbox.

    Derived from the run's own inbound session JWT when the bearer in context
    is one: the verifier demands ``commit_sha``, ``connection_name`` and
    ``capabilities`` for ``chat:`` identities, and only the inbound token
    carries them all. Otherwise (API-key callers, tests) the token is built
    from the context vars alone. Returns None when no identity is bound.
    """
    identity = mcp_execution_identity_var.get(None) or ""
    org_id = mcp_org_id_var.get(None)
    user_id = mcp_user_id_var.get(None)
    if not identity or not org_id or not user_id:
        return None
    claims: dict = {}
    raw = mcp_raw_key_var.get(None) or ""
    if raw.count(".") == 2:
        try:
            claims = verify_session_jwt(raw)
        except Exception:
            claims = {}
    capabilities = list(claims.get("capabilities") or mcp_capabilities_var.get(None) or [])
    return mint_session_jwt(
        user_id=str(claims.get("sub") or user_id),
        org_id=str(claims.get("org_id") or org_id),
        session_id=str(claims.get("session_id") or identity),
        project_id=claims.get("project_id") or mcp_project_id_var.get(None),
        branch=str(claims.get("branch") or mcp_branch_var.get(None) or "main"),
        connection_name=claims.get("connection_name") or mcp_allowed_connection_var.get(None),
        commit_sha=claims.get("commit_sha"),
        capabilities=capabilities or None,
        execution_identity=str(claims.get("execution_identity") or identity),
        scopes=list(GIT_TOKEN_SCOPES),
        ttl=GIT_TOKEN_TTL_SECONDS,
    )


def git_exec_env() -> dict[str, str]:
    """Per-exec env: a fresh ``SP_GIT_TOKEN``; empty when none can be minted."""
    try:
        token = mint_git_token()
    except Exception:
        logger.warning("git token mint failed; push is unavailable this call", exc_info=True)
        return {}
    return {GIT_TOKEN_ENV: token} if token else {}
