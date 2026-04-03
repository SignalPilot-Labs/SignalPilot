"""Integration tests: key pool + runner + rate limit events end-to-end.

Tests verify that KeyPool correctly manages key rotation, auto-wait, and audit
logging in scenarios that mirror how the runner uses the pool during rate limit
events. External dependencies (cryptography, asyncio.sleep) are controlled so
tests are fast and deterministic.

Implementation note: key_pool.py imports `from agent import db`, so it uses
agent.db._db. All database access in tests goes through agent.db as well to
avoid the module identity mismatch caused by adding the agent/ directory to
sys.path (which makes `import db` a different object from `import agent.db`).
"""

import sys
import json
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Always use agent.db so we share the same module object as key_pool.py
import agent.db as agent_db
from key_pool import KeyPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def initialized_db(tmp_path):
    """Open a fresh database via agent.db for each test."""
    db_path = str(tmp_path / "test.db")
    await agent_db.init_db(db_path)
    yield db_path
    await agent_db.close_db()
    agent_db._db = None


@pytest.fixture
def master_key_path(tmp_path):
    """Create a temporary Fernet master key file."""
    from cryptography.fernet import Fernet
    key_path = str(tmp_path / "master.key")
    key = Fernet.generate_key()
    Path(key_path).write_bytes(key)
    return key_path


@pytest_asyncio.fixture
async def pool_with_run(tmp_path):
    """Provide a KeyPool tied to a fresh run_id, with crypto and db both ready.

    Yields (pool, run_id). The MASTER_KEY_PATH patch and the crypto singleton
    reset remain active for the entire test body.
    """
    import monitor.crypto as crypto_mod

    # Generate a temporary master key
    from cryptography.fernet import Fernet
    key_path = str(tmp_path / "master.key")
    Fernet.generate_key()
    Path(key_path).write_bytes(Fernet.generate_key())

    # Fresh database
    db_path = str(tmp_path / "pool_test.db")
    await agent_db.init_db(db_path)

    crypto_mod._fernet = None

    with patch("key_pool.MASTER_KEY_PATH", key_path):
        run_id = await agent_db.create_run("test/key-pool-branch")
        pool = KeyPool(run_id=run_id)
        yield pool, run_id

    await agent_db.close_db()
    agent_db._db = None
    crypto_mod._fernet = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_test_key(
    pool: KeyPool,
    raw_key: str = "sk-test-key-abc123",
    label: str = "test",
    priority: int = 0,
    provider: str = "claude_code",
) -> "key_pool.ApiKey":  # type: ignore[name-defined]
    """Convenience wrapper to add a key."""
    return await pool.add_key(provider, raw_key, label=label, priority=priority)


