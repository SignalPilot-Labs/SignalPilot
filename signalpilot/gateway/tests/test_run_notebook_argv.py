"""F-4: Tests for run_notebook argv safety and shell injection elimination.

Covers:
- Filename regex: rejects metacharacters and path traversal.
- Branch regex: rejects leading-dash branches.
- No sh -c in any exec call.
- Code with heredoc markers is safely forwarded as stdin_bytes to tee.
- Git commands use argv (no shell).
- Missing project directory returns error (no find fallback).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.mcp.tools.notebook import _validate_branch, _validate_filename


class TestFilenameRegex:
    """_validate_filename rejects unsafe filenames."""

    def test_valid_filename_accepted(self):
        assert _validate_filename("analysis.py") is None

    def test_valid_filename_with_dots_and_dashes(self):
        assert _validate_filename("my-analysis_v2.0.py") is None

    def test_filename_rejects_shell_metachars(self):
        assert _validate_filename("a; rm -rf /.py") is not None

    def test_filename_rejects_path_traversal(self):
        assert _validate_filename("../../etc/passwd.py") is not None

    def test_filename_rejects_slash(self):
        assert _validate_filename("dir/file.py") is not None

    def test_filename_rejects_no_extension(self):
        assert _validate_filename("nopyextension") is not None

    def test_filename_rejects_wrong_extension(self):
        assert _validate_filename("script.sh") is not None

    def test_filename_rejects_backtick(self):
        assert _validate_filename("`rm -rf /`.py") is not None

    def test_filename_rejects_dollar(self):
        assert _validate_filename("$(id).py") is not None

    def test_filename_rejects_space(self):
        assert _validate_filename("my file.py") is not None


class TestBranchRegex:
    """_validate_branch rejects unsafe branch names."""

    def test_valid_branch_accepted(self):
        assert _validate_branch("signalpilot-agent/abc123") is None

    def test_valid_simple_branch(self):
        assert _validate_branch("main") is None

    def test_branch_rejects_leading_dash(self):
        assert _validate_branch("-foo") is not None

    def test_branch_rejects_empty(self):
        assert _validate_branch("") is not None

    def test_branch_rejects_semicolon(self):
        assert _validate_branch("main;rm -rf /") is not None

    def test_branch_rejects_dollar(self):
        assert _validate_branch("$(id)") is not None

    def test_branch_rejects_backtick(self):
        assert _validate_branch("`id`") is not None

    def test_branch_rejects_space(self):
        assert _validate_branch("my branch") is not None


class TestNoShellCInExecCalls:
    """run_notebook must never pass ["sh", "-c", ...] to exec_in_pod."""

    @pytest.mark.asyncio
    async def test_no_shell_c_in_exec_calls(self, monkeypatch):
        """All exec calls must use direct argv — no ["sh", "-c", ...] sequences."""
        recorded_calls: list[dict] = []

        async def mock_exec_in_pod(pod_name, *, org_id, argv, timeout=300, stdin_bytes=None):
            recorded_calls.append({"argv": argv, "stdin_bytes": stdin_bytes})
            # Simulate successful execution
            return ("", "", 0)

        # Mock all required dependencies
        mock_orch = MagicMock()
        mock_orch.exec_in_pod = mock_exec_in_pod
        mock_orch.is_pod_alive = AsyncMock(return_value=True)

        mock_existing_session = MagicMock()
        mock_existing_session.status = "running"
        mock_existing_session.pod_name = "nb-testpod"
        mock_existing_session.id = "sess-test"

        mock_project = MagicMock()
        mock_project.name = "myproject"

        mock_store = AsyncMock()
        mock_store.get_workspace_project = AsyncMock(return_value=mock_project)

        import gateway.mcp.tools.notebook as nb_mod

        monkeypatch.setattr(nb_mod, "mcp_org_id_var", MagicMock(get=lambda default: "test-org"))
        monkeypatch.setattr(nb_mod, "mcp_user_id_var", MagicMock(get=lambda default: "test-user"))

        # Patch _store_session context manager
        store_ctx = MagicMock()
        store_ctx.__aenter__ = AsyncMock(return_value=mock_store)
        store_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(nb_mod, "_store_session", MagicMock(return_value=store_ctx))

        # Patch git operations
        mock_repo_exists = MagicMock(return_value=True)
        mock_repo_path = MagicMock(return_value="/fake/repo")
        mock_run_git = MagicMock(return_value=(0, "", ""))

        from gateway.db.engine import get_session_factory
        from gateway.orchestrator.kubernetes import KubernetesOrchestrator
        from gateway.store import notebook_sessions as ns

        mock_factory = MagicMock()
        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_db_session

        with patch("gateway.git.repos.repo_exists", mock_repo_exists), \
             patch("gateway.git.repos.repo_path", mock_repo_path), \
             patch("gateway.git.repos._run_git", mock_run_git), \
             patch("gateway.db.engine.get_session_factory", return_value=mock_factory), \
             patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=mock_orch), \
             patch("gateway.store.notebook_sessions.get_active_session", AsyncMock(return_value=mock_existing_session)):

            from gateway.mcp.tools.notebook import run_notebook

            await run_notebook(
                filename="analysis.py",
                code="x = 1\nprint(x)",
                project_id="proj-123",
                agent_branch="signalpilot-agent/abc123",
            )

        # Verify no sh -c calls were made
        for call in recorded_calls:
            argv = call["argv"]
            assert not (
                len(argv) >= 2 and argv[0] == "sh" and argv[1] == "-c"
            ), f"sh -c found in exec call: {argv}"

    @pytest.mark.asyncio
    async def test_code_with_heredoc_marker_safe(self, monkeypatch):
        """Code containing heredoc markers is forwarded as stdin_bytes to tee, not shell-interpolated."""
        recorded_calls: list[dict] = []

        async def mock_exec_in_pod(pod_name, *, org_id, argv, timeout=300, stdin_bytes=None):
            recorded_calls.append({"argv": argv, "stdin_bytes": stdin_bytes})
            return ("", "", 0)

        mock_orch = MagicMock()
        mock_orch.exec_in_pod = mock_exec_in_pod
        mock_orch.is_pod_alive = AsyncMock(return_value=True)

        mock_existing_session = MagicMock()
        mock_existing_session.status = "running"
        mock_existing_session.pod_name = "nb-testpod"
        mock_existing_session.id = "sess-test"

        mock_project = MagicMock()
        mock_project.name = "myproject"

        mock_store = AsyncMock()
        mock_store.get_workspace_project = AsyncMock(return_value=mock_project)

        import gateway.mcp.tools.notebook as nb_mod

        monkeypatch.setattr(nb_mod, "mcp_org_id_var", MagicMock(get=lambda default: "test-org"))
        monkeypatch.setattr(nb_mod, "mcp_user_id_var", MagicMock(get=lambda default: "test-user"))

        store_ctx = MagicMock()
        store_ctx.__aenter__ = AsyncMock(return_value=mock_store)
        store_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(nb_mod, "_store_session", MagicMock(return_value=store_ctx))

        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=False)

        dangerous_code = "x\nSPEOF\nrm -rf /\n"

        with patch("gateway.git.repos.repo_exists", return_value=True), \
             patch("gateway.git.repos.repo_path", return_value="/fake/repo"), \
             patch("gateway.git.repos._run_git", return_value=(0, "", "")), \
             patch("gateway.db.engine.get_session_factory", return_value=MagicMock(return_value=mock_db_session)), \
             patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=mock_orch), \
             patch("gateway.store.notebook_sessions.get_active_session", AsyncMock(return_value=mock_existing_session)):

            from gateway.mcp.tools.notebook import run_notebook

            await run_notebook(
                filename="analysis.py",
                code=dangerous_code,
                project_id="proj-123",
                agent_branch="signalpilot-agent/abc123",
            )

        # Find the tee call and verify code was passed as stdin_bytes
        tee_calls = [c for c in recorded_calls if c["argv"] and c["argv"][0] == "tee"]
        assert tee_calls, f"No tee call found; calls were: {[c['argv'] for c in recorded_calls]}"
        tee_call = tee_calls[0]
        assert tee_call["stdin_bytes"] == dangerous_code.encode("utf-8")
        # Verify argv is ["tee", "<path>"] not ["sh", "-c", ...]
        assert tee_call["argv"][0] == "tee"
        assert len(tee_call["argv"]) == 2


class TestGitCommandsUseArgv:
    """Git commit/push commands must use argv form with -C flag."""

    @pytest.mark.asyncio
    async def test_git_commands_use_argv(self, monkeypatch):
        """git add, commit, push must be separate exec calls using -C flag, no sh -c."""
        recorded_calls: list[dict] = []

        async def mock_exec_in_pod(pod_name, *, org_id, argv, timeout=300, stdin_bytes=None):
            recorded_calls.append({"argv": argv})
            return ("", "", 0)

        mock_orch = MagicMock()
        mock_orch.exec_in_pod = mock_exec_in_pod
        mock_orch.is_pod_alive = AsyncMock(return_value=True)

        mock_existing_session = MagicMock()
        mock_existing_session.status = "running"
        mock_existing_session.pod_name = "nb-testpod"
        mock_existing_session.id = "sess-test"

        mock_project = MagicMock()
        mock_project.name = "myproject"

        mock_store = AsyncMock()
        mock_store.get_workspace_project = AsyncMock(return_value=mock_project)

        import gateway.mcp.tools.notebook as nb_mod

        monkeypatch.setattr(nb_mod, "mcp_org_id_var", MagicMock(get=lambda default: "test-org"))
        monkeypatch.setattr(nb_mod, "mcp_user_id_var", MagicMock(get=lambda default: "test-user"))

        store_ctx = MagicMock()
        store_ctx.__aenter__ = AsyncMock(return_value=mock_store)
        store_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(nb_mod, "_store_session", MagicMock(return_value=store_ctx))

        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=False)

        with patch("gateway.git.repos.repo_exists", return_value=True), \
             patch("gateway.git.repos.repo_path", return_value="/fake/repo"), \
             patch("gateway.git.repos._run_git", return_value=(0, "", "")), \
             patch("gateway.db.engine.get_session_factory", return_value=MagicMock(return_value=mock_db_session)), \
             patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=mock_orch), \
             patch("gateway.store.notebook_sessions.get_active_session", AsyncMock(return_value=mock_existing_session)):

            from gateway.mcp.tools.notebook import run_notebook

            await run_notebook(
                filename="analysis.py",
                code="x = 1",
                project_id="proj-123",
                agent_branch="signalpilot-agent/abc123",
            )

        git_calls = [c for c in recorded_calls if c["argv"] and c["argv"][0] == "git"]
        # Should have 3 git calls: add, commit, push
        assert len(git_calls) >= 3, f"Expected at least 3 git calls, got: {[c['argv'] for c in git_calls]}"

        add_calls = [c for c in git_calls if "-C" in c["argv"] and "add" in c["argv"]]
        commit_calls = [c for c in git_calls if "-C" in c["argv"] and "commit" in c["argv"]]
        push_calls = [c for c in git_calls if "-C" in c["argv"] and "push" in c["argv"]]

        assert add_calls, "Expected git add -C call"
        assert commit_calls, "Expected git commit -C call"
        assert push_calls, "Expected git push -C call"

        # Verify push uses refs/heads/ notation
        push_argv = push_calls[0]["argv"]
        assert "origin" in push_argv
        refs_arg = [a for a in push_argv if "refs/heads/" in a]
        assert refs_arg, f"Expected refs/heads/ in push argv: {push_argv}"


class TestProjectDirNoFindFallback:
    """Missing project directory returns an error — no find fallback."""

    @pytest.mark.asyncio
    async def test_project_dir_missing_returns_error(self, monkeypatch):
        """When project dir doesn't exist in pod, returns an error string (no find)."""
        exec_calls: list[list[str]] = []

        async def mock_exec_in_pod(pod_name, *, org_id, argv, timeout=300, stdin_bytes=None):
            exec_calls.append(argv)
            if argv[0] == "test" and "-d" in argv:
                # Project dir not found
                return ("", "", 1)
            return ("", "", 0)

        mock_orch = MagicMock()
        mock_orch.exec_in_pod = mock_exec_in_pod
        mock_orch.is_pod_alive = AsyncMock(return_value=True)

        mock_existing_session = MagicMock()
        mock_existing_session.status = "running"
        mock_existing_session.pod_name = "nb-testpod"
        mock_existing_session.id = "sess-test"

        mock_project = MagicMock()
        mock_project.name = "myproject"

        mock_store = AsyncMock()
        mock_store.get_workspace_project = AsyncMock(return_value=mock_project)

        import gateway.mcp.tools.notebook as nb_mod

        monkeypatch.setattr(nb_mod, "mcp_org_id_var", MagicMock(get=lambda default: "test-org"))
        monkeypatch.setattr(nb_mod, "mcp_user_id_var", MagicMock(get=lambda default: "test-user"))

        store_ctx = MagicMock()
        store_ctx.__aenter__ = AsyncMock(return_value=mock_store)
        store_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(nb_mod, "_store_session", MagicMock(return_value=store_ctx))

        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=False)

        with patch("gateway.git.repos.repo_exists", return_value=True), \
             patch("gateway.git.repos.repo_path", return_value="/fake/repo"), \
             patch("gateway.git.repos._run_git", return_value=(0, "", "")), \
             patch("gateway.db.engine.get_session_factory", return_value=MagicMock(return_value=mock_db_session)), \
             patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=mock_orch), \
             patch("gateway.store.notebook_sessions.get_active_session", AsyncMock(return_value=mock_existing_session)):

            from gateway.mcp.tools.notebook import run_notebook

            result = await run_notebook(
                filename="analysis.py",
                code="x = 1",
                project_id="proj-123",
                agent_branch="signalpilot-agent/abc123",
            )

        assert "Error" in result or "error" in result.lower(), (
            f"Expected error when project dir is missing, got: {result!r}"
        )
        # Verify no `find` command was called
        find_calls = [c for c in exec_calls if c and c[0] == "find"]
        assert not find_calls, f"find was called despite removal of find fallback: {find_calls}"
