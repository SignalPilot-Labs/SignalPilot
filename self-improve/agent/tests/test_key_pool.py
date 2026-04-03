"""Unit tests for agent/key_pool.py — multi-key rotation and rate limit recovery.

Uses a real temporary SQLite database (via agent.db.init_db) so that SQL
constraints and row-factory behaviour are exercised. Crypto is exercised
with a real Fernet key written to a temp directory; the MASTER_KEY_PATH
module attribute and the monitor.crypto._fernet singleton are patched for
each test.

IMPORTANT: key_pool.py uses `from agent import db` which resolves to the
`agent.db` module object — NOT the bare `db` module used in test_db.py.
These are separate module objects with separate `_db` globals.  All
fixtures therefore call `agent.db.init_db` / `agent.db.close_db`.
"""

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio

# Make agent package importable from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import agent.db as agent_db_module
from agent.db import init_db, close_db, create_run
import monitor.crypto as crypto_module
from key_pool import KeyPool, ApiKey, MASTER_KEY_PATH, DEFAULT_CONFIG, VALID_STRATEGIES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def initialized_db(tmp_path):
    """Open a fresh agent.db for each test, then close it."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    yield db_path
    await close_db()
    agent_db_module._db = None


@pytest.fixture
def master_key_path(tmp_path):
    """Create a temporary Fernet master key file."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    key_path = tmp_path / "master.key"
    key_path.write_bytes(key)
    return str(key_path)


@pytest_asyncio.fixture
async def pool(initialized_db, master_key_path):
    """KeyPool with patched MASTER_KEY_PATH and reset crypto singleton."""
    crypto_module._fernet = None
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        p = KeyPool(run_id=None)
        yield p
    crypto_module._fernet = None


@pytest_asyncio.fixture
async def pool_with_run(initialized_db, master_key_path):
    """KeyPool with a real run_id (for audit log tests)."""
    run_id = await create_run("test-branch")
    crypto_module._fernet = None
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        p = KeyPool(run_id=run_id)
        yield p, run_id
    crypto_module._fernet = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_key(pool, provider="claude_code", raw="sk-test-key", label="test", priority=0):
    """Convenience wrapper that adds a key inside the current patch context."""
    return await pool.add_key(provider, raw, label, priority)


async def _raw_key_row(key_id: str) -> dict:
    """Fetch the raw api_keys row (including encrypted_key) directly from DB."""
    conn = agent_db_module.get_db()
    cursor = await conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


# ===========================================================================
# Database Layer Tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_add_key_stores_encrypted(pool):
    """add_key stores an encrypted value, never the raw key."""
    raw = "sk-ant-super-secret-key-12345"
    k = await pool.add_key("claude_code", raw, "label", 0)
    row = await _raw_key_row(k.id)
    assert row is not None
    assert raw not in row["encrypted_key"], "raw key must not appear in encrypted_key column"
    # The encrypted blob should be a non-empty Fernet token
    assert len(row["encrypted_key"]) > 30


@pytest.mark.asyncio(loop_scope="function")
async def test_add_key_assigns_uuid(pool):
    """add_key assigns a UUID4-formatted id."""
    k = await pool.add_key("claude_code", "sk-test", "label", 0)
    parsed = uuid.UUID(k.id)
    assert str(parsed) == k.id
    assert parsed.version == 4


@pytest.mark.asyncio(loop_scope="function")
async def test_add_key_default_priority_zero(pool):
    """add_key uses priority=0 when not specified."""
    k = await pool.add_key("claude_code", "sk-test")
    assert k.priority == 0


@pytest.mark.asyncio(loop_scope="function")
async def test_add_key_invalid_provider_raises(pool):
    """add_key raises ValueError for unknown providers."""
    with pytest.raises(ValueError, match="Invalid provider"):
        await pool.add_key("openai", "sk-test", "label", 0)


@pytest.mark.asyncio(loop_scope="function")
async def test_list_keys_masks_values(pool):
    """list_keys returns masked keys, not raw values."""
    raw = "sk-ant-very-secret-value-9876"
    await pool.add_key("claude_code", raw, "k1", 0)
    keys = await pool.list_keys()
    assert len(keys) == 1
    entry = keys[0]
    assert "masked_key" in entry
    assert "encrypted_key" not in entry
    assert raw not in entry["masked_key"]
    # Masked value should start with the first 4 chars
    assert entry["masked_key"].startswith(raw[:4])
    assert "*" in entry["masked_key"]


