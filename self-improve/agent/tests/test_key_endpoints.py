"""Unit tests for key management API endpoints.

Tests cover POST /keys, GET /keys, PATCH /keys/{id}, DELETE /keys/{id},
GET /keys/status, GET /keys/config, and PATCH /keys/config.

Each test uses a real temporary SQLite database so that SQL constraints,
encryption, and masking logic are fully exercised — only external crypto
and routing state are patched (MASTER_KEY_PATH and _fernet singleton).
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Make the agent package importable from the tests sub-directory.
# The key_pool and endpoints modules use `from agent import db`, which
# resolves to `agent.db` (the package-level module), not the top-level `db`
# module.  We must init `agent.db` — not bare `db` — so the DB connection is
# visible to KeyPool.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent import db as db_module
from agent.db import init_db, close_db
from agent import endpoints
from agent.rate_limit import keys_limiter
import monitor.crypto as crypto
import agent.key_pool as kp_module


# ---------------------------------------------------------------------------
# Shared fixture — creates isolated DB + master key for each test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app_client(tmp_path):
    """Spin up a fresh DB and test client for each test.

    Resets the Fernet singleton so each test uses its own master key.
    Resets db_module._db so the module-global connection is clean.
    """
    db_path = str(tmp_path / "test.db")
    key_path = str(tmp_path / "master.key")

    # Write a freshly generated Fernet key
    master_key = Fernet.generate_key()
    Path(key_path).write_bytes(master_key)

    # Clear cached Fernet instance so it picks up the new key
    crypto._fernet = None

    await init_db(db_path)

    # Patch MASTER_KEY_PATH used by key_pool and monitor.crypto calls
    orig_key_path = kp_module.MASTER_KEY_PATH
    kp_module.MASTER_KEY_PATH = key_path

    app = FastAPI()
    app.include_router(endpoints.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Teardown: restore state so other tests are not affected
    kp_module.MASTER_KEY_PATH = orig_key_path
    keys_limiter.reset()
    await close_db()
    db_module._db = None
    crypto._fernet = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_key(client: AsyncClient, *, provider: str = "claude_code",
                   key: str = "sk-test-key-abcdef", label: str = "", priority: int = 0) -> dict:
    """POST /keys and return the response JSON."""
    resp = await client.post("/keys", json={
        "provider": provider,
        "key": key,
        "label": label,
        "priority": priority,
    })
    assert resp.status_code == 201, f"add_key failed: {resp.json()}"
    return resp.json()


# ===========================================================================
# POST /keys
# ===========================================================================

class TestAddKey:
    @pytest.mark.asyncio
    async def test_add_key_endpoint_returns_201(self, app_client):
        """POST /keys with valid data returns HTTP 201."""
        resp = await app_client.post("/keys", json={
            "provider": "claude_code",
            "key": "sk-ant-api-abc12345",
            "label": "Primary key",
            "priority": 0,
        })
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_add_key_endpoint_response_has_expected_fields(self, app_client):
        """Response contains id, provider, label, priority, is_enabled, masked_key."""
        data = await _add_key(app_client, label="My Key", priority=3)
        assert "id" in data
        assert data["provider"] == "claude_code"
        assert data["label"] == "My Key"
        assert data["priority"] == 3
        assert data["is_enabled"] is True
        assert "masked_key" in data

    @pytest.mark.asyncio
    async def test_add_key_endpoint_encrypts(self, app_client):
        """The raw API key must not appear anywhere in the response."""
        raw_key = "sk-ant-supersecret-key-99999"
        data = await _add_key(app_client, key=raw_key)
        # The raw key must not be present in any field of the response
        assert raw_key not in str(data), "Raw key was leaked in response"
        assert "encrypted_key" not in data, "encrypted_key column must not be returned"

    @pytest.mark.asyncio
    async def test_add_key_masked_value_shows_prefix(self, app_client):
        """masked_key shows the first 4 characters followed by asterisks."""
        raw_key = "sk-ant-secretvalue"
        data = await _add_key(app_client, key=raw_key)
        masked = data["masked_key"]
        # First 4 chars of key should match
        assert masked.startswith(raw_key[:4])
        assert "*" in masked

    @pytest.mark.asyncio
    async def test_invalid_provider_rejected(self, app_client):
        """POST /keys with an invalid provider returns 422."""
        resp = await app_client.post("/keys", json={
            "provider": "openai",
            "key": "sk-openai-test",
        })
        assert resp.status_code == 422
        assert "provider" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_codex_provider_accepted(self, app_client):
        """POST /keys with provider='codex' is valid and returns 201."""
        resp = await app_client.post("/keys", json={
            "provider": "codex",
            "key": "sk-codex-key-12345",
        })
        assert resp.status_code == 201
        assert resp.json()["provider"] == "codex"

    @pytest.mark.asyncio
    async def test_add_key_missing_key_field_rejected(self, app_client):
        """POST /keys without the required 'key' field returns 422."""
        resp = await app_client.post("/keys", json={"provider": "claude_code"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_add_key_missing_provider_field_rejected(self, app_client):
        """POST /keys without the required 'provider' field returns 422."""
        resp = await app_client.post("/keys", json={"key": "sk-test-abc"})
        assert resp.status_code == 422


# ===========================================================================
# GET /keys
# ===========================================================================

class TestListKeys:
    @pytest.mark.asyncio
    async def test_list_keys_empty_returns_empty_list(self, app_client):
        """GET /keys returns [] when no keys have been added."""
        resp = await app_client.get("/keys")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_keys_endpoint_masks_values(self, app_client):
        """GET /keys returns masked_key and never exposes encrypted_key."""
        raw_key = "sk-ant-raw-secret-value-xyz"
        await _add_key(app_client, key=raw_key)

        resp = await app_client.get("/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        key_entry = data[0]
        assert "masked_key" in key_entry
        assert "encrypted_key" not in key_entry
        # Raw key must not appear in the response
        assert raw_key not in str(data)

    @pytest.mark.asyncio
    async def test_list_keys_endpoint_includes_status(self, app_client):
        """GET /keys includes is_enabled and rate_limit_resets_at fields."""
        await _add_key(app_client)

        resp = await app_client.get("/keys")
        key_entry = resp.json()[0]
        assert "is_enabled" in key_entry
        assert key_entry["is_enabled"] is True
        assert "rate_limit_resets_at" in key_entry
        assert key_entry["rate_limit_resets_at"] is None  # freshly added, not rate-limited

    @pytest.mark.asyncio
    async def test_list_keys_returns_multiple_keys(self, app_client):
        """GET /keys returns all added keys."""
        await _add_key(app_client, key="sk-one-111111111", label="Key One")
        await _add_key(app_client, key="sk-two-222222222", label="Key Two")
        await _add_key(app_client, key="sk-thr-333333333", label="Key Three")

        resp = await app_client.get("/keys")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    @pytest.mark.asyncio
    async def test_list_keys_includes_id_field(self, app_client):
        """GET /keys returns an 'id' field for each key (needed for PATCH/DELETE)."""
        added = await _add_key(app_client)
        resp = await app_client.get("/keys")
        listed = resp.json()[0]
        assert listed["id"] == added["id"]


# ===========================================================================
# PATCH /keys/{id}
# ===========================================================================

class TestUpdateKey:
    @pytest.mark.asyncio
    async def test_update_key_endpoint_partial(self, app_client):
        """PATCH /keys/{id} updates only the provided fields."""
        added = await _add_key(app_client, label="Old Label", priority=0)
        key_id = added["id"]

        resp = await app_client.patch(f"/keys/{key_id}", json={"label": "New Label", "priority": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "New Label"
        assert data["priority"] == 10

    @pytest.mark.asyncio
    async def test_update_key_label_only(self, app_client):
        """PATCH /keys/{id} can update just the label without affecting priority."""
        added = await _add_key(app_client, label="Initial", priority=5)
        key_id = added["id"]

        resp = await app_client.patch(f"/keys/{key_id}", json={"label": "Changed"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "Changed"
        assert data["priority"] == 5  # unchanged

    @pytest.mark.asyncio
    async def test_update_key_enabled_flag(self, app_client):
        """PATCH /keys/{id} can toggle is_enabled."""
        # Add two keys so we can disable one without it being the last
        added1 = await _add_key(app_client, key="sk-key-one-aaaaaa")
        added2 = await _add_key(app_client, key="sk-key-two-bbbbbb")
        key_id = added1["id"]

        resp = await app_client.patch(f"/keys/{key_id}", json={"is_enabled": False})
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False

    @pytest.mark.asyncio
    async def test_update_key_not_found_returns_404(self, app_client):
        """PATCH /keys/{id} returns 404 when the key does not exist."""
        fake_id = str(uuid.uuid4())
        resp = await app_client.patch(f"/keys/{fake_id}", json={"label": "Ghost"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_key_response_masks_value(self, app_client):
        """PATCH /keys/{id} returns masked_key and no encrypted_key."""
        added = await _add_key(app_client)
        key_id = added["id"]

        resp = await app_client.patch(f"/keys/{key_id}", json={"label": "Updated"})
        data = resp.json()
        assert "masked_key" in data
        assert "encrypted_key" not in data


# ===========================================================================
# DELETE /keys/{id}
# ===========================================================================

class TestDeleteKey:
    @pytest.mark.asyncio
    async def test_delete_key_endpoint_removes(self, app_client):
        """DELETE /keys/{id} removes the key; it no longer appears in GET /keys."""
        key1 = await _add_key(app_client, key="sk-keep-111111111")
        key2 = await _add_key(app_client, key="sk-kill-222222222")
        key2_id = key2["id"]

        resp = await app_client.delete(f"/keys/{key2_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "deleted": key2_id}

        # Verify it is gone
        list_resp = await app_client.get("/keys")
        ids = [k["id"] for k in list_resp.json()]
        assert key2_id not in ids
        assert key1["id"] in ids

    @pytest.mark.asyncio
    async def test_delete_last_key_returns_409(self, app_client):
        """DELETE /keys/{id} returns 409 when deleting the only enabled key."""
        added = await _add_key(app_client)
        key_id = added["id"]

        resp = await app_client.delete(f"/keys/{key_id}")
        assert resp.status_code == 409
        assert "last enabled" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key_returns_404(self, app_client):
        """DELETE /keys/{id} returns 404 when the key does not exist."""
        fake_id = str(uuid.uuid4())
        resp = await app_client.delete(f"/keys/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_returns_deleted_id_in_response(self, app_client):
        """DELETE /keys/{id} echoes the deleted id in the response."""
        key1 = await _add_key(app_client, key="sk-key-one-xxxxxx")
        key2 = await _add_key(app_client, key="sk-key-two-yyyyyy")
        key_id = key2["id"]

        resp = await app_client.delete(f"/keys/{key_id}")
        assert resp.json()["deleted"] == key_id

    @pytest.mark.asyncio
    async def test_delete_disabled_key_allowed_when_enabled_exists(self, app_client):
        """Can delete a disabled key even if it's the only one (it's not enabled)."""
        key1 = await _add_key(app_client, key="sk-enabled-aaaaaa")
        key2 = await _add_key(app_client, key="sk-disable-bbbbbb")

        # Disable key2
        await app_client.patch(f"/keys/{key2['id']}", json={"is_enabled": False})

        # Now delete key2 (disabled, so the enabled count stays at 1 for key1)
        resp = await app_client.delete(f"/keys/{key2['id']}")
        assert resp.status_code == 200


# ===========================================================================
# GET /keys/status
# ===========================================================================

class TestKeyPoolStatus:
    @pytest.mark.asyncio
    async def test_key_pool_status_endpoint_structure(self, app_client):
        """GET /keys/status returns the expected top-level fields."""
        await _add_key(app_client)

        resp = await app_client.get("/keys/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_key_id" in data
        assert "total_keys" in data
        assert "available_keys" in data
        assert "rate_limited_keys" in data
        assert "earliest_reset_at" in data
        assert "seconds_until_reset" in data
        assert "keys" in data

    @pytest.mark.asyncio
    async def test_key_pool_status_endpoint(self, app_client):
        """GET /keys/status counts reflect the actual pool state."""
        await _add_key(app_client, key="sk-status-one-1111")
        await _add_key(app_client, key="sk-status-two-2222")

        resp = await app_client.get("/keys/status")
        data = resp.json()
        assert data["total_keys"] == 2
        assert data["available_keys"] == 2
        assert data["rate_limited_keys"] == 0
        # No active key selected yet (new KeyPool instance per request)
        assert data["active_key_id"] is None

    @pytest.mark.asyncio
    async def test_key_pool_status_empty_pool(self, app_client):
        """GET /keys/status returns zeros when no keys are configured."""
        resp = await app_client.get("/keys/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_keys"] == 0
        assert data["available_keys"] == 0
        assert data["rate_limited_keys"] == 0
        assert data["earliest_reset_at"] is None
        assert data["seconds_until_reset"] is None

    @pytest.mark.asyncio
    async def test_key_pool_status_keys_are_masked(self, app_client):
        """Keys embedded in GET /keys/status are masked, not raw."""
        raw_key = "sk-ant-status-secret-xyz"
        await _add_key(app_client, key=raw_key)

        resp = await app_client.get("/keys/status")
        data = resp.json()
        for key_entry in data["keys"]:
            assert "encrypted_key" not in key_entry
            assert raw_key not in str(key_entry)


# ===========================================================================
# GET /keys/config
# ===========================================================================

class TestGetConfig:
    @pytest.mark.asyncio
    async def test_get_config_endpoint(self, app_client):
        """GET /keys/config returns the rotation config with default values."""
        resp = await app_client.get("/keys/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "codex_fallback_enabled" in data
        assert "auto_wait_enabled" in data
        assert "max_wait_minutes" in data
        assert "rotation_strategy" in data
        assert "prefer_model_downgrade_over_codex" in data

    @pytest.mark.asyncio
    async def test_get_config_endpoint_default_values(self, app_client):
        """GET /keys/config seeds sensible defaults on first call."""
        resp = await app_client.get("/keys/config")
        data = resp.json()
        assert data["codex_fallback_enabled"] == "false"
        assert data["auto_wait_enabled"] == "true"
        assert data["max_wait_minutes"] == "60"
        assert data["rotation_strategy"] == "priority_then_cooldown"
        assert data["prefer_model_downgrade_over_codex"] == "true"


# ===========================================================================
# PATCH /keys/config  (routing-order note)
# ===========================================================================

class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_update_config_endpoint(self, app_client):
        """PATCH /keys/config updates the specified config fields."""
        # Seed defaults first via GET
        await app_client.get("/keys/config")

        resp = await app_client.patch("/keys/config", json={"max_wait_minutes": 30})
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_wait_minutes"] == "30"

    @pytest.mark.asyncio
    async def test_update_config_unknown_key_via_pool_rejected(self, app_client):
        """Verify unknown config keys are rejected at the KeyPool level."""
        from agent.key_pool import KeyPool
        pool = KeyPool()
        with pytest.raises(ValueError, match="Unknown config key"):
            await pool.update_config({"evil_injection": "true"})

    @pytest.mark.asyncio
    async def test_update_config_directly_via_pool(self, app_client):
        """Verify config updates work at the KeyPool level even if the HTTP route is shadowed."""
        from agent.key_pool import KeyPool

        # Seed defaults
        await app_client.get("/keys/config")

        pool = KeyPool()
        updated = await pool.update_config({"codex_fallback_enabled": "true", "max_wait_minutes": "45"})
        assert updated["codex_fallback_enabled"] == "true"
        assert updated["max_wait_minutes"] == "45"
        # Other keys remain at defaults
        assert updated["rotation_strategy"] == "priority_then_cooldown"

        # The GET endpoint should reflect the change
        resp = await app_client.get("/keys/config")
        assert resp.json()["codex_fallback_enabled"] == "true"
        assert resp.json()["max_wait_minutes"] == "45"


# ===========================================================================
# Edge-case / integration
# ===========================================================================

class TestKeyEndpointsIntegration:
    @pytest.mark.asyncio
    async def test_add_then_list_then_delete_lifecycle(self, app_client):
        """Full lifecycle: add two keys, list them, delete one, verify count."""
        k1 = await _add_key(app_client, key="sk-lifecycle-one-1", label="First")
        k2 = await _add_key(app_client, key="sk-lifecycle-two-2", label="Second")

        list_resp = await app_client.get("/keys")
        assert len(list_resp.json()) == 2

        del_resp = await app_client.delete(f"/keys/{k2['id']}")
        assert del_resp.status_code == 200

        list_resp2 = await app_client.get("/keys")
        assert len(list_resp2.json()) == 1
        assert list_resp2.json()[0]["id"] == k1["id"]

    @pytest.mark.asyncio
    async def test_update_then_list_reflects_changes(self, app_client):
        """Changes from PATCH /keys/{id} are visible in GET /keys."""
        added = await _add_key(app_client, label="Before", priority=0)
        key_id = added["id"]

        await app_client.patch(f"/keys/{key_id}", json={"label": "After", "priority": 99})

        list_resp = await app_client.get("/keys")
        updated = next(k for k in list_resp.json() if k["id"] == key_id)
        assert updated["label"] == "After"
        assert updated["priority"] == 99

    @pytest.mark.asyncio
    async def test_status_total_reflects_added_keys(self, app_client):
        """GET /keys/status total_keys increments as keys are added."""
        resp0 = await app_client.get("/keys/status")
        assert resp0.json()["total_keys"] == 0

        await _add_key(app_client, key="sk-a-111111111")
        resp1 = await app_client.get("/keys/status")
        assert resp1.json()["total_keys"] == 1

        await _add_key(app_client, key="sk-b-222222222")
        resp2 = await app_client.get("/keys/status")
        assert resp2.json()["total_keys"] == 2


# ---------------------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------------------

class TestRateLimit:
    """Tests for rate limiting on /keys/* endpoints."""

    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_threshold(self, app_client):
        """10 requests within the window all succeed."""
        keys_limiter.reset()
        for _ in range(10):
            resp = await app_client.get("/keys")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_at_threshold(self, app_client):
        """11th request returns 429 with Retry-After header."""
        keys_limiter.reset()
        for _ in range(10):
            resp = await app_client.get("/keys")
            assert resp.status_code == 200

        resp = await app_client.get("/keys")
        assert resp.status_code == 429
        assert "retry-after" in resp.headers
        retry_after = int(resp.headers["retry-after"])
        assert retry_after > 0
        assert resp.json()["detail"] == "Rate limit exceeded on key management endpoints"

    @pytest.mark.asyncio
    async def test_rate_limit_resets_after_window(self, app_client):
        """After the window passes, requests succeed again."""
        from agent.rate_limit import RateLimiter

        # Create a limiter with controllable time
        fake_time = 1000.0

        def time_func():
            return fake_time

        test_limiter = RateLimiter(max_requests=3, window_seconds=10, time_func=time_func)

        # Fill the window
        for _ in range(3):
            assert test_limiter.check() is None

        # 4th request blocked
        retry = test_limiter.check()
        assert retry is not None

        # Advance time past the window
        fake_time = 1011.0

        # Request succeeds again
        assert test_limiter.check() is None