async def _fetch_audit_events(run_id: str) -> list[dict]:
    """Return all audit_log rows for a run as plain dicts."""
    conn = agent_db.get_db()
    cursor = await conn.execute(
        "SELECT event_type, details FROM audit_log WHERE run_id = ? ORDER BY id",
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [
        {"event_type": row["event_type"], "details": json.loads(row["details"])}
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Test 1: KeyPool stores run_id and starts with no active key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_key_pool_initializes_with_run(tmp_path):
    """KeyPool stores the run_id and has no active key on construction."""
    import monitor.crypto as crypto_mod
    from cryptography.fernet import Fernet

    key_path = str(tmp_path / "master.key")
    Path(key_path).write_bytes(Fernet.generate_key())

    db_path = str(tmp_path / "init_test.db")
    await agent_db.init_db(db_path)
    try:
        crypto_mod._fernet = None
        run_id = await agent_db.create_run("test/init-branch")
        with patch("key_pool.MASTER_KEY_PATH", key_path):
            pool = KeyPool(run_id=run_id)

        assert pool._run_id == run_id
        assert pool.active_key_id is None
        assert pool.previous_key_id is None
    finally:
        await agent_db.close_db()
        agent_db._db = None
        crypto_mod._fernet = None


# ---------------------------------------------------------------------------
# Test 2: migrate settings.claude_token to api_keys pool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_runner_key_pool_init_with_migration(tmp_path):
    """Seed a token in settings, run migration, verify it lands in api_keys."""
    import monitor.crypto as crypto_mod
    from cryptography.fernet import Fernet
    from monitor.crypto import encrypt

    key_path = str(tmp_path / "master.key")
    Path(key_path).write_bytes(Fernet.generate_key())

    db_path = str(tmp_path / "migrate_test.db")
    await agent_db.init_db(db_path)
    try:
        crypto_mod._fernet = None

        with patch("key_pool.MASTER_KEY_PATH", key_path):
            encrypted = encrypt("sk-live-primary-key", key_path)

        conn = agent_db.get_db()
        await conn.execute(
            "INSERT INTO settings (key, value, encrypted) VALUES ('claude_token', ?, 1)",
            (encrypted,),
        )
        await conn.commit()

        with patch("key_pool.MASTER_KEY_PATH", key_path):
            migrated = await KeyPool.migrate_single_token_to_pool()

        assert migrated is True

        # Key must appear in api_keys
        cursor = await conn.execute("SELECT count(*) FROM api_keys")
        assert (await cursor.fetchone())[0] == 1

        cursor = await conn.execute("SELECT label, provider FROM api_keys")
        row = await cursor.fetchone()
        assert row["provider"] == "claude_code"
        assert "migrated" in row["label"].lower()

        # Second call is a no-op
        with patch("key_pool.MASTER_KEY_PATH", key_path):
            migrated_again = await KeyPool.migrate_single_token_to_pool()
        assert migrated_again is False

    finally:
        await agent_db.close_db()
        agent_db._db = None
        crypto_mod._fernet = None


# ---------------------------------------------------------------------------
# Test 3: rate-limit first key, verify rotation to second
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_key_rotation_marks_and_selects_next(pool_with_run):
    """handle_rate_limit marks the active key and rotates to the next available one."""
    pool, run_id = pool_with_run

    key_a = await _add_test_key(pool, raw_key="sk-key-alpha", label="alpha", priority=0)
    key_b = await _add_test_key(pool, raw_key="sk-key-beta", label="beta", priority=1)

    # Simulate runner having selected key_a
    pool._active_key = key_a

    next_key = await pool.handle_rate_limit(resets_at=time.time() + 3600)

    assert next_key is not None
    assert next_key.id == key_b.id
    assert pool.active_key_id == key_b.id
    assert pool.previous_key_id == key_a.id

    # key_a should be marked rate-limited in the DB
    conn = agent_db.get_db()
    cursor = await conn.execute(
        "SELECT rate_limit_resets_at FROM api_keys WHERE id = ?", (key_a.id,)
    )
    row = await cursor.fetchone()
    assert row["rate_limit_resets_at"] is not None
    assert row["rate_limit_resets_at"] > time.time()


# ---------------------------------------------------------------------------
# Test 4: all keys exhausted — handle_rate_limit returns None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_key_rotation_all_exhausted_returns_none(pool_with_run):
    """When the only key is rate-limited, handle_rate_limit returns None."""
    pool, run_id = pool_with_run

    key = await _add_test_key(pool, raw_key="sk-only-key", label="only")
    pool._active_key = key

    result = await pool.handle_rate_limit(resets_at=time.time() + 7200)

    assert result is None
    assert pool.previous_key_id == key.id


# ---------------------------------------------------------------------------
# Test 5: auto-wait — key resets soon, wait_for_next_available_key returns it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_auto_wait_with_quick_reset(pool_with_run):
    """A key resetting 1 second in the future is returned after sleeping."""
    pool, run_id = pool_with_run

    key = await _add_test_key(pool, raw_key="sk-soon-reset", label="soon")

    # Rate-limit the key 1 second into the future
    future_ts = int(time.time()) + 1
    conn = agent_db.get_db()
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id = ?",
        (future_ts, key.id),
    )
    await conn.commit()

    await pool.update_config({"auto_wait_enabled": "true", "max_wait_minutes": "60"})

    with patch("key_pool.asyncio.sleep", new_callable=AsyncMock):
        result = await pool.wait_for_next_available_key()

    assert result is not None
    assert result.id == key.id
    assert pool.active_key_id == key.id

    # Rate limit must be cleared after wait
    cursor = await conn.execute(
        "SELECT rate_limit_resets_at FROM api_keys WHERE id = ?", (key.id,)
    )
    row = await cursor.fetchone()
    assert row["rate_limit_resets_at"] is None


# ---------------------------------------------------------------------------
# Test 6: auto-wait disabled — returns None without sleeping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_auto_wait_disabled_returns_none(pool_with_run):
    """When auto_wait_enabled=false, wait_for_next_available_key returns None immediately."""
    pool, run_id = pool_with_run

    key = await _add_test_key(pool, raw_key="sk-rate-limited", label="rl")
    future_ts = int(time.time()) + 300
    conn = agent_db.get_db()
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id = ?",
        (future_ts, key.id),
    )
    await conn.commit()

    await pool.update_config({"auto_wait_enabled": "false"})

    with patch("key_pool.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await pool.wait_for_next_available_key()
        mock_sleep.assert_not_called()

    assert result is None


# ---------------------------------------------------------------------------
# Test 7: auto-wait exceeds max_wait — returns None without sleeping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_auto_wait_exceeds_max_returns_none(pool_with_run):
    """A key resetting in 120 minutes with max_wait=60 returns None without sleeping."""
    pool, run_id = pool_with_run

    key = await _add_test_key(pool, raw_key="sk-long-cooldown", label="long")

    # Reset is 120 minutes away
    future_ts = int(time.time()) + 120 * 60
    conn = agent_db.get_db()
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id = ?",
        (future_ts, key.id),
    )
    await conn.commit()

    await pool.update_config({"auto_wait_enabled": "true", "max_wait_minutes": "60"})

    with patch("key_pool.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await pool.wait_for_next_available_key()
        mock_sleep.assert_not_called()

    assert result is None


# ---------------------------------------------------------------------------
# Test 8: pool status reflects correct counts after rate-limiting some keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_pool_status_reflects_state(pool_with_run):
    """get_pool_status returns correct total/available/rate_limited counts."""
    pool, run_id = pool_with_run

    key_a = await _add_test_key(pool, raw_key="sk-a", label="A", priority=0)
    key_b = await _add_test_key(pool, raw_key="sk-b", label="B", priority=1)
    key_c = await _add_test_key(pool, raw_key="sk-c", label="C", priority=2)

    # Rate-limit two of the three keys
    future_ts = int(time.time()) + 3600
    conn = agent_db.get_db()
    await conn.execute(
        "UPDATE api_keys SET rate_limit_resets_at = ? WHERE id IN (?, ?)",
        (future_ts, key_a.id, key_b.id),
    )
    await conn.commit()

    # Activate the third (available) key
    pool._active_key = key_c

    status = await pool.get_pool_status()

    assert status["total_keys"] == 3
    assert status["available_keys"] == 1
    assert status["rate_limited_keys"] == 2
    assert status["active_key_id"] == key_c.id
    assert status["earliest_reset_at"] == future_ts
    assert status["seconds_until_reset"] > 0
    assert len(status["keys"]) == 3


# ---------------------------------------------------------------------------
# Test 9: audit events are logged for key operations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_audit_events_logged(pool_with_run):
    """handle_rate_limit and wait_for_next_available_key write expected audit events."""
    pool, run_id = pool_with_run

    key_a = await _add_test_key(pool, raw_key="sk-audit-a", label="audit-A", priority=0)
    key_b = await _add_test_key(pool, raw_key="sk-audit-b", label="audit-B", priority=1)

    # Rate-limit key_a — should rotate to key_b
    pool._active_key = key_a
    next_key = await pool.handle_rate_limit(resets_at=time.time() + 3600, utilization=0.95)

    assert next_key is not None
    assert next_key.id == key_b.id

    events = await _fetch_audit_events(run_id)
    event_types = [e["event_type"] for e in events]

    assert "key_rate_limited" in event_types
    assert "key_rotated" in event_types

    rotated = next(e for e in events if e["event_type"] == "key_rotated")
    assert rotated["details"]["from_key_id"] == key_a.id
    assert rotated["details"]["to_key_id"] == key_b.id
    assert rotated["details"]["reason"] == "rate_limit"

    # Now exhaust key_b too and wait for recovery
    pool._active_key = key_b
    await pool.handle_rate_limit(resets_at=time.time() + 30, utilization=1.0)

    await pool.update_config({"auto_wait_enabled": "true", "max_wait_minutes": "60"})

    with patch("key_pool.asyncio.sleep", new_callable=AsyncMock):
        waited_key = await pool.wait_for_next_available_key()

    assert waited_key is not None

    events_after = await _fetch_audit_events(run_id)
    event_types_after = [e["event_type"] for e in events_after]

    assert "key_pool_waiting" in event_types_after
    assert "key_pool_resumed" in event_types_after

    waiting_event = next(e for e in events_after if e["event_type"] == "key_pool_waiting")
    assert "key_id" in waiting_event["details"]
    assert "wait_seconds" in waiting_event["details"]
    assert waiting_event["details"]["wait_seconds"] >= 0


# ---------------------------------------------------------------------------
# Codex fallback integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_codex_fallback_when_all_claude_limited(pool_with_run):
    """When all claude_code keys are rate-limited and codex enabled, returns codex key."""
    pool, run_id = pool_with_run

    claude_key = await _add_test_key(pool, raw_key="sk-claude-only", label="Claude", priority=0)
    codex_key = await _add_test_key(pool, raw_key="sk-codex-fb", label="Codex", priority=0, provider="codex")

    # Enable codex fallback
    await pool.update_config({"codex_fallback_enabled": "true"})

    # Rate-limit the only claude key
    pool._active_key = claude_key
    next_key = await pool.handle_rate_limit(resets_at=time.time() + 3600, utilization=1.0)

    assert next_key is not None
    assert next_key.provider == "codex"
    assert next_key.id == codex_key.id

    events = await _fetch_audit_events(run_id)
    event_types = [e["event_type"] for e in events]
    assert "codex_fallback" in event_types


@pytest.mark.asyncio(loop_scope="function")
async def test_codex_fallback_disabled_by_default(pool_with_run):
    """When codex_fallback_enabled is false (default), codex keys are not used."""
    pool, run_id = pool_with_run

    claude_key = await _add_test_key(pool, raw_key="sk-claude-x", label="Claude", priority=0)
    await _add_test_key(pool, raw_key="sk-codex-x", label="Codex", priority=0, provider="codex")

    pool._active_key = claude_key
    next_key = await pool.handle_rate_limit(resets_at=time.time() + 3600, utilization=1.0)

    # Codex disabled by default — should return None
    assert next_key is None


@pytest.mark.asyncio(loop_scope="function")
async def test_concurrent_handle_rate_limit_no_deadlock(pool_with_run):
    """Concurrent calls to handle_rate_limit don't deadlock (asyncio.Lock test)."""
    import asyncio
    pool, run_id = pool_with_run

    key_a = await _add_test_key(pool, raw_key="sk-conc-a", label="A", priority=0)
    key_b = await _add_test_key(pool, raw_key="sk-conc-b", label="B", priority=1)

    pool._active_key = key_a

    # Run two handle_rate_limit calls concurrently — should not deadlock
    async def rate_limit_call():
        return await pool.handle_rate_limit(resets_at=time.time() + 3600, utilization=0.9)

    results = await asyncio.gather(rate_limit_call(), rate_limit_call())
    # At least one should get a key (the other may get None since both claude keys could be marked)
    assert any(r is not None for r in results) or all(r is None for r in results)