@pytest.mark.asyncio(loop_scope="function")
async def test_list_keys_returns_all_providers(pool):
    """list_keys returns keys from both claude_code and codex providers."""
    await pool.add_key("claude_code", "sk-ant-111", "claude-key", 0)
    await pool.add_key("codex", "sk-openai-222", "codex-key", 0)
    keys = await pool.list_keys()
    providers = {k["provider"] for k in keys}
    assert "claude_code" in providers
    assert "codex" in providers


@pytest.mark.asyncio(loop_scope="function")
async def test_list_keys_filter_by_provider(pool):
    """list_keys with provider= returns only that provider's keys."""
    await pool.add_key("claude_code", "sk-ant-111", "c1", 0)
    await pool.add_key("codex", "sk-openai-222", "o1", 0)
    claude_keys = await pool.list_keys(provider="claude_code")
    assert all(k["provider"] == "claude_code" for k in claude_keys)
    assert len(claude_keys) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_update_key_priority(pool):
    """update_key changes priority and persists it."""
    k = await pool.add_key("claude_code", "sk-test", "label", 0)
    updated = await pool.update_key(k.id, priority=5)
    assert updated.priority == 5
    # Verify in DB
    row = await _raw_key_row(k.id)
    assert row["priority"] == 5


@pytest.mark.asyncio(loop_scope="function")
async def test_update_key_enable_disable(pool):
    """update_key toggles is_enabled."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    # Disable k1 (k2 is still enabled so it's not last)
    updated = await pool.update_key(k1.id, is_enabled=False)
    assert updated.is_enabled is False
    row = await _raw_key_row(k1.id)
    assert row["is_enabled"] == 0
    # Re-enable
    updated2 = await pool.update_key(k1.id, is_enabled=True)
    assert updated2.is_enabled is True


@pytest.mark.asyncio(loop_scope="function")
async def test_update_key_label(pool):
    """update_key changes the label."""
    k = await pool.add_key("claude_code", "sk-test", "old-label", 0)
    updated = await pool.update_key(k.id, label="new-label")
    assert updated.label == "new-label"


@pytest.mark.asyncio(loop_scope="function")
async def test_delete_key_removes_from_pool(pool):
    """delete_key removes the key and it no longer appears in list_keys."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    await pool.delete_key(k1.id)
    keys = await pool.list_keys()
    ids = [k["id"] for k in keys]
    assert k1.id not in ids
    assert k2.id in ids


@pytest.mark.asyncio(loop_scope="function")
async def test_delete_last_key_returns_error(pool):
    """delete_key raises ValueError when deleting the last enabled key."""
    k = await pool.add_key("claude_code", "sk-test", "only-key", 0)
    with pytest.raises(ValueError, match="Cannot delete the last enabled"):
        await pool.delete_key(k.id)


@pytest.mark.asyncio(loop_scope="function")
async def test_delete_disabled_key_allowed_even_if_last(pool):
    """Deleting a disabled key is allowed even if no other enabled keys remain."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    # Disable k1, then delete it — k2 is the only remaining enabled one
    await pool.update_key(k1.id, is_enabled=False)
    # k1 is disabled so it's not the "last enabled" — delete should work
    await pool.delete_key(k1.id)
    keys = await pool.list_keys()
    assert len(keys) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_rate_limited_sets_fields(pool):
    """mark_rate_limited sets resets_at and utilization on the active key."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    pool._active_key = k
    future_ts = int(time.time()) + 3600
    await pool.mark_rate_limited(resets_at=future_ts, utilization=0.95)
    row = await _raw_key_row(k.id)
    assert row["rate_limit_resets_at"] == future_ts
    assert abs(row["rate_limit_utilization"] - 0.95) < 0.001


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_rate_limited_increments_rate_limit_hits(pool):
    """mark_rate_limited increments the rate_limit_hits counter."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    pool._active_key = k
    await pool.mark_rate_limited(resets_at=time.time() + 3600)
    row = await _raw_key_row(k.id)
    assert row["rate_limit_hits"] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_clear_rate_limit_nulls_fields(pool):
    """clear_rate_limit sets rate_limit_resets_at and utilization to NULL."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    pool._active_key = k
    await pool.mark_rate_limited(resets_at=time.time() + 3600, utilization=0.8)
    await pool.clear_rate_limit(k.id)
    row = await _raw_key_row(k.id)
    assert row["rate_limit_resets_at"] is None
    assert row["rate_limit_utilization"] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_rate_limited_no_active_key_is_noop(pool):
    """mark_rate_limited with no active key does not raise."""
    pool._active_key = None
    # Should not raise
    await pool.mark_rate_limited(resets_at=time.time() + 3600)


