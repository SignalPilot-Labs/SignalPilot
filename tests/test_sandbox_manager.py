"""Integration tests for sp-sandbox/sandbox_manager.py — HTTP API."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import AioHTTPTestCase

# Add sp-sandbox to path so we can import directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sp-sandbox"))

from models import ExecutionResult
from sandbox_manager import active_sessions, create_app, executor


class TestHealthEndpoint(AioHTTPTestCase):
    """Tests for GET /health."""

    async def get_application(self):
        active_sessions.clear()
        return create_app()

    async def test_health_returns_status(self):
        resp = await self.client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "healthy"
        assert "active_vms" in data
        assert "max_vms" in data

    async def test_health_counts_active_sessions(self):
        active_sessions["s1"] = "vm1"
        active_sessions["s2"] = "vm2"
        resp = await self.client.get("/health")
        data = await resp.json()
        assert data["active_vms"] == 2


class TestListVmsEndpoint(AioHTTPTestCase):
    """Tests for GET /vms."""

    async def get_application(self):
        active_sessions.clear()
        return create_app()

    async def test_empty_vms(self):
        resp = await self.client.get("/vms")
        assert resp.status == 200
        data = await resp.json()
        assert data["active_vms"] == []

    async def test_lists_active_sessions(self):
        active_sessions["token-abc"] = "vm-xyz"
        resp = await self.client.get("/vms")
        data = await resp.json()
        assert len(data["active_vms"]) == 1
        assert data["active_vms"][0]["vm_id"] == "vm-xyz"
        assert data["active_vms"][0]["session_token"] == "token-abc"


class TestExecuteEndpoint(AioHTTPTestCase):
    """Tests for POST /execute."""

    async def get_application(self):
        active_sessions.clear()
        return create_app()

    async def test_missing_code_returns_400(self):
        resp = await self.client.post("/execute", json={"code": "", "session_token": "t", "timeout": 5})
        assert resp.status == 400
        data = await resp.json()
        assert data["success"] is False
        assert "Missing" in data["error"]

    async def test_invalid_json_returns_400(self):
        resp = await self.client.post("/execute", data=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status == 400
        data = await resp.json()
        assert "Invalid JSON" in data["error"]

    async def test_code_too_long_returns_400(self):
        resp = await self.client.post("/execute", json={
            "code": "x" * 1_000_001,
            "session_token": "t",
            "timeout": 5,
        })
        assert resp.status == 400
        data = await resp.json()
        assert "max length" in data["error"]

    async def test_successful_execution(self):
        mock_result = ExecutionResult(
            success=True, output="hello", error=None, execution_ms=100.0, vm_id="mock-vm",
        )
        with patch.object(executor, "execute", new_callable=AsyncMock, return_value=mock_result):
            resp = await self.client.post("/execute", json={
                "code": "print('hello')",
                "session_token": "test-session",
                "timeout": 10,
            })
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        assert data["output"] == "hello"
        assert data["vm_id"] == "mock-vm"
        assert data["execution_ms"] == 100.0

    async def test_failed_execution_clears_session(self):
        mock_result = ExecutionResult(
            success=False, output="", error="boom", execution_ms=50.0, vm_id="fail-vm",
        )
        with patch.object(executor, "execute", new_callable=AsyncMock, return_value=mock_result):
            resp = await self.client.post("/execute", json={
                "code": "raise Exception",
                "session_token": "fail-session",
                "timeout": 5,
            })
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is False
        assert "fail-session" not in active_sessions

    async def test_rate_limit_at_max_vms(self):
        from constants import MAX_VMS
        for i in range(MAX_VMS):
            active_sessions[f"s{i}"] = f"vm{i}"

        resp = await self.client.post("/execute", json={
            "code": "print(1)",
            "session_token": "new-session",
            "timeout": 5,
        })
        assert resp.status == 429
        data = await resp.json()
        assert "Rate limited" in data["error"]

    async def test_existing_session_bypasses_rate_limit(self):
        from constants import MAX_VMS
        for i in range(MAX_VMS):
            active_sessions[f"s{i}"] = f"vm{i}"

        mock_result = ExecutionResult(
            success=True, output="ok", error=None, execution_ms=10.0, vm_id="vm0",
        )
        with patch.object(executor, "execute", new_callable=AsyncMock, return_value=mock_result):
            resp = await self.client.post("/execute", json={
                "code": "print(1)",
                "session_token": "s0",
                "timeout": 5,
            })
        assert resp.status == 200

    async def test_timeout_clamped_to_bounds(self):
        captured_args = {}

        async def capture_execute(code, vm_id, timeout):
            captured_args["timeout"] = timeout
            return ExecutionResult(
                success=True, output="", error=None, execution_ms=5.0, vm_id="t-vm",
            )

        with patch.object(executor, "execute", side_effect=capture_execute):
            await self.client.post("/execute", json={
                "code": "x",
                "session_token": "t",
                "timeout": 999,
            })
        assert captured_args["timeout"] == 300


class TestKillVmEndpoint(AioHTTPTestCase):
    """Tests for DELETE /vm/{vm_id}."""

    async def get_application(self):
        active_sessions.clear()
        return create_app()

    async def test_kill_existing_vm(self):
        active_sessions["s1"] = "vm-to-kill"
        with patch.object(executor, "kill", new_callable=AsyncMock, return_value=True):
            resp = await self.client.delete("/vm/vm-to-kill")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "killed"
        assert "s1" not in active_sessions

    async def test_kill_nonexistent_vm(self):
        with patch.object(executor, "kill", new_callable=AsyncMock, return_value=False):
            resp = await self.client.delete("/vm/no-such-vm")
        assert resp.status == 404
        data = await resp.json()
        assert data["status"] == "not_found"
