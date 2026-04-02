"""Tests for the permission security module.

These tests verify the security-critical permission checks that gate
every tool call in the self-improvement agent.
"""

import os
import pytest

from agent import permissions


# === Credential path detection ===

class TestCredentialPaths:
    def test_blocks_env_file(self):
        assert permissions._is_credential_path("/workspace/.env")

    def test_blocks_env_local(self):
        assert permissions._is_credential_path("/workspace/.env.local")

    def test_blocks_pem_file(self):
        assert permissions._is_credential_path("/workspace/server.pem")

    def test_blocks_key_file(self):
        assert permissions._is_credential_path("/workspace/private.key")

    def test_blocks_ssh_dir(self):
        assert permissions._is_credential_path("/home/user/.ssh/id_rsa")

    def test_blocks_npmrc(self):
        assert permissions._is_credential_path("/home/user/.npmrc")

    def test_blocks_credentials_file(self):
        assert permissions._is_credential_path("/workspace/credentials.json")

    def test_allows_normal_python(self):
        assert not permissions._is_credential_path("/workspace/main.py")

    def test_allows_normal_config(self):
        assert not permissions._is_credential_path("/workspace/config.yaml")

    def test_allows_env_in_name(self):
        # "environment.py" should NOT be blocked (no .env pattern match)
        assert not permissions._is_credential_path("/workspace/environment.py")


# === Path confinement ===

class TestPathConfinement:
    def test_allows_workspace(self):
        assert permissions._check_path_confinement("/workspace/src/main.py") is None

    def test_allows_repo(self):
        assert permissions._check_path_confinement("/home/agentuser/repo/file.py") is None

    def test_allows_tmp(self):
        assert permissions._check_path_confinement("/tmp/build/output") is None

    def test_blocks_etc(self):
        result = permissions._check_path_confinement("/etc/passwd")
        assert result is not None
        assert "outside allowed" in result

    def test_blocks_root(self):
        result = permissions._check_path_confinement("/root/.bashrc")
        assert result is not None

    def test_blocks_var(self):
        result = permissions._check_path_confinement("/var/log/syslog")
        assert result is not None

    def test_empty_path_allowed(self):
        assert permissions._check_path_confinement("") is None

    def test_traversal_blocked(self):
        # normpath resolves ../.. but /workspace/../../etc/passwd -> /etc/passwd
        result = permissions._check_path_confinement("/workspace/../../etc/passwd")
        assert result is not None


# === Git push checks ===

class TestGitPushChecks:
    def test_blocks_push_to_main(self):
        result = permissions._check_git_push("git push origin main")
        assert result is not None
        assert "protected" in result.lower()

    def test_blocks_push_to_master(self):
        result = permissions._check_git_push("git push origin master")
        assert result is not None

    def test_blocks_push_to_staging(self):
        result = permissions._check_git_push("git push origin staging")
        assert result is not None

    def test_blocks_force_push(self):
        result = permissions._check_git_push("git push -f origin feature-branch")
        assert result is not None
        assert "force" in result.lower()

    def test_blocks_force_push_long(self):
        result = permissions._check_git_push("git push --force origin feature-branch")
        assert result is not None

    def test_allows_push_to_feature_branch(self):
        result = permissions._check_git_push("git push origin feature/my-branch")
        assert result is None

    def test_allows_push_with_upstream(self):
        result = permissions._check_git_push("git push -u origin signalpilot/improvements-123")
        assert result is None

    def test_non_push_command_allowed(self):
        result = permissions._check_git_push("git status")
        assert result is None


# === Dangerous command checks ===

class TestDangerousCommands:
    def test_blocks_rm_rf_root(self):
        result = permissions._check_dangerous_command("rm -rf /")
        assert result is not None

    def test_blocks_mkfs(self):
        result = permissions._check_dangerous_command("mkfs.ext4 /dev/sda1")
        assert result is not None

    def test_blocks_dd_to_device(self):
        result = permissions._check_dangerous_command("dd if=/dev/zero of=/dev/sda")
        assert result is not None

    def test_allows_normal_rm(self):
        result = permissions._check_dangerous_command("rm /workspace/temp.txt")
        assert result is None

    def test_allows_rm_rf_workspace(self):
        # Removing workspace subdirectories is OK
        result = permissions._check_dangerous_command("rm -rf /workspace/node_modules")
        assert result is None


# === Token exposure checks ===

class TestTokenExposure:
    def test_blocks_echo_git_token(self):
        result = permissions._check_token_exposure("echo $GIT_TOKEN")
        assert result is not None

    def test_blocks_printenv_all(self):
        result = permissions._check_token_exposure("printenv")
        assert result is not None

    def test_blocks_env_command(self):
        result = permissions._check_token_exposure("env")
        assert result is not None

    def test_blocks_cat_env_file(self):
        result = permissions._check_token_exposure("cat .env")
        assert result is not None

    def test_allows_echo_normal(self):
        result = permissions._check_token_exposure("echo hello world")
        assert result is None

    def test_allows_printenv_path(self):
        result = permissions._check_token_exposure("printenv PATH")
        assert result is None


# === Repo exploration checks ===

class TestRepoExploration:
    def test_blocks_cd_to_system(self):
        result = permissions._check_repo_exploration("cd /opt/other-repo")
        assert result is not None

    def test_allows_cd_to_workspace(self):
        result = permissions._check_repo_exploration("cd /workspace/src")
        assert result is None

    def test_allows_cd_to_tmp(self):
        result = permissions._check_repo_exploration("cd /tmp/build")
        assert result is None

    def test_allows_cd_to_usr(self):
        result = permissions._check_repo_exploration("cd /usr/local/bin")
        assert result is None


# === Input summarization ===

class TestSummarizeInput:
    def test_truncates_long_strings(self):
        data = {"command": "x" * 1000}
        result = permissions._summarize_input(data)
        assert len(result["command"]) < 1000
        assert "[truncated]" in result["command"]

    def test_preserves_short_strings(self):
        data = {"file_path": "/workspace/main.py"}
        result = permissions._summarize_input(data)
        assert result["file_path"] == "/workspace/main.py"

    def test_preserves_non_string_values(self):
        data = {"timeout": 120, "verbose": True}
        result = permissions._summarize_input(data)
        assert result["timeout"] == 120
        assert result["verbose"] is True
