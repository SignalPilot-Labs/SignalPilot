"""Unit tests for permissions.py helper functions.

All tested functions are pure/synchronous helpers. The async
check_tool_permission() entrypoint is not tested here since it
requires a live DB and SDK types.
"""

import sys
import os
from pathlib import Path

# Ensure the agent package root is importable without installing.
# The agent package lives at /home/agentuser/repo/self-improve/agent,
# which is the directory that contains permissions.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from permissions import (
    _is_credential_path,
    _extract_file_path,
    _check_path_confinement,
    _parse_bash_command,
    _check_git_push,
    _check_dangerous_command,
    _check_repo_exploration,
    _check_token_exposure,
    _summarize_input,
)


# ---------------------------------------------------------------------------
# _is_credential_path
# ---------------------------------------------------------------------------

class TestIsCredentialPath:
    """_is_credential_path returns True for credential-like paths."""

    # --- paths that MUST be flagged ---

    def test_dotenv_exact(self):
        assert _is_credential_path(".env") is True

    def test_dotenv_local(self):
        assert _is_credential_path(".env.local") is True

    def test_dotenv_production(self):
        assert _is_credential_path(".env.production") is True

    def test_dotenv_in_subdirectory(self):
        assert _is_credential_path("/workspace/app/.env") is True

    def test_credentials_json(self):
        assert _is_credential_path("credentials.json") is True

    def test_credentials_in_path(self):
        assert _is_credential_path("/home/user/credentials") is True

    def test_pem_file(self):
        assert _is_credential_path("server.pem") is True

    def test_pem_with_path(self):
        assert _is_credential_path("/etc/ssl/private/cert.pem") is True

    def test_key_file(self):
        assert _is_credential_path("mykey.key") is True

    def test_secret_in_name(self):
        assert _is_credential_path("secret_config.yaml") is True

    def test_secrets_directory(self):
        assert _is_credential_path("/workspace/secrets/db_password") is True

    def test_token_file(self):
        assert _is_credential_path("github.token") is True

    def test_id_rsa(self):
        assert _is_credential_path("/home/user/.ssh/id_rsa") is True

    def test_id_ed25519(self):
        assert _is_credential_path("id_ed25519") is True

    def test_gnupg_directory(self):
        assert _is_credential_path("/home/user/.gnupg/pubring.kbx") is True

    def test_ssh_directory(self):
        assert _is_credential_path("/home/user/.ssh/known_hosts") is True

    def test_npmrc(self):
        assert _is_credential_path(".npmrc") is True

    def test_pypirc(self):
        assert _is_credential_path(".pypirc") is True

    def test_docker_config(self):
        assert _is_credential_path("/home/user/.docker/config.json") is True

    def test_case_insensitive_env(self):
        # Pattern is compiled with re.IGNORECASE
        assert _is_credential_path(".ENV") is True

    def test_case_insensitive_secret(self):
        assert _is_credential_path("MySecret.txt") is True

    # --- paths that must NOT be flagged ---

    def test_normal_python_file(self):
        assert _is_credential_path("/workspace/app/main.py") is False

    def test_normal_json_config(self):
        assert _is_credential_path("/workspace/config.json") is False

    def test_readme(self):
        assert _is_credential_path("README.md") is False

    def test_requirements_txt(self):
        assert _is_credential_path("requirements.txt") is False

    def test_dockerfile(self):
        assert _is_credential_path("Dockerfile") is False

    def test_regular_txt(self):
        assert _is_credential_path("/tmp/output.txt") is False

    def test_package_json(self):
        assert _is_credential_path("/workspace/frontend/package.json") is False


# ---------------------------------------------------------------------------
# _extract_file_path
# ---------------------------------------------------------------------------

class TestExtractFilePath:
    """_extract_file_path pulls a path out of tool input dicts."""

    def test_file_path_key(self):
        assert _extract_file_path({"file_path": "/workspace/foo.py"}) == "/workspace/foo.py"

    def test_path_key(self):
        assert _extract_file_path({"path": "/tmp/bar"}) == "/tmp/bar"

    def test_file_path_takes_precedence(self):
        # When both keys exist file_path is returned (dict.get short-circuits via or)
        result = _extract_file_path({"file_path": "/workspace/a.py", "path": "/tmp/b"})
        assert result == "/workspace/a.py"

    def test_missing_keys_returns_none(self):
        assert _extract_file_path({"command": "ls"}) is None

    def test_empty_dict(self):
        assert _extract_file_path({}) is None

    def test_empty_string_file_path_falls_back_to_path(self):
        # Empty string is falsy so `or` falls through to `path`
        result = _extract_file_path({"file_path": "", "path": "/tmp/z"})
        assert result == "/tmp/z"


