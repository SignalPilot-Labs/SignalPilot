"""Security gating inside the sandbox container.

SecurityGate enforces minimal access controls. The sandbox is isolated
by gVisor — these rules only protect structural integrity and secrets.

Rules (and why):
1. Branch integrity — orchestrator owns branching, subagents must not switch/create
2. Push integrity — only push to the run's working branch
3. Secret protection — don't leak tokens in stdout (gets logged to DB)
4. Remote/clone protection — stay on configured repo, don't exfiltrate code
5. git clean — protect in-progress work from other subagents
6. Merge integrity — orchestrator owns branch convergence, not subagents
7. GitHub writes — orchestrator owns PR/release/repo writes; reads are fine
8. Secret var refs — block commands that name GIT_TOKEN / GH_TOKEN /
   AGENT_INTERNAL_SECRET, which would enable curl/interpreter exfil
9. /proc/<pid>/environ — block reads; execve snapshot may still contain
   secrets even after os.environ scrub
"""

import logging
import re

from constants import CREDENTIAL_PATTERNS, SECRET_ENV_VARS

log = logging.getLogger("sandbox.security")


class SecurityGate:
    """Minimal permission callback for sandbox tool calls.

    Only blocks operations that would break the orchestrator or leak secrets.
    Everything else is allowed — the sandbox is the sandbox, let it rip.
    """

    def __init__(self, github_repo: str, branch_name: str):
        self._github_repo = github_repo
        self._branch_name = branch_name
        self._cred_re = re.compile("|".join(CREDENTIAL_PATTERNS), re.IGNORECASE)

    def check_permission(
        self, tool_name: str, input_data: dict,
    ) -> str | None:
        """Check a tool call. Returns deny reason or None (allowed)."""
        if tool_name in ("Read", "Write", "Edit", "Glob", "Grep"):
            return self._check_credential_access(input_data)
        if tool_name == "Bash":
            return self._check_bash(input_data.get("command", ""))
        return None

    # ── File Checks ──

    def _check_credential_access(self, input_data: dict) -> str | None:
        """Block access to credential files. No path confinement — sandbox is isolated."""
        path = input_data.get("file_path") or input_data.get("path")
        if not path:
            return None
        if self._cred_re.search(path):
            return f"Access to credential file '{path}' is blocked"
        return None

    # ── Bash Checks ──

    def _check_bash(self, cmd: str) -> str | None:
        """Run bash checks. Blocks anything that could leak secrets, mutate
        remote GitHub state, or rewrite branching outside the working branch."""
        return (
            self._check_token_exposure(cmd)
            or self._check_secret_var_refs(cmd)
            or self._check_proc_environ(cmd)
            or self._check_branch_integrity(cmd)
            or self._check_merge(cmd)
            or self._check_push_target(cmd)
            or self._check_remote_and_clone(cmd)
            or self._check_gh_writes(cmd)
            or self._check_github_api_direct(cmd)
        )

    def _check_token_exposure(self, cmd: str) -> str | None:
        """Block commands that would print secrets to stdout (gets logged)."""
        patterns = [
            rf"echo\s+.*\$\{{?({SECRET_ENV_VARS})",
            r"cat\s+.*\.env",
            rf"printenv\s+({SECRET_ENV_VARS})",
            r"printenv\s*$", r"\benv\s*$", r"\bset\s*$", r"\bexport\s*$",
        ]
        for pattern in patterns:
            if re.search(pattern, cmd):
                return "Blocked command that would expose credentials"
        return None

    def _check_branch_integrity(self, cmd: str) -> str | None:
        """Block branch creation/switching/clean. Orchestrator owns branching."""
        if re.search(r"git\s+checkout\s+-b\b", cmd):
            return "Cannot create branches — the system manages branching"
        if re.search(r"git\s+switch\s+-c\b", cmd):
            return "Cannot create branches — the system manages branching"
        if re.search(r"git\s+branch\s+(?!-)\S", cmd):
            return "Cannot create branches — the system manages branching"
        if re.search(r"git\s+switch\s+(?!-)\S", cmd):
            return "Cannot switch branches — stay on the current branch"
        if re.search(r"git\s+checkout\s+(?!-)\S", cmd) and "--" not in cmd and not re.search(r"git\s+checkout\s+\.", cmd):
            return "Cannot switch branches — use 'git checkout -- <file>' to revert files"
        if re.search(r"git\s+clean\s+-[a-zA-Z]*f", cmd):
            return "git clean -f is blocked — it deletes untracked files permanently"
        return None

    def _check_push_target(self, cmd: str) -> str | None:
        """Block pushes to any branch other than the run's working branch."""
        if not re.search(r"git\s+push", cmd):
            return None
        if not self._branch_name:
            return "git push blocked — no working branch configured"
        if ":" in cmd:
            return "Refspec pushes are blocked — use 'git push origin HEAD'"
        if re.search(rf"origin\s+(HEAD|{re.escape(self._branch_name)})(\s|$)", cmd):
            return None
        return f"Can only push to the working branch '{self._branch_name}' — use 'git push origin HEAD'"

    def _check_remote_and_clone(self, cmd: str) -> str | None:
        """Block remote modifications and cloning other repos."""
        if "git remote" in cmd:
            if self._github_repo and self._github_repo not in cmd:
                return f"Cannot modify git remotes — only {self._github_repo} is allowed"

        if "git clone" in cmd:
            if self._github_repo and self._github_repo not in cmd:
                return f"Cannot clone other repositories — stay within {self._github_repo}"
            if not self._github_repo:
                return "Cannot clone repositories — repo not configured"

        return None

    def _check_merge(self, cmd: str) -> str | None:
        """Block git merge — the orchestrator owns branch convergence.

        Reads like `git merge-base` / `git merge-tree` / `git merge-file`
        are allowed because they don't mutate refs.
        """
        if re.search(r"\bgit\s+merge\b(?!-)", cmd):
            return "git merge is blocked — the orchestrator handles branch convergence"
        return None

    def _check_gh_writes(self, cmd: str) -> str | None:
        """Block `gh` subcommands that mutate GitHub state.

        Read-only commands (`gh pr view`, `gh pr list`, `gh api GET`,
        `gh pr diff`, `gh pr checks`, `gh repo view`) remain allowed —
        subagents may legitimately inspect repo state.
        """
        write_patterns = [
            r"\bgh\s+pr\s+(create|edit|merge|close|reopen|ready|review|comment|lock|unlock)\b",
            r"\bgh\s+release\s+(create|edit|delete|upload|download)\b",
            r"\bgh\s+repo\s+(create|delete|edit|archive|unarchive|rename|fork|clone|sync)\b",
            r"\bgh\s+issue\s+(create|edit|close|reopen|comment|delete|lock|unlock|pin|unpin|transfer)\b",
            r"\bgh\s+workflow\s+(run|enable|disable)\b",
            r"\bgh\s+run\s+(rerun|cancel|delete|watch)\b",
            r"\bgh\s+secret\s+(set|delete|remove)\b",
            r"\bgh\s+variable\s+(set|delete|remove)\b",
            r"\bgh\s+gist\s+(create|edit|delete)\b",
            r"\bgh\s+label\s+(create|edit|delete|clone)\b",
            r"\bgh\s+ruleset\s+(create|edit|delete)\b",
            r"\bgh\s+auth\s+(login|logout|refresh|setup-git|switch|token)\b",
        ]
        for pattern in write_patterns:
            if re.search(pattern, cmd):
                return "gh write commands are blocked — the orchestrator handles GitHub state changes"
        if re.search(r"\bgh\s+api\b", cmd):
            if re.search(r"(-X|--method)\s+(POST|PUT|PATCH|DELETE)\b", cmd, re.IGNORECASE):
                return "gh api write methods (POST/PUT/PATCH/DELETE) are blocked — GET only"
        return None

    def _check_github_api_direct(self, cmd: str) -> str | None:
        """Block direct HTTP clients hitting api.github.com.

        The orchestrator owns all GitHub API writes — a subagent hitting
        api.github.com with curl/wget/httpie would be using the token we
        inject for git auth to bypass `gh` and the `_check_gh_writes` block.
        """
        if re.search(r"\b(curl|wget|http|https|httpie)\b", cmd) and "api.github.com" in cmd:
            return "Direct calls to api.github.com are blocked — the orchestrator handles GitHub API writes"
        return None

    def _check_secret_var_refs(self, cmd: str) -> str | None:
        """Block commands that name our internal secret env vars.

        Catches `curl -H "... $GH_TOKEN"`, `python -c "os.environ['GH_TOKEN']"`,
        `node -e "process.env.GH_TOKEN"`, and similar. The orchestrator owns
        authenticated operations; subagents have no legitimate reason to
        reference these names in a command string.
        """
        for name in ("AGENT_INTERNAL_SECRET", "GH_TOKEN", "GIT_TOKEN"):
            if name in cmd:
                return f"Commands that reference {name} are blocked"
        return None

    def _check_proc_environ(self, cmd: str) -> str | None:
        """Block reads of `/proc/<pid>/environ`.

        Linux freezes each process's env at execve() time in kernel memory;
        Python's `os.environ.pop` doesn't scrub that memory, so the sandbox
        server's original env is still reachable via /proc/1/environ and
        would leak AGENT_INTERNAL_SECRET.
        """
        if re.search(r"/proc/[^/\s]+/environ\b", cmd):
            return "/proc/<pid>/environ is blocked — it can leak credentials"
        return None
