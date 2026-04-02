"""Security gating: can_use_tool callback that enforces all access controls.

This is the security core of the self-improve framework. Every tool call
passes through check_tool_permission() before execution.

Rules:
1. Block reads/writes to credential files (.env, secrets, keys, tokens)
2. Block git push to any repo other than GITHUB_REPO
3. Block push to protected branches (main, staging, prod, master)
4. Confine all file operations to /workspace
5. Block dangerous commands (rm -rf /, docker rm, etc.)
6. Audit every permission decision
"""

import os
import re

from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from agent import db

# Read at call time so runtime changes from /start are picked up
def _get_allowed_repo() -> str:
    return os.environ.get("GITHUB_REPO", "")

# Protected branches - agent must never push directly to these
PROTECTED_BRANCHES = {"main", "master", "staging", "prod", "production"}

# Credential file patterns (case-insensitive)
CREDENTIAL_PATTERNS = [
    r"\.env($|\.|/)",
    r"credentials",
    r"\.pem$",
    r"\.key$",
    r"secret",
    r"\.token$",
    r"id_rsa",
    r"id_ed25519",
    r"\.gnupg",
    r"\.ssh/",
    r"\.npmrc$",
    r"\.pypirc$",
    r"\.docker/config\.json",
]
_cred_re = re.compile("|".join(CREDENTIAL_PATTERNS), re.IGNORECASE)

# Dangerous bash patterns
DANGEROUS_PATTERNS = [
    r"rm\s+(-\w*r\w*f|-\w*f\w*r|--force.*--recursive|--recursive.*--force)\s+/\s*$",
    r"mkfs\.",
    r"dd\s+.*of=/dev/",
    r">\s*/dev/sd[a-z]",
    r"chmod\s+-R\s+777\s+/\s*$",
]
_dangerous_re = re.compile("|".join(DANGEROUS_PATTERNS))

# Current run_id, set by main.py before the session starts
_run_id: str | None = None


def set_run_id(run_id: str) -> None:
    global _run_id
    _run_id = run_id


def _is_credential_path(path: str) -> bool:
    """Check if a file path matches credential patterns."""
    return bool(_cred_re.search(path))


def _extract_file_path(input_data: dict) -> str | None:
    """Extract file_path from tool input data."""
    return input_data.get("file_path") or input_data.get("path")


def _check_path_confinement(path: str) -> str | None:
    """Returns deny reason if path is outside allowed directories, else None."""
    if not path:
        return None
    norm = os.path.normpath(path)
    # Allow: /workspace (host mount), /home/agentuser/repo (cloned repo), /tmp
    # Use trailing / to prevent prefix tricks (e.g. /workspace-evil matching /workspace)
    allowed_exact = ("/workspace", "/home/agentuser/repo", "/tmp")
    if not any(norm == p or norm.startswith(p + "/") for p in allowed_exact):
        return f"Path '{path}' is outside allowed directories — operations are confined to the repo"
    return None


def _parse_bash_command(input_data: dict) -> str:
    """Extract the command string from a Bash tool call."""
    return input_data.get("command", "")


def _check_git_push(cmd: str) -> str | None:
    """Check git push commands for repo and branch violations. Returns deny reason or None."""
    if "git push" not in cmd and "git remote" not in cmd:
        return None

    # Block adding/changing remotes to non-allowed repos
    if "git remote" in cmd:
        repo = _get_allowed_repo()
        if repo and repo not in cmd:
            return f"Cannot modify git remotes — only {repo} is allowed"

    if "git push" not in cmd:
        return None

    # Block push to protected branches
    for branch in PROTECTED_BRANCHES:
        # Match patterns like: git push origin main, git push -u origin main
        if re.search(rf"git\s+push\s+.*\b{branch}\b", cmd):
            return f"Cannot push directly to protected branch '{branch}' — create a PR instead"

    # Block force push entirely — match -f/--force only as standalone flags preceded
    # by whitespace, not as substrings in branch names like "cool-feature"
    if re.search(r"git\s+push\s+.*(?<=\s)(-f\b|--force\b)", cmd):
        return "Force push is not allowed"

    return None


def _check_dangerous_command(cmd: str) -> str | None:
    """Check for destructive system commands. Returns deny reason or None."""
    if _dangerous_re.search(cmd):
        return "Blocked dangerous system command"
    return None


def _check_repo_exploration(cmd: str) -> str | None:
    """Block commands that try to clone or explore other repos."""
    # Block cloning other repos
    if "git clone" in cmd:
        repo = _get_allowed_repo()
        if repo and repo not in cmd:
            return f"Cannot clone other repositories — stay within {repo}"
        if not repo:
            return "Cannot clone repositories — GITHUB_REPO not configured"

    # Block cd to outside workspace
    cd_match = re.search(r"cd\s+([^\s;&|]+)", cmd)
    if cd_match:
        target = cd_match.group(1)
        if target.startswith("/") and not target.startswith("/workspace"):
            # Allow: repo clone dir, common system paths needed for builds
            allowed_system = ("/home/agentuser/repo", "/tmp", "/usr", "/var", "/etc/apt")
            if not any(target.startswith(p) for p in allowed_system):
                return f"Cannot cd to '{target}' — operations confined to /workspace"

    return None


def _check_token_exposure(cmd: str) -> str | None:
    """Block commands that would print or expose tokens/secrets."""
    _secret_vars = "GIT_TOKEN|ANTHROPIC_API_KEY|GH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN|FGAT_GIT_TOKEN"
    exposure_patterns = [
        rf"echo\s+.*\$\{{?({_secret_vars})",
        r"cat\s+.*\.env",
        rf"printenv\s+({_secret_vars})",
        r"printenv\s*$",
        r"\benv\s*$",
        r"\bset\s*$",
        r"\bexport\s*$",
    ]
    for pattern in exposure_patterns:
        if re.search(pattern, cmd):
            return "Blocked command that would expose credentials"
    return None


async def check_tool_permission(
    tool_name: str,
    input_data: dict,
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    """Main permission callback — every tool call passes through here."""

    deny_reason = None

    # --- File operation tools ---
    if tool_name in ("Read", "Write", "Edit", "Glob", "Grep"):
        path = _extract_file_path(input_data)
        if path:
            # Check credential files
            if _is_credential_path(path):
                deny_reason = f"Access to credential file '{path}' is blocked"

            # Check path confinement
            if not deny_reason:
                deny_reason = _check_path_confinement(path)

    # --- Bash tool ---
    elif tool_name == "Bash":
        cmd = _parse_bash_command(input_data)

        # Check in priority order
        deny_reason = (
            _check_token_exposure(cmd)
            or _check_dangerous_command(cmd)
            or _check_git_push(cmd)
            or _check_repo_exploration(cmd)
        )

    # --- Audit the decision ---
    if _run_id:
        try:
            await db.log_audit(
                _run_id,
                "permission_denied" if deny_reason else "permission_allowed",
                {
                    "tool_name": tool_name,
                    "input_summary": _summarize_input(input_data),
                    "deny_reason": deny_reason,
                },
            )
        except Exception as e:
            print(f"[permissions] Failed to log audit: {e}")

    if deny_reason:
        return PermissionResultDeny(message=deny_reason)

    return PermissionResultAllow(updated_input=input_data)


def _summarize_input(input_data: dict) -> dict:
    """Create a truncated summary of input for audit logging."""
    summary = {}
    for key, value in input_data.items():
        if isinstance(value, str) and len(value) > 500:
            summary[key] = value[:500] + "...[truncated]"
        else:
            summary[key] = value
    return summary