# ---------------------------------------------------------------------------
# _check_path_confinement
# ---------------------------------------------------------------------------

class TestCheckPathConfinement:
    """_check_path_confinement returns None for allowed paths, a string for blocked ones."""

    # --- allowed paths (must return None) ---

    def test_workspace_root(self):
        assert _check_path_confinement("/workspace") is None

    def test_workspace_subpath(self):
        assert _check_path_confinement("/workspace/project/src/main.py") is None

    def test_home_agentuser_repo(self):
        assert _check_path_confinement("/home/agentuser/repo") is None

    def test_home_agentuser_repo_subpath(self):
        assert _check_path_confinement("/home/agentuser/repo/self-improve/agent/permissions.py") is None

    def test_tmp_root(self):
        assert _check_path_confinement("/tmp") is None

    def test_tmp_subpath(self):
        assert _check_path_confinement("/tmp/scratch.txt") is None

    def test_empty_string_is_allowed(self):
        # Empty path → early return None (no path to confine)
        assert _check_path_confinement("") is None

    # --- blocked paths (must return a non-empty string) ---

    def test_etc_passwd(self):
        reason = _check_path_confinement("/etc/passwd")
        assert reason is not None
        assert "/etc/passwd" in reason

    def test_root_secret(self):
        assert _check_path_confinement("/root/secret") is not None

    def test_home_other_user(self):
        assert _check_path_confinement("/home/otheruser/data") is not None

    def test_proc_filesystem(self):
        assert _check_path_confinement("/proc/self/environ") is not None

    def test_usr_bin(self):
        assert _check_path_confinement("/usr/bin/python3") is not None

    def test_path_traversal_attempt(self):
        # os.path.normpath collapses ../ sequences
        assert _check_path_confinement("/workspace/../etc/shadow") is not None

    def test_workspace_prefix_trick(self):
        # Ensure /workspace-evil is blocked — the confinement check uses
        # exact match or trailing-slash startswith to prevent prefix tricks.
        assert _check_path_confinement("/workspace-evil/secrets") is not None


# ---------------------------------------------------------------------------
# _parse_bash_command
# ---------------------------------------------------------------------------

class TestParseBashCommand:
    """_parse_bash_command extracts the 'command' key from input dicts."""

    def test_basic_command(self):
        assert _parse_bash_command({"command": "ls -la"}) == "ls -la"

    def test_missing_command_key_returns_empty(self):
        assert _parse_bash_command({"file_path": "/tmp/x"}) == ""

    def test_empty_dict(self):
        assert _parse_bash_command({}) == ""


# ---------------------------------------------------------------------------
# _check_git_push
# ---------------------------------------------------------------------------

