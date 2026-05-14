"""Sandbox constants loaded from config.yml."""

import re

from config.loader import sandbox_config, security_config

_cfg = sandbox_config()
_security_cfg = security_config()

# ── Execution ──
CMD_TIMEOUT: int = _cfg.get("exec_timeout_sec", 120)
SANDBOX_PORT: int = 8080
SANDBOX_HOST: str = "0.0.0.0"

# ── Security ──
INTERNAL_SECRET_HEADER: str = "X-Internal-Secret"
INTERNAL_SECRET_ENV_VAR: str = "AGENT_INTERNAL_SECRET"

CREDENTIAL_PATTERNS: list[str] = _security_cfg.get("credential_patterns", [])
SECRET_ENV_VARS: str = _security_cfg.get("secret_env_vars", "")

# ── Session ──
MAX_CONCURRENT_SESSIONS: int = _cfg.get("max_concurrent_sessions", 5)
SESSION_EVENT_QUEUE_SIZE: int = _cfg.get("session_event_queue_size", 1000)

# ── Time Lock ──
EARLY_EXIT_THRESHOLD_MIN: float = 5.0  # Allow end_session when < 5 min remain
SECONDS_PER_MINUTE: int = 60

INPUT_SUMMARY_MAX_LEN: int = 1000
INPUT_CONTENT_MAX_LEN: int = 3000

# ── Subagent Attribution ──
# Tool name the SDK reports for Task subagent invocations. The hook's
# PreToolUse fires with this name immediately before SubagentStart, and
# its tool_use_id is the parent link the SubagentStart payload lacks.
TASK_TOOL_NAME: str = "Agent"

# ── Filesystem API ──
# Max file size the /file_system/read endpoint will return. Larger files
# must be streamed via /exec + tail/head or split before reading.
FS_READ_MAX_BYTES: int = 2 * 1024 * 1024

# ── Retry (transient network errors on git/gh commands) ──
RETRY_MAX_ATTEMPTS: int = 3
RETRY_BASE_DELAY_SEC: float = 2.0
RETRY_TRANSIENT_PATTERNS: tuple[str, ...] = (
    "error connecting",
    "connection refused",
    "connection reset",
    "timed out",
    "could not resolve",
)

# ── Repo handlers ──
REPO_WORK_DIR: str = "/home/agentuser/repo"
REPO_BRANCH_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_./]*$")
REPO_BRANCH_NAME_MAX_LEN: int = 256

# Inline shell credential helper: reads $GIT_TOKEN at the moment git
# invokes it. Secret lives in process memory only — never on disk.
GIT_CREDENTIAL_HELPER: str = (
    '!f() { echo "username=x-access-token"; echo "password=${GIT_TOKEN}"; }; f'
)