# ===========================================================================
# Key Selection Tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_prefers_unlimited(pool):
    """get_next_key prefers a non-rate-limited key over a rate-limited one."""
    k_limited = await pool.add_key("claude_code", "sk-limited", "limited", 0)
    k_free = await pool.add_key("claude_code", "sk-free", "free", 1)
    # Rate-limit k_limited
    pool._active_key = k_limited
    await pool.mark_rate_limited(resets_at=time.time() + 3600)
    result = await pool.get_next_key("claude_code")
    assert result is not None
    assert result.id == k_free.id


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_respects_priority(pool):
    """get_next_key returns the key with the lowest priority number."""
    k_low = await pool.add_key("claude_code", "sk-prio-0", "low-prio", 0)
    _k_high = await pool.add_key("claude_code", "sk-prio-5", "high-prio", 5)
    result = await pool.get_next_key("claude_code")
    assert result is not None
    assert result.id == k_low.id


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_skips_disabled(pool):
    """get_next_key never returns a disabled key."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    await pool.update_key(k1.id, is_enabled=False)
    result = await pool.get_next_key("claude_code")
    assert result is not None
    assert result.id == k2.id


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_skips_rate_limited(pool):
    """get_next_key skips keys whose rate_limit_resets_at is in the future."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    pool._active_key = k1
    await pool.mark_rate_limited(resets_at=time.time() + 7200)
    result = await pool.get_next_key("claude_code")
    assert result is not None
    assert result.id == k2.id


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_returns_expired_limit(pool):
    """get_next_key treats past rate_limit_resets_at as available."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    # Set resets_at to the past directly in DB
    conn = agent_db_module.get_db()
    past_ts = int(time.time()) - 100
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id = ?",
        (past_ts, k.id),
    )
    await conn.commit()
    result = await pool.get_next_key("claude_code")
    assert result is not None
    assert result.id == k.id


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_only_correct_provider(pool):
    """get_next_key never returns a key from a different provider."""
    _k_codex = await pool.add_key("codex", "sk-openai-test", "codex-key", 0)
    # No claude_code keys
    result = await pool.get_next_key("claude_code")
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_empty_pool(pool):
    """get_next_key returns None when the pool has no keys."""
    result = await pool.get_next_key("claude_code")
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_all_disabled(pool):
    """get_next_key returns None when all keys for the provider are disabled."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    # Disable both — requires second key present to avoid last-enabled guard
    await pool.update_key(k1.id, is_enabled=False)
    await pool.update_key(k2.id, is_enabled=False)
    result = await pool.get_next_key("claude_code")
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_get_next_key_lru_among_same_priority(pool):
    """Among same-priority keys, get_next_key selects the least-recently-used one."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 0)
    # Touch k1 (set last_used_at) to make k2 the LRU
    conn = agent_db_module.get_db()
    await conn.execute(
        "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?", (k1.id,)
    )
    await conn.commit()
    result = await pool.get_next_key("claude_code")
    assert result is not None
    assert result.id == k2.id


# ===========================================================================
# Rotation Tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_handle_rate_limit_rotates_to_next(pool):
    """handle_rate_limit returns the next available non-limited key."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    pool._active_key = k1
    result = await pool.handle_rate_limit(resets_at=time.time() + 3600)
    assert result is not None
    assert result.id == k2.id


