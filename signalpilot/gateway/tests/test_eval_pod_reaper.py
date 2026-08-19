"""Tests for reap_terminal_eval_pods (gateway/evals/backends.py).

The reaper removes eval pods stranded in a terminal phase by a gateway
restart. It must skip running pods, respect the age cap, delete the env
Secret with the pod, and swallow listing/permission failures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.evals.backends import reap_terminal_eval_pods


def _pod(name: str, phase: str, age_seconds: int, ns: str = "sp-nb-org1") -> dict:
    return {
        "metadata": {
            "name": name,
            "namespace": ns,
            "creation_timestamp": datetime.now(UTC) - timedelta(seconds=age_seconds),
        },
        "status": {"phase": phase},
    }


def _orch(pods: list[dict]):
    orch = MagicMock()
    orch._ensure_client = AsyncMock()
    core = MagicMock()
    listing = MagicMock()
    listing.to_dict.return_value = {"items": pods}
    core.list_pod_for_all_namespaces = AsyncMock(return_value=listing)
    core.delete_namespaced_pod = AsyncMock()
    core.delete_namespaced_secret = AsyncMock()
    orch._core_api = core
    return orch, core


class TestReaper:
    async def test_deletes_old_terminal_pods_and_their_secrets(self):
        orch, core = _orch(
            [
                _pod("sp-eval-old", "Succeeded", age_seconds=7200),
                _pod("sp-eval-dead", "Failed", age_seconds=86400),
            ]
        )
        assert await reap_terminal_eval_pods(orch) == 2
        deleted = [c.kwargs["name"] for c in core.delete_namespaced_pod.call_args_list]
        assert deleted == ["sp-eval-old", "sp-eval-dead"]
        secrets = [c.kwargs["name"] for c in core.delete_namespaced_secret.call_args_list]
        assert secrets == ["sp-eval-env-sp-eval-old", "sp-eval-env-sp-eval-dead"]

    async def test_skips_running_and_recent_pods(self):
        orch, core = _orch(
            [
                _pod("sp-eval-live", "Running", age_seconds=7200),
                _pod("sp-eval-fresh", "Succeeded", age_seconds=60),
            ]
        )
        assert await reap_terminal_eval_pods(orch) == 0
        core.delete_namespaced_pod.assert_not_called()

    async def test_missing_creation_timestamp_still_reaps_terminal_pod(self):
        pod = _pod("sp-eval-nots", "Succeeded", age_seconds=0)
        pod["metadata"]["creation_timestamp"] = None
        orch, core = _orch([pod])
        assert await reap_terminal_eval_pods(orch) == 1

    async def test_list_failure_returns_zero(self):
        orch, core = _orch([])
        core.list_pod_for_all_namespaces = AsyncMock(side_effect=RuntimeError("403 forbidden"))
        assert await reap_terminal_eval_pods(orch) == 0

    async def test_delete_failure_continues_to_next_pod(self):
        orch, core = _orch(
            [
                _pod("sp-eval-a", "Succeeded", age_seconds=7200),
                _pod("sp-eval-b", "Succeeded", age_seconds=7200),
            ]
        )
        core.delete_namespaced_pod = AsyncMock(side_effect=[RuntimeError("boom"), None])
        assert await reap_terminal_eval_pods(orch) == 1

    async def test_no_client_returns_zero(self):
        orch = MagicMock()
        orch._ensure_client = AsyncMock()
        orch._core_api = None
        assert await reap_terminal_eval_pods(orch) == 0