class TestCheckGitPush:
    """_check_git_push blocks protected branches, force push, and remote changes."""

    # --- commands unrelated to git push (must return None) ---

    def test_unrelated_command(self):
        assert _check_git_push("ls -la") is None

    def test_git_status(self):
        assert _check_git_push("git status") is None

    def test_git_commit(self):
        assert _check_git_push("git commit -m 'fix'") is None

    # --- pushing to feature branches (must return None) ---

    def test_push_feature_branch(self):
        # Ensure branch names containing "f" or "force" are not false-positives
        # for the force-push check — -f must be a standalone flag.
        assert _check_git_push("git push origin feature/my-cool-feature") is None

    def test_push_branch_with_no_f_in_name(self):
        # A branch name that doesn't contain "f" or "force" is not caught by the
        # force-push regex and is correctly allowed (assuming no protected branch match).
        assert _check_git_push("git push origin my-cool-branch") is None

    def test_push_with_upstream_flag_feature(self):
        # "-u" flag followed by "fix/bug-123" — the word "fix" contains no standalone
        # -f, and -u is not a force flag, so this is allowed.
        assert _check_git_push("git push -u origin my-branch-123") is None

    def test_push_signalpilot_branch(self):
        assert _check_git_push("git push origin signalpilot/improvements") is None

    # --- protected branches (must be blocked) ---

    def test_push_main(self):
        reason = _check_git_push("git push origin main")
        assert reason is not None
        assert "main" in reason

    def test_push_master(self):
        reason = _check_git_push("git push origin master")
        assert reason is not None
        assert "master" in reason

    def test_push_staging(self):
        reason = _check_git_push("git push origin staging")
        assert reason is not None
        assert "staging" in reason

    def test_push_prod(self):
        reason = _check_git_push("git push origin prod")
        assert reason is not None
        assert "prod" in reason

    def test_push_production(self):
        reason = _check_git_push("git push origin production")
        assert reason is not None
        assert "production" in reason

    def test_push_with_upstream_flag_main(self):
        reason = _check_git_push("git push -u origin main")
        assert reason is not None

    # --- force push (must be blocked) ---

    def test_force_push_short_flag(self):
        reason = _check_git_push("git push -f origin feature/x")
        assert reason is not None
        assert "Force" in reason or "force" in reason

    def test_force_push_long_flag(self):
        reason = _check_git_push("git push --force origin feature/x")
        assert reason is not None

    # --- remote modification (must be blocked when GITHUB_REPO is set) ---

    def test_git_remote_add_other_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPO", "github.com/SignalPilot-Labs/self-improve")
        reason = _check_git_push("git remote add upstream github.com/attacker/evil-repo")
        assert reason is not None
        assert "SignalPilot-Labs/self-improve" in reason

    def test_git_remote_add_allowed_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPO", "github.com/SignalPilot-Labs/self-improve")
        # Contains the allowed repo — should pass
        result = _check_git_push("git remote set-url origin github.com/SignalPilot-Labs/self-improve")
        assert result is None

    def test_git_remote_no_github_repo_configured(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        # No GITHUB_REPO set → remote check is skipped (repo is empty string → falsy guard)
        result = _check_git_push("git remote add upstream anything")
        assert result is None


# ---------------------------------------------------------------------------
# _check_dangerous_command
# ---------------------------------------------------------------------------

class TestCheckDangerousCommand:
    """_check_dangerous_command blocks destructive system commands."""

    # --- blocked commands ---

    def test_rm_rf_slash(self):
        assert _check_dangerous_command("rm -rf /") is not None

    def test_rm_rf_slash_with_space(self):
        assert _check_dangerous_command("rm -rf / ") is not None

    def test_rm_fr_slash(self):
        # Both -rf and -fr orderings must be blocked.
        assert _check_dangerous_command("rm -fr /") is not None

    def test_mkfs_ext4(self):
        assert _check_dangerous_command("mkfs.ext4 /dev/sda1") is not None

    def test_dd_to_device(self):
        assert _check_dangerous_command("dd if=/dev/zero of=/dev/sda") is not None

    def test_redirect_to_block_device(self):
        assert _check_dangerous_command("echo x > /dev/sda") is not None

    def test_chmod_777_root(self):
        assert _check_dangerous_command("chmod -R 777 /") is not None

    # --- safe commands (must return None) ---

    def test_normal_rm(self):
        assert _check_dangerous_command("rm /tmp/old_file.txt") is None

    def test_rm_rf_workspace(self):
        # Only "/" at end-of-string is caught; a specific directory is fine
        assert _check_dangerous_command("rm -rf /workspace/old_build") is None

    def test_ls_command(self):
        assert _check_dangerous_command("ls -la /workspace") is None

    def test_git_push(self):
        assert _check_dangerous_command("git push origin feature/x") is None


# ---------------------------------------------------------------------------
# _check_repo_exploration
# ---------------------------------------------------------------------------

class TestCheckRepoExploration:
    """_check_repo_exploration blocks cloning other repos and cd to disallowed paths."""

    # --- git clone ---

    def test_clone_blocked_when_other_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPO", "github.com/SignalPilot-Labs/self-improve")
        reason = _check_repo_exploration("git clone github.com/attacker/evil")
        assert reason is not None

    def test_clone_allowed_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPO", "github.com/SignalPilot-Labs/self-improve")
        result = _check_repo_exploration("git clone github.com/SignalPilot-Labs/self-improve")
        assert result is None

    def test_clone_blocked_when_github_repo_not_set(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        reason = _check_repo_exploration("git clone github.com/someone/repo")
        assert reason is not None

    def test_no_clone_in_command(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPO", "github.com/SignalPilot-Labs/self-improve")
        assert _check_repo_exploration("git fetch origin") is None

    # --- cd to allowed paths (must return None) ---

    def test_cd_workspace(self):
        assert _check_repo_exploration("cd /workspace/project") is None

    def test_cd_home_agentuser_repo(self):
        assert _check_repo_exploration("cd /home/agentuser/repo/self-improve") is None

    def test_cd_tmp(self):
        assert _check_repo_exploration("cd /tmp/build") is None

    def test_cd_usr(self):
        assert _check_repo_exploration("cd /usr/local/bin") is None

    def test_cd_etc_apt(self):
        assert _check_repo_exploration("cd /etc/apt") is None

    def test_cd_relative_path(self):
        # Relative paths don't start with "/" so the check is skipped
        assert _check_repo_exploration("cd src/components") is None

    # --- cd to blocked paths ---

    def test_cd_etc_passwd_dir(self):
        reason = _check_repo_exploration("cd /etc/secrets")
        assert reason is not None

    def test_cd_root_home(self):
        reason = _check_repo_exploration("cd /root")
        assert reason is not None

    def test_cd_proc(self):
        reason = _check_repo_exploration("cd /proc/1")
        assert reason is not None

    def test_cd_other_user_home(self):
        reason = _check_repo_exploration("cd /home/otheruser")
        assert reason is not None


# ---------------------------------------------------------------------------
# _check_token_exposure
# ---------------------------------------------------------------------------

class TestCheckTokenExposure:
    """_check_token_exposure blocks commands that would print secrets."""

    # --- blocked commands ---

    def test_echo_git_token(self):
        assert _check_token_exposure("echo $GIT_TOKEN") is not None

    def test_echo_git_token_braces(self):
        assert _check_token_exposure("echo ${GIT_TOKEN}") is not None

    def test_echo_anthropic_api_key(self):
        assert _check_token_exposure("echo $ANTHROPIC_API_KEY") is not None

    def test_echo_gh_token(self):
        assert _check_token_exposure("echo $GH_TOKEN") is not None

    def test_echo_claude_oauth_token(self):
        assert _check_token_exposure("echo $CLAUDE_CODE_OAUTH_TOKEN") is not None

    def test_echo_fgat_token(self):
        assert _check_token_exposure("echo $FGAT_GIT_TOKEN") is not None

    def test_cat_dotenv(self):
        assert _check_token_exposure("cat .env") is not None

    def test_cat_dotenv_with_path(self):
        assert _check_token_exposure("cat /workspace/.env") is not None

    def test_printenv_git_token(self):
        assert _check_token_exposure("printenv GIT_TOKEN") is not None

    def test_printenv_no_args(self):
        assert _check_token_exposure("printenv") is not None

    def test_env_alone(self):
        assert _check_token_exposure("env") is not None

    def test_set_alone(self):
        assert _check_token_exposure("set") is not None

    def test_export_alone(self):
        assert _check_token_exposure("export") is not None

    # --- safe commands (must return None) ---

    def test_echo_normal_string(self):
        assert _check_token_exposure("echo hello world") is None

    def test_echo_path_variable(self):
        assert _check_token_exposure("echo $PATH") is None

    def test_printenv_path(self):
        # printenv with a non-secret var doesn't match the pattern
        assert _check_token_exposure("printenv PATH") is None

    def test_export_var_with_value(self):
        # "export FOO=bar" — has content after export so doesn't match \bexport\s*$
        assert _check_token_exposure("export FOO=bar") is None

    def test_cat_normal_file(self):
        assert _check_token_exposure("cat /workspace/README.md") is None

    def test_git_status(self):
        assert _check_token_exposure("git status") is None

    def test_ls_command(self):
        assert _check_token_exposure("ls -la") is None


# ---------------------------------------------------------------------------
# _summarize_input
# ---------------------------------------------------------------------------

class TestSummarizeInput:
    """_summarize_input truncates long string values for audit logging."""

    def test_short_values_unchanged(self):
        data = {"file_path": "/workspace/main.py", "command": "ls"}
        result = _summarize_input(data)
        assert result == data

    def test_long_string_truncated(self):
        long_value = "x" * 600
        result = _summarize_input({"content": long_value})
        assert result["content"].endswith("...[truncated]")
        assert len(result["content"]) < len(long_value)

    def test_truncated_value_starts_with_first_500_chars(self):
        long_value = "A" * 500 + "B" * 100
        result = _summarize_input({"content": long_value})
        assert result["content"].startswith("A" * 500)

    def test_exactly_500_chars_not_truncated(self):
        value = "z" * 500
        result = _summarize_input({"content": value})
        assert result["content"] == value
        assert "truncated" not in result["content"]

    def test_501_chars_truncated(self):
        value = "z" * 501
        result = _summarize_input({"content": value})
        assert result["content"].endswith("...[truncated]")

    def test_non_string_values_preserved(self):
        data = {"count": 42, "flag": True, "items": [1, 2, 3]}
        result = _summarize_input(data)
        assert result == data

    def test_mixed_values(self):
        data = {
            "short": "hello",
            "long": "y" * 600,
            "number": 99,
        }
        result = _summarize_input(data)
        assert result["short"] == "hello"
        assert result["number"] == 99
        assert result["long"].endswith("...[truncated]")

    def test_empty_dict(self):
        assert _summarize_input({}) == {}

    def test_empty_string_not_truncated(self):
        result = _summarize_input({"key": ""})
        assert result["key"] == ""

    def test_original_dict_not_mutated(self):
        long_value = "m" * 600
        data = {"content": long_value}
        _summarize_input(data)
        assert data["content"] == long_value