@pytest.mark.asyncio(loop_scope="function")
async def test_handle_rate_limit_marks_current_key(pool):
    """handle_rate_limit marks the active key as rate-limited."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    _k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    pool._active_key = k1
    future_ts = time.time() + 3600
    await pool.handle_rate_limit(resets_at=future_ts)
    row = await _raw_key_row(k1.id)
    assert row["rate_limit_resets_at"] is not None
    assert row["rate_limit_resets_at"] > time.time()


@pytest.mark.asyncio(loop_scope="function")
async def test_handle_rate_limit_stores_previous_key_id(pool):
    """handle_rate_limit sets _previous_key_id to the outgoing key."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    _k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    pool._active_key = k1
    await pool.handle_rate_limit(resets_at=time.time() + 3600)
    assert pool.previous_key_id == k1.id


@pytest.mark.asyncio(loop_scope="function")
async def test_handle_rate_limit_two_keys_ping_pong(pool):
    """With 2 keys, successive rate limits alternate between keys."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)

    # First rate limit k1 → should get k2
    pool._active_key = k1
    result1 = await pool.handle_rate_limit(resets_at=time.time() + 3600)
    assert result1 is not None
    assert result1.id == k2.id

    # Clear k1's rate limit so pool has a fresh available key
    await pool.clear_rate_limit(k1.id)

    # Now rate limit k2 → should get k1
    pool._active_key = k2
    result2 = await pool.handle_rate_limit(resets_at=time.time() + 3600)
    assert result2 is not None
    assert result2.id == k1.id


@pytest.mark.asyncio(loop_scope="function")
async def test_handle_rate_limit_all_exhausted_codex_disabled(pool):
    """handle_rate_limit returns None when all claude_code keys are rate-limited and codex disabled."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    _k_codex = await pool.add_key("codex", "sk-openai-test", "codex", 0)
    pool._active_key = k1
    result = await pool.handle_rate_limit(resets_at=time.time() + 3600)
    # codex_fallback_enabled defaults to false
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_rotation_preserves_run_id(pool_with_run):
    """Key rotation preserves the same run_id — no new run created."""
    pool, run_id = pool_with_run
    k1 = await pool.add_key("claude_code", "sk-run-id-1", "k1", 0)
    k2 = await pool.add_key("claude_code", "sk-run-id-2", "k2", 1)
    pool._active_key = k1
    await pool.handle_rate_limit(resets_at=time.time() + 3600)
    assert pool._run_id == run_id
    conn = agent_db_module.get_db()
    cursor = await conn.execute(
        "SELECT count(*) FROM audit_log WHERE run_id = ?", (run_id,),
    )
    count = (await cursor.fetchone())[0]
    assert count >= 2  # at least key_rate_limited + key_rotated


