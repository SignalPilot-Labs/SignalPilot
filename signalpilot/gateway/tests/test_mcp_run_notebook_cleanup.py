"""F-17: Gate tests for MCP run_notebook cleanup restructure (Option A).

Verifies that:
1. When create_jwt_secret_with_owner_ref raises, delete_pod is NOT called
   (helper owns its own cleanup — calling it again causes a redundant 404).
2. When the helper succeeds but wait_for_running/wait_for_ready raises, delete_pod
   IS called exactly once (pod exists, caller owns cleanup).

Inject → fail → revert → pass pattern:
  - test_helper_failure_does_not_double_delete: re-add delete_pod call in the
    helper-except block → await_count == 1 → assertion `== 0` fails.
  - test_readiness_failure_deletes_pod_once: remove delete_pod from the outer-try
    except block → await_count == 0 → assertion `== 1` fails.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_run_notebook_deps(
    *,
    helper_raises: Exception | None = None,
    wait_raises: Exception | None = None,
) -> tuple[MagicMock, dict]:
    """Build the minimal set of mocks needed to reach the pod-creation path.

    Returns (mock_orch, patch_map) where patch_map is passed to patch().
    """
    mock_orch = MagicMock()
    mock_orch._ensure_client = AsyncMock()
    mock_orch._namespace_prefix = "sp-nb"
    mock_orch._core_api = MagicMock()
    mock_orch.create_pod = AsyncMock(return_value=MagicMock())
    mock_orch.delete_pod = AsyncMock()
    mock_orch.get_pod = AsyncMock(return_value=MagicMock(ip="10.0.0.1"))
    mock_orch.is_pod_alive = AsyncMock(return_value=False)  # Force new pod creation

    if wait_raises is not None:
        mock_orch.wait_for_running = AsyncMock(side_effect=wait_raises)
        mock_orch.wait_for_ready = AsyncMock()
    else:
        mock_orch.wait_for_running = AsyncMock()
        mock_orch.wait_for_ready = AsyncMock()

    if helper_raises is not None:
        helper_mock = AsyncMock(side_effect=helper_raises)
    else:
        helper_mock = AsyncMock()

    return mock_orch, helper_mock


def _setup_notebook_monkeypatches(monkeypatch, mock_orch: MagicMock) -> None:
    """Apply monkeypatches to notebook module for org/user context vars."""
    import gateway.mcp.tools.notebook as nb_mod

    monkeypatch.setattr(nb_mod, "mcp_org_id_var", MagicMock(get=lambda default: "test-org"))
    monkeypatch.setattr(nb_mod, "mcp_user_id_var", MagicMock(get=lambda default: "test-user"))


def _make_store_ctx(project_name: str = "myproject") -> MagicMock:
    """Return a mock async context manager for _store_session."""
    mock_project = MagicMock()
    mock_project.name = project_name

    mock_store = AsyncMock()
    mock_store.get_workspace_project = AsyncMock(return_value=mock_project)

    store_ctx = MagicMock()
    store_ctx.__aenter__ = AsyncMock(return_value=mock_store)
    store_ctx.__aexit__ = AsyncMock(return_value=False)
    return store_ctx


def _make_db_session_ctx() -> AsyncMock:
    """Return a mock async context manager for the DB session factory."""
    mock_db_session = AsyncMock()
    mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_db_session.__aexit__ = AsyncMock(return_value=False)
    return mock_db_session


class TestHelperFailureDoesNotDoubleDelete:
    """When create_jwt_secret_with_owner_ref raises, delete_pod must NOT be called.

    The helper already deletes Pod + Secret on its own failure path (jwt_secret_lifecycle.py).
    Calling delete_pod again causes a redundant 404 API call and a spurious log warning.
    """

    @pytest.mark.asyncio
    async def test_helper_failure_does_not_double_delete(self, monkeypatch):
        """delete_pod.await_count == 0 when the helper raises.

        Inject demo: re-add `await orch.delete_pod(pod_name, org_id=org_id)` inside
        the inner except block → await_count becomes 1 → assertion `== 0` fails.
        """
        mock_orch, helper_mock = _make_run_notebook_deps(
            helper_raises=RuntimeError("boom — simulated helper failure"),
        )

        _setup_notebook_monkeypatches(monkeypatch, mock_orch)

        import gateway.mcp.tools.notebook as nb_mod

        store_ctx = _make_store_ctx()
        monkeypatch.setattr(nb_mod, "_store_session", MagicMock(return_value=store_ctx))

        mock_db_session = _make_db_session_ctx()

        with (
            patch("gateway.git.repos.repo_exists", return_value=True),
            patch("gateway.git.repos.repo_path", return_value="/fake/repo"),
            patch("gateway.git.repos._run_git", return_value=(0, "", "")),
            patch("gateway.db.engine.get_session_factory", return_value=MagicMock(return_value=mock_db_session)),
            patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=mock_orch),
            patch("gateway.store.notebook_sessions.get_active_session", AsyncMock(return_value=None)),
            patch("gateway.store.notebook_sessions.create_session", AsyncMock(return_value=MagicMock(id="sess-1", access_token="tok"))),
            patch("gateway.store.notebook_sessions.delete_stopped", AsyncMock()),
            patch("gateway.store.notebook_sessions.update_session_status", AsyncMock()),
            patch("gateway.auth.notebook_jwt.mint_session_jwt", return_value="fake.jwt"),
            patch("gateway.config.k8s.get_k8s_settings", return_value=MagicMock(
                sp_session_jwt_ttl_seconds=3600,
                sp_public_gateway_url="http://gw",
            )),
            patch("gateway.orchestrator.namespaces.namespace_for_org", return_value="sp-nb-testorg"),
            patch(
                "gateway.orchestrator.jwt_secret_lifecycle.create_jwt_secret_with_owner_ref",
                helper_mock,
            ),
        ):
            from gateway.mcp.tools.notebook import run_notebook

            result = await run_notebook(
                filename="analysis.py",
                code="x = 1",
                project_id="proj-123",
                agent_branch="signalpilot-agent/abc123",
            )

        assert "Error starting notebook pod" in result, (
            f"Expected error message from helper failure, got: {result!r}"
        )
        assert mock_orch.delete_pod.await_count == 0, (
            f"delete_pod must NOT be called when the helper raises (helper owns cleanup). "
            f"await_count was {mock_orch.delete_pod.await_count}. "
            "Inject demo: add `await orch.delete_pod(...)` in the inner except → count becomes 1 → fails."
        )


class TestReadinessFailureDeletesPodOnce:
    """When the helper succeeds but wait_for_running raises, delete_pod is called exactly once.

    The pod exists at this point (helper returned cleanly); the caller owns cleanup.
    """

    @pytest.mark.asyncio
    async def test_readiness_failure_deletes_pod_once(self, monkeypatch):
        """delete_pod.await_count == 1 when wait_for_running raises after helper succeeds.

        Inject demo: remove `await orch.delete_pod(pod_name, org_id=org_id)` from the
        outer-try except block → await_count becomes 0 → assertion `== 1` fails.
        """
        mock_orch, helper_mock = _make_run_notebook_deps(
            helper_raises=None,
            wait_raises=TimeoutError("pod did not start in time"),
        )

        _setup_notebook_monkeypatches(monkeypatch, mock_orch)

        import gateway.mcp.tools.notebook as nb_mod

        store_ctx = _make_store_ctx()
        monkeypatch.setattr(nb_mod, "_store_session", MagicMock(return_value=store_ctx))

        mock_db_session = _make_db_session_ctx()

        with (
            patch("gateway.git.repos.repo_exists", return_value=True),
            patch("gateway.git.repos.repo_path", return_value="/fake/repo"),
            patch("gateway.git.repos._run_git", return_value=(0, "", "")),
            patch("gateway.db.engine.get_session_factory", return_value=MagicMock(return_value=mock_db_session)),
            patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=mock_orch),
            patch("gateway.store.notebook_sessions.get_active_session", AsyncMock(return_value=None)),
            patch("gateway.store.notebook_sessions.create_session", AsyncMock(return_value=MagicMock(id="sess-1", access_token="tok"))),
            patch("gateway.store.notebook_sessions.delete_stopped", AsyncMock()),
            patch("gateway.store.notebook_sessions.update_session_status", AsyncMock()),
            patch("gateway.auth.notebook_jwt.mint_session_jwt", return_value="fake.jwt"),
            patch("gateway.config.k8s.get_k8s_settings", return_value=MagicMock(
                sp_session_jwt_ttl_seconds=3600,
                sp_public_gateway_url="http://gw",
            )),
            patch("gateway.orchestrator.namespaces.namespace_for_org", return_value="sp-nb-testorg"),
            patch(
                "gateway.orchestrator.jwt_secret_lifecycle.create_jwt_secret_with_owner_ref",
                helper_mock,
            ),
        ):
            from gateway.mcp.tools.notebook import run_notebook

            result = await run_notebook(
                filename="analysis.py",
                code="x = 1",
                project_id="proj-123",
                agent_branch="signalpilot-agent/abc123",
            )

        assert "Error starting notebook pod" in result, (
            f"Expected error message from readiness failure, got: {result!r}"
        )
        assert mock_orch.delete_pod.await_count == 1, (
            f"delete_pod must be called exactly once when readiness wait fails (pod is live, caller owns cleanup). "
            f"await_count was {mock_orch.delete_pod.await_count}. "
            "Inject demo: remove `await orch.delete_pod(...)` from the outer except → count becomes 0 → fails."
        )
