"""Unit tests for RunManager and RunSlot."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agent.run_manager import (
    ALLOWED_CREDENTIAL_KEYS,
    MAX_CONCURRENT,
    SIGNAL_ENDPOINTS,
    RunManager,
    RunSlot,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

MOCK_INSPECT_OUTPUT = json.dumps([{
    "Config": {"Image": "self-improve-agent"},
    "NetworkSettings": {"Networks": {"self-improve_default": {}}},
    "Mounts": [
        {"Source": "/var/lib/docker/volumes/db/_data", "Destination": "/data", "Mode": "rw"},
        {"Source": "/var/lib/docker/volumes/repo/_data", "Destination": "/home/agentuser/repo", "Mode": "rw"},
        {"Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "Mode": "rw"},
    ],
}])


def _make_subprocess_result(stdout: str, returncode: int = 0) -> SimpleNamespace:
    """Return a fake subprocess.CompletedProcess-like object."""
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def _manager_with_env() -> RunManager:
    """Return a RunManager whose _env_cache is pre-populated (no docker calls needed)."""
    mgr = RunManager()
    mgr._env_cache = {
        "image": "self-improve-agent",
        "network": "self-improve_default",
        "mounts": [
            {"source": "/var/lib/docker/volumes/db/_data", "destination": "/data", "mode": "rw"},
            {"source": "/var/lib/docker/volumes/repo/_data", "destination": "/home/agentuser/repo", "mode": "rw"},
            {"source": "/var/run/docker.sock", "destination": "/var/run/docker.sock", "mode": "rw"},
        ],
    }
    return mgr


# ===========================================================================
# 1. RunSlot tests
# ===========================================================================

class TestRunSlot:
    def test_run_slot_defaults(self):
        """RunSlot should have sensible defaults for all fields."""
        slot = RunSlot()
        assert slot.run_id is None
        assert slot.container_id == ""
        assert slot.container_name == ""
        assert slot.status == "starting"
        assert slot.prompt is None
        assert slot.max_budget_usd == 0
        assert slot.duration_minutes == 0
        assert slot.base_branch == "main"
        assert slot.error_message is None
        assert slot.volume_name == ""
        assert slot.started_at > 0

    def test_run_slot_with_values(self):
        """RunSlot should store explicitly supplied values."""
        slot = RunSlot(
            run_id="abc123",
            container_id="cid",
            container_name="improve-worker-x",
            status="running",
            prompt="do the thing",
            max_budget_usd=5.0,
            duration_minutes=30.0,
            base_branch="dev",
            error_message=None,
            volume_name="improve-worker-repo-x",
        )
        assert slot.run_id == "abc123"
        assert slot.status == "running"
        assert slot.prompt == "do the thing"
        assert slot.max_budget_usd == 5.0
        assert slot.duration_minutes == 30.0
        assert slot.base_branch == "dev"
        assert slot.volume_name == "improve-worker-repo-x"

    def test_run_slot_volume_name(self):
        """RunSlot must have a volume_name field (used for cleanup)."""
        slot = RunSlot(volume_name="my-volume")
        assert slot.volume_name == "my-volume"


# ===========================================================================
# 2. RunManager initialisation
# ===========================================================================

class TestRunManagerInit:
    def test_run_manager_init(self):
        """slots dict should be empty and _start_lock should exist."""
        mgr = RunManager()
        assert mgr.slots == {}
        assert isinstance(mgr._start_lock, asyncio.Lock)

    def test_active_count_empty(self):
        """active_count returns 0 when there are no slots."""
        mgr = RunManager()
        assert mgr.active_count() == 0

    def test_active_count_with_slots(self):
        """active_count sums only starting+running slots."""
        mgr = RunManager()
        mgr.slots = {
            "a": RunSlot(status="starting"),
            "b": RunSlot(status="running"),
            "c": RunSlot(status="completed"),
            "d": RunSlot(status="error"),
            "e": RunSlot(status="stopped"),
        }
        assert mgr.active_count() == 2


# ===========================================================================
# 3. _detect_environment
# ===========================================================================

class TestDetectEnvironment:
    def test_detect_environment_caches_result(self):
        """_detect_environment must call docker inspect exactly once (caches result)."""
        mgr = RunManager()
        with patch.object(mgr, "_run_docker", return_value=MOCK_INSPECT_OUTPUT) as mock_docker, \
             patch("os.uname", return_value=SimpleNamespace(nodename="test-host")):
            mgr._detect_environment()
            mgr._detect_environment()
        mock_docker.assert_called_once_with(["inspect", "test-host"])

    def test_detect_environment_parses_output(self):
        """_detect_environment extracts image, network, and mounts correctly."""
        mgr = RunManager()
        with patch.object(mgr, "_run_docker", return_value=MOCK_INSPECT_OUTPUT), \
             patch("os.uname", return_value=SimpleNamespace(nodename="test-host")):
            env = mgr._detect_environment()

        assert env["image"] == "self-improve-agent"
        assert env["network"] == "self-improve_default"
        assert len(env["mounts"]) == 3
        destinations = [m["destination"] for m in env["mounts"]]
        assert "/data" in destinations
        assert "/home/agentuser/repo" in destinations
        assert "/var/run/docker.sock" in destinations


# ===========================================================================
# 4. _build_worker_mounts
# ===========================================================================

class TestBuildWorkerMounts:
    def test_build_worker_mounts_replaces_repo_volume(self):
        """/home/agentuser/repo destination gets a per-worker named volume."""
        mgr = _manager_with_env()
        flags = mgr._build_worker_mounts("abc123")
        # Flags are like ["-v", "volume:dst", ...] — find the repo entry
        joined = " ".join(flags)
        assert "improve-worker-repo-abc123:/home/agentuser/repo" in joined
        # The original source volume for /home/agentuser/repo must NOT appear
        assert "/var/lib/docker/volumes/repo/_data" not in joined

    def test_build_worker_mounts_preserves_other_mounts(self):
        """Non-repo mounts are passed through with their original source and mode."""
        mgr = _manager_with_env()
        flags = mgr._build_worker_mounts("abc123")
        # /data and /var/run/docker.sock should appear verbatim
        joined = " ".join(flags)
        assert "/data" in joined
        assert "/var/run/docker.sock" in joined
        # Their sources must be present too
        assert "/var/lib/docker/volumes/db/_data" in joined
        assert "/var/run/docker.sock:/var/run/docker.sock" in joined


# ===========================================================================
# 5. send_signal
# ===========================================================================

class TestSendSignal:
    @pytest.mark.asyncio
    async def test_send_signal_valid(self):
        """send_signal POSTs to the correct endpoint for a valid signal."""
        mgr = RunManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await mgr.send_signal("improve-worker-x", "stop", {"reason": "done"})

        mock_client.post.assert_called_once_with(
            "http://improve-worker-x:8500/stop", json={"reason": "done"}
        )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_send_signal_invalid_raises(self):
        """send_signal raises ValueError for an unrecognised signal name."""
        mgr = RunManager()
        with pytest.raises(ValueError, match="Unknown signal"):
            await mgr.send_signal("improve-worker-x", "explode")

    @pytest.mark.asyncio
    async def test_signal_endpoint_mapping(self):
        """Every key in SIGNAL_ENDPOINTS produces a POST to the correct URL."""
        mgr = RunManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            for signal, endpoint in SIGNAL_ENDPOINTS.items():
                mock_client.post.reset_mock()
                await mgr.send_signal("worker", signal)
                called_url = mock_client.post.call_args[0][0]
                assert called_url == f"http://worker:8500/{endpoint}", \
                    f"signal={signal!r} should map to endpoint={endpoint!r}"


# ===========================================================================
# 6. Credential filtering
# ===========================================================================

class TestCredentialFiltering:
    def test_credentials_filtered(self):
        """Only ALLOWED_CREDENTIAL_KEYS are forwarded; the rest are silently dropped."""
        creds = {"claude_token": "tok", "git_token": "gt", "github_repo": "owner/repo"}
        safe = {k: v for k, v in creds.items() if k in ALLOWED_CREDENTIAL_KEYS}
        assert set(safe.keys()) == {"claude_token", "git_token", "github_repo"}

    def test_credentials_unknown_keys_rejected(self):
        """Keys not in ALLOWED_CREDENTIAL_KEYS must be excluded."""
        creds = {"claude_token": "tok", "evil_key": "bad", "another": "nope"}
        safe = {k: v for k, v in creds.items() if k in ALLOWED_CREDENTIAL_KEYS}
        assert "evil_key" not in safe
        assert "another" not in safe
        assert safe == {"claude_token": "tok"}


# ===========================================================================
# 7. TOCTOU race protection
# ===========================================================================

class TestTOCTOU:
    @pytest.mark.asyncio
    async def test_start_run_reserves_slot_immediately(self):
        """Slot must be in self.slots before the docker run call completes."""
        mgr = _manager_with_env()
        slot_names_at_docker_call: list[str] = []

        async def fake_wait_health(name):
            pass

        def fake_run_docker(args, timeout=30):
            # Record the slot keys the moment docker run is called
            slot_names_at_docker_call.extend(mgr.slots.keys())
            return "abc123def456"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"run_id": "run-001"}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(mgr, "_run_docker", side_effect=fake_run_docker), \
             patch.object(mgr, "_wait_for_health", new=fake_wait_health), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("asyncio.create_task"):
            await mgr.start_run("prompt", 1.0, 10.0, "main", {})

        assert len(slot_names_at_docker_call) == 1, "slot must be reserved before docker run"

    @pytest.mark.asyncio
    async def test_max_concurrent_enforced(self):
        """start_run raises RuntimeError when MAX_CONCURRENT slots are active."""
        mgr = RunManager()
        for i in range(MAX_CONCURRENT):
            mgr.slots[f"worker-{i}"] = RunSlot(status="running")

        with pytest.raises(RuntimeError, match="Max concurrent"):
            await mgr.start_run("prompt", 1.0, 10.0, "main", {})


# ===========================================================================
# 8. to_dict
# ===========================================================================

class TestToDict:
    def test_to_dict_serialization(self):
        """to_dict returns a dict with all expected keys and correct types."""
        slot = RunSlot(
            run_id="r1",
            container_id="cid123",
            container_name="improve-worker-x",
            status="running",
            prompt="hello",
            max_budget_usd=3.5,
            duration_minutes=20.0,
            base_branch="main",
            error_message=None,
            volume_name="vol-x",
        )
        d = RunManager.to_dict(slot)
        assert d["run_id"] == "r1"
        assert d["container_id"] == "cid123"
        assert d["container_name"] == "improve-worker-x"
        assert d["status"] == "running"
        assert d["prompt"] == "hello"
        assert isinstance(d["max_budget_usd"], float)
        assert isinstance(d["duration_minutes"], float)
        assert d["base_branch"] == "main"
        assert isinstance(d["started_at"], float)
        assert d["error_message"] is None
        assert d["volume_name"] == "vol-x"
        expected_keys = {
            "run_id", "container_id", "container_name", "status", "prompt",
            "max_budget_usd", "duration_minutes", "base_branch", "started_at",
            "error_message", "volume_name",
        }
        assert set(d.keys()) == expected_keys


# ===========================================================================
# 9. Cleanup
# ===========================================================================

class TestCleanup:
    def test_cleanup_container(self):
        """cleanup_container calls docker stop then docker rm."""
        mgr = RunManager()
        calls_made: list[list[str]] = []

        def fake_docker(args, timeout=30):
            calls_made.append(args)
            return ""

        with patch.object(mgr, "_run_docker", side_effect=fake_docker):
            mgr.cleanup_container("improve-worker-x")

        assert calls_made[0][:2] == ["stop", "-t"]
        assert "improve-worker-x" in calls_made[0]
        assert calls_made[1][0] == "rm"
        assert "improve-worker-x" in calls_made[1]

    def test_cleanup_container_with_volume(self):
        """cleanup_container(remove_volume=True) also runs docker volume rm."""
        mgr = RunManager()
        mgr.slots["improve-worker-x"] = RunSlot(
            container_name="improve-worker-x",
            volume_name="improve-worker-repo-x",
            status="completed",
        )
        calls_made: list[list[str]] = []

        def fake_docker(args, timeout=30):
            calls_made.append(args)
            return ""

        with patch.object(mgr, "_run_docker", side_effect=fake_docker):
            mgr.cleanup_container("improve-worker-x", remove_volume=True)

        commands = [c[0] for c in calls_made]
        assert "volume" in commands
        vol_call = next(c for c in calls_made if c[0] == "volume")
        assert vol_call == ["volume", "rm", "improve-worker-repo-x"]

    def test_cleanup_all_finished(self):
        """cleanup_all_finished only touches slots that are not starting/running."""
        mgr = RunManager()
        mgr.slots = {
            "active": RunSlot(status="running"),
            "done": RunSlot(status="completed"),
            "err": RunSlot(status="error"),
        }
        cleaned_names: list[str] = []

        def fake_cleanup(name, remove_volume=False):
            cleaned_names.append(name)

        with patch.object(mgr, "cleanup_container", side_effect=fake_cleanup):
            count = mgr.cleanup_all_finished()

        assert count == 2
        assert "active" not in cleaned_names
        assert "done" in cleaned_names
        assert "err" in cleaned_names
        # Finished slots should be removed from dict
        assert "done" not in mgr.slots
        assert "err" not in mgr.slots
        assert "active" in mgr.slots


# ===========================================================================
# 10. Slot lookup
# ===========================================================================

class TestSlotLookup:
    def test_get_slot_by_run_id(self):
        """get_slot_by_run_id returns the slot whose run_id matches."""
        mgr = RunManager()
        mgr.slots["worker-a"] = RunSlot(run_id="run-aaa")
        mgr.slots["worker-b"] = RunSlot(run_id="run-bbb")
        result = mgr.get_slot_by_run_id("run-bbb")
        assert result is mgr.slots["worker-b"]

    def test_get_slot_by_run_id_not_found(self):
        """get_slot_by_run_id returns None when no slot matches."""
        mgr = RunManager()
        mgr.slots["worker-a"] = RunSlot(run_id="run-aaa")
        assert mgr.get_slot_by_run_id("nonexistent") is None

    def test_get_slot(self):
        """get_slot returns the slot keyed by container_name."""
        mgr = RunManager()
        slot = RunSlot(container_name="improve-worker-x")
        mgr.slots["improve-worker-x"] = slot
        assert mgr.get_slot("improve-worker-x") is slot
        assert mgr.get_slot("missing") is None

    def test_get_all_slots(self):
        """get_all_slots returns all slots as a list."""
        mgr = RunManager()
        mgr.slots = {
            "a": RunSlot(container_name="a"),
            "b": RunSlot(container_name="b"),
        }
        result = mgr.get_all_slots()
        assert len(result) == 2
        assert set(s.container_name for s in result) == {"a", "b"}


# ===========================================================================
# 11. kill_run
# ===========================================================================

class TestKillRun:
    @pytest.mark.asyncio
    async def test_kill_run_sends_signal_and_cleans_up(self):
        """kill_run sends the kill signal, marks status=killed, then cleans up."""
        mgr = RunManager()
        mgr.slots["improve-worker-x"] = RunSlot(
            container_name="improve-worker-x", status="running"
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.object(mgr, "cleanup_container") as mock_cleanup:
            result = await mgr.kill_run("improve-worker-x")

        assert result == {"ok": True}
        assert mgr.slots["improve-worker-x"].status == "killed"
        mock_cleanup.assert_called_once_with("improve-worker-x")


# ===========================================================================
# 12. start_run integration-style
# ===========================================================================

class TestStartRun:
    def _make_http_mock(self, run_id="run-xyz"):
        """Build a reusable httpx.AsyncClient mock that returns run_id."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"run_id": run_id}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        return mock_client

    @pytest.mark.asyncio
    async def test_start_run_full_flow(self):
        """Happy path: docker run succeeds, health check passes, /start called."""
        mgr = _manager_with_env()
        mock_client = self._make_http_mock("run-001")

        async def fake_wait_health(name):
            pass

        with patch.object(mgr, "_run_docker", return_value="abc123def456") as mock_docker, \
             patch.object(mgr, "_wait_for_health", new=fake_wait_health), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("asyncio.create_task"):
            slot = await mgr.start_run("do stuff", 2.0, 15.0, "main",
                                       {"claude_token": "tok"})

        assert slot.status == "running"
        assert slot.run_id == "run-001"
        assert slot.container_id == "abc123def456"  # first 12 chars of the returned ID
        # Verify docker run was invoked with "run" as first arg
        docker_call_args = mock_docker.call_args[0][0]
        assert docker_call_args[0] == "run"
        # Verify the /start POST was made
        mock_client.post.assert_called_once()
        post_url = mock_client.post.call_args[0][0]
        assert "/start" in post_url

    @pytest.mark.asyncio
    async def test_start_run_health_timeout(self):
        """start_run propagates TimeoutError when health check times out."""
        mgr = _manager_with_env()

        async def fake_wait_health_timeout(name):
            raise TimeoutError("did not become healthy")

        with patch.object(mgr, "_run_docker", return_value="abc123def456"), \
             patch.object(mgr, "_wait_for_health", new=fake_wait_health_timeout), \
             patch.object(mgr, "cleanup_container"):
            with pytest.raises(TimeoutError, match="did not become healthy"):
                await mgr.start_run("prompt", 1.0, 10.0, "main", {})

        # Slot should be in error state
        slot = next(iter(mgr.slots.values()))
        assert slot.status == "error"
        assert "Health check failed" in slot.error_message

    @pytest.mark.asyncio
    async def test_start_run_docker_failure(self):
        """start_run sets slot to error when docker run fails."""
        mgr = _manager_with_env()

        def fail_docker(args, timeout=30):
            raise RuntimeError("docker: image not found")

        with patch.object(mgr, "_run_docker", side_effect=fail_docker):
            with pytest.raises(RuntimeError, match="image not found"):
                await mgr.start_run("prompt", 1.0, 10.0, "main", {})

        slot = next(iter(mgr.slots.values()))
        assert slot.status == "error"
        assert "image not found" in slot.error_message