@pytest.mark.asyncio(loop_scope="function")
async def test_handle_rate_limit_all_exhausted_codex_enabled(pool):
    """handle_rate_limit falls back to codex when all claude_code keys are rate-limited and codex enabled."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    k_codex = await pool.add_key("codex", "sk-openai-test", "codex", 0)
    await pool.update_config({"codex_fallback_enabled": "true"})
    pool._active_key = k1
    result = await pool.handle_rate_limit(resets_at=time.time() + 3600)
    assert result is not None
    assert result.provider == "codex"
    assert result.id == k_codex.id


@pytest.mark.asyncio(loop_scope="function")
async def test_handle_rate_limit_logs_rotation_audit(pool_with_run):
    """handle_rate_limit writes a key_rotated audit log entry when run_id is set."""
    pool, run_id = pool_with_run
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    _k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    pool._active_key = k1
    await pool.handle_rate_limit(resets_at=time.time() + 3600)
    conn = agent_db_module.get_db()
    cursor = await conn.execute(
        "SELECT * FROM audit_log WHERE run_id = ? AND event_type = 'key_rotated'",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row is not None


# ===========================================================================
# Config Tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_default_config_values(pool):
    """Fresh DB has all DEFAULT_CONFIG entries after first get_config call."""
    config = await pool.get_config()
    for key, expected in DEFAULT_CONFIG.items():
        assert key in config, f"Missing default config key: {key}"
        assert config[key] == expected, f"Wrong default for {key}: {config[key]!r} != {expected!r}"


@pytest.mark.asyncio(loop_scope="function")
async def test_update_config_persists(pool):
    """update_config stores new values that survive a subsequent get_config call."""
    await pool.update_config({"max_wait_minutes": "120"})
    config = await pool.get_config()
    assert config["max_wait_minutes"] == "120"


@pytest.mark.asyncio(loop_scope="function")
async def test_update_config_upserts_existing_key(pool):
    """update_config overwrites an existing config key without duplicating rows."""
    await pool.update_config({"max_wait_minutes": "30"})
    await pool.update_config({"max_wait_minutes": "45"})
    config = await pool.get_config()
    assert config["max_wait_minutes"] == "45"


@pytest.mark.asyncio(loop_scope="function")
async def test_codex_fallback_default_off(pool):
    """codex_fallback_enabled is 'false' by default."""
    config = await pool.get_config()
    assert config.get("codex_fallback_enabled") == "false"


@pytest.mark.asyncio(loop_scope="function")
async def test_invalid_rotation_strategy_rejected(pool):
    """update_config raises ValueError for an unrecognised rotation_strategy."""
    with pytest.raises(ValueError, match="Invalid rotation strategy"):
        await pool.update_config({"rotation_strategy": "round_robin_nonexistent"})


@pytest.mark.asyncio(loop_scope="function")
async def test_unknown_config_key_rejected(pool):
    """update_config raises ValueError for keys not in DEFAULT_CONFIG."""
    with pytest.raises(ValueError, match="Unknown config key"):
        await pool.update_config({"evil_key": "malicious_value"})


@pytest.mark.asyncio(loop_scope="function")
async def test_valid_rotation_strategy_accepted(pool):
    """update_config accepts every strategy in VALID_STRATEGIES."""
    for strategy in VALID_STRATEGIES:
        config = await pool.update_config({"rotation_strategy": strategy})
        assert config["rotation_strategy"] == strategy


@pytest.mark.asyncio(loop_scope="function")
async def test_update_config_returns_full_config(pool):
    """update_config returns the complete config dict after applying updates."""
    result = await pool.update_config({"auto_wait_enabled": "false"})
    assert isinstance(result, dict)
    assert "auto_wait_enabled" in result
    assert "codex_fallback_enabled" in result


# ===========================================================================
# Migration Tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_migrate_single_token_to_pool(initialized_db, master_key_path):
    """migrate_single_token_to_pool moves settings.claude_token into api_keys."""
    crypto_module._fernet = None
    from monitor.crypto import encrypt
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        conn = agent_db_module.get_db()
        raw_token = "sk-ant-migrated-key-abc"
        encrypted = encrypt(raw_token, master_key_path)
        await conn.execute(
            "INSERT INTO settings (key, value, encrypted) VALUES ('claude_token', ?, 1)",
            (encrypted,),
        )
        await conn.commit()

        result = await KeyPool.migrate_single_token_to_pool()
        assert result is True

        pool = KeyPool(run_id=None)
        keys = await pool.list_keys()
        assert len(keys) == 1
        assert keys[0]["provider"] == "claude_code"
        assert keys[0]["label"] == "Primary (migrated)"
    crypto_module._fernet = None


@pytest.mark.asyncio(loop_scope="function")
async def test_migrate_idempotent(initialized_db, master_key_path):
    """Running migrate_single_token_to_pool twice does not create duplicate keys."""
    crypto_module._fernet = None
    from monitor.crypto import encrypt
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        conn = agent_db_module.get_db()
        encrypted = encrypt("sk-ant-idempotent-test", master_key_path)
        await conn.execute(
            "INSERT INTO settings (key, value, encrypted) VALUES ('claude_token', ?, 1)",
            (encrypted,),
        )
        await conn.commit()

        first = await KeyPool.migrate_single_token_to_pool()
        assert first is True

        second = await KeyPool.migrate_single_token_to_pool()
        assert second is False

        pool = KeyPool(run_id=None)
        keys = await pool.list_keys()
        assert len(keys) == 1
    crypto_module._fernet = None


@pytest.mark.asyncio(loop_scope="function")
async def test_migrate_no_token_returns_false(initialized_db, master_key_path):
    """migrate_single_token_to_pool returns False when no settings.claude_token exists."""
    crypto_module._fernet = None
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        result = await KeyPool.migrate_single_token_to_pool()
        assert result is False
    crypto_module._fernet = None


@pytest.mark.asyncio(loop_scope="function")
async def test_migrate_preserves_encryption(initialized_db, master_key_path):
    """Migrated key round-trips through encryption: decrypted value matches original."""
    crypto_module._fernet = None
    from monitor.crypto import encrypt, decrypt
    raw_token = "sk-ant-encrypt-preservation-test"
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        conn = agent_db_module.get_db()
        encrypted = encrypt(raw_token, master_key_path)
        await conn.execute(
            "INSERT INTO settings (key, value, encrypted) VALUES ('claude_token', ?, 1)",
            (encrypted,),
        )
        await conn.commit()

        await KeyPool.migrate_single_token_to_pool()

        # Verify the stored encrypted_key decrypts back to the original
        cursor = await conn.execute("SELECT encrypted_key FROM api_keys LIMIT 1")
        row = await cursor.fetchone()
        assert row is not None
        decrypted = decrypt(row["encrypted_key"], master_key_path)
        assert decrypted == raw_token
    crypto_module._fernet = None


@pytest.mark.asyncio(loop_scope="function")
async def test_migrate_unencrypted_token_in_settings(initialized_db, master_key_path):
    """migrate handles a plaintext (unencrypted=0) claude_token in settings."""
    crypto_module._fernet = None
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        conn = agent_db_module.get_db()
        raw_token = "sk-ant-plaintext-token"
        await conn.execute(
            "INSERT INTO settings (key, value, encrypted) VALUES ('claude_token', ?, 0)",
            (raw_token,),
        )
        await conn.commit()

        result = await KeyPool.migrate_single_token_to_pool()
        assert result is True

        # Verify the key was stored encrypted
        cursor = await conn.execute("SELECT encrypted_key FROM api_keys LIMIT 1")
        row = await cursor.fetchone()
        assert row is not None
        assert raw_token not in row["encrypted_key"]
    crypto_module._fernet = None


# ===========================================================================
# Auto-Wait Tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_wait_disabled_returns_none(pool):
    """wait_for_next_available_key returns None when auto_wait_enabled=false."""
    await pool.update_config({"auto_wait_enabled": "false"})
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    pool._active_key = k
    await pool.mark_rate_limited(resets_at=time.time() + 60)
    result = await pool.wait_for_next_available_key()
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_wait_exceeds_max_returns_none(pool):
    """wait_for_next_available_key returns None when reset time exceeds max_wait."""
    await pool.update_config({"auto_wait_enabled": "true", "max_wait_minutes": "1"})
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    pool._active_key = k
    # Rate limit resets 2 hours in the future — exceeds 1-minute max
    await pool.mark_rate_limited(resets_at=time.time() + 7200)
    result = await pool.wait_for_next_available_key()
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_wait_no_rate_limited_keys_returns_none(pool):
    """wait_for_next_available_key returns None when no keys have a pending reset."""
    await pool.add_key("claude_code", "sk-test", "k1", 0)
    # No rate limits set — _get_earliest_resetting_key returns None
    result = await pool.wait_for_next_available_key()
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_wait_already_past_resets_returns_key(pool):
    """wait_for_next_available_key returns the key immediately if reset_at is in the past."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    # Set resets_at to the past directly in DB
    conn = agent_db_module.get_db()
    past_ts = int(time.time()) - 10
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id = ?",
        (past_ts, k.id),
    )
    await conn.commit()
    await pool.update_config({"auto_wait_enabled": "true", "max_wait_minutes": "60"})
    result = await pool.wait_for_next_available_key()
    assert result is not None
    assert result.id == k.id


@pytest.mark.asyncio(loop_scope="function")
async def test_wait_sleeps_and_returns_key(pool):
    """wait_for_next_available_key sleeps then returns the key (asyncio.sleep mocked)."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    # Set resets_at 30 seconds in the future (within max_wait of 60 minutes)
    future_ts = int(time.time()) + 30
    conn = agent_db_module.get_db()
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id = ?",
        (future_ts, k.id),
    )
    await conn.commit()
    await pool.update_config({"auto_wait_enabled": "true", "max_wait_minutes": "60"})

    with patch("key_pool.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await pool.wait_for_next_available_key()
    assert result is not None
    assert result.id == k.id
    # asyncio.sleep must have been called at least once
    assert mock_sleep.called


@pytest.mark.asyncio(loop_scope="function")
async def test_wait_stop_fn_aborts(pool):
    """wait_for_next_available_key returns None when should_stop_fn returns True."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    future_ts = int(time.time()) + 30
    conn = agent_db_module.get_db()
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id = ?",
        (future_ts, k.id),
    )
    await conn.commit()
    await pool.update_config({"auto_wait_enabled": "true", "max_wait_minutes": "60"})

    stop_flag = {"stop": False}

    def should_stop():
        stop_flag["stop"] = True
        return True

    with patch("key_pool.asyncio.sleep", new_callable=AsyncMock):
        result = await pool.wait_for_next_available_key(should_stop_fn=should_stop)
    assert result is None


# ===========================================================================
# Pool Status Tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_get_pool_status_structure(pool):
    """get_pool_status returns dict with expected keys."""
    await pool.add_key("claude_code", "sk-test", "k1", 0)
    status = await pool.get_pool_status()
    expected_keys = {
        "active_key_id",
        "total_keys",
        "available_keys",
        "rate_limited_keys",
        "earliest_reset_at",
        "seconds_until_reset",
        "keys",
    }
    assert expected_keys <= set(status.keys())


@pytest.mark.asyncio(loop_scope="function")
async def test_get_pool_status_counts(pool):
    """get_pool_status correctly counts available and rate-limited keys."""
    k1 = await pool.add_key("claude_code", "sk-test-1", "k1", 0)
    _k2 = await pool.add_key("claude_code", "sk-test-2", "k2", 1)
    # Rate-limit k1
    pool._active_key = k1
    await pool.mark_rate_limited(resets_at=time.time() + 3600)
    status = await pool.get_pool_status()
    assert status["total_keys"] == 2
    assert status["rate_limited_keys"] == 1
    assert status["available_keys"] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_get_pool_status_active_key_id(pool):
    """get_pool_status reflects the currently active key."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    pool._active_key = k
    status = await pool.get_pool_status()
    assert status["active_key_id"] == k.id


# ===========================================================================
# ApiKey dataclass property tests
# ===========================================================================

@pytest.mark.asyncio(loop_scope="function")
async def test_api_key_is_rate_limited_true(pool):
    """ApiKey.is_rate_limited is True when resets_at is in the future."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    pool._active_key = k
    await pool.mark_rate_limited(resets_at=time.time() + 3600)
    row = await _raw_key_row(k.id)
    api_key = KeyPool._row_to_key(
        type("Row", (), {**row, "__getitem__": lambda self, x: row[x]})()
    )
    # Use the actual fetched object
    updated_k = await pool._get_key_by_id(k.id)
    assert updated_k.is_rate_limited is True


@pytest.mark.asyncio(loop_scope="function")
async def test_api_key_is_rate_limited_false(pool):
    """ApiKey.is_rate_limited is False when resets_at is None."""
    k = await pool.add_key("claude_code", "sk-test", "k1", 0)
    assert k.is_rate_limited is False


@pytest.mark.asyncio(loop_scope="function")
async def test_api_key_decrypted_value(pool, master_key_path):
    """ApiKey.decrypted_value round-trips back to the original raw key."""
    raw = "sk-ant-round-trip-test-abc"
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        k = await pool.add_key("claude_code", raw, "k1", 0)
        assert k.decrypted_value == raw


@pytest.mark.asyncio(loop_scope="function")
async def test_api_key_masked_value(pool, master_key_path):
    """ApiKey.masked_value starts with first 4 chars and contains asterisks."""
    raw = "sk-ant-mask-test-xyz"
    with patch("key_pool.MASTER_KEY_PATH", master_key_path):
        k = await pool.add_key("claude_code", raw, "k1", 0)
        assert k.masked_value.startswith(raw[:4])
        assert "*" in k.masked_value
        assert raw not in k.masked_value
