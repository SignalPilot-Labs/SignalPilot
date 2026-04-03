"""Runner-level integration tests: _run_loop + KeyPool + rate limit events.

These tests verify that runner._run_loop correctly interacts with KeyPool when
rate limit events arrive from the SDK client:

1. test_run_loop_rotates_on_rate_limit       — rotates key and requests client restart
2. test_run_loop_pauses_when_all_keys_exhausted — sets status=rate_limited when no keys left
3. test_run_loop_codex_fallback_polls_for_claude — enters codex mode, polls, returns True
4. test_run_loop_legacy_no_key_pool          — no pool → legacy single-key rate-limit path

Strategy for isinstance() checks:
  runner.py does `isinstance(message, RateLimitEvent)` where `RateLimitEvent`
  is imported from the stubbed `claude_agent_sdk.types` MagicMock. We create
  real Python classes in this file, then patch the names inside the runner
  module so that isinstance() uses our classes.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Make agent package importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent.db as agent_db
from key_pool import KeyPool


# ---------------------------------------------------------------------------
# Real stub classes that runner.py's isinstance() checks will recognise
# ---------------------------------------------------------------------------

class _RateLimitInfo:
    """Mirrors the rate_limit_info object from the real SDK."""
    def __init__(self, status="rejected", resets_at=None, utilization=0.95):
        self.status = status
        self.resets_at = resets_at if resets_at is not None else time.time() + 3600
        self.utilization = utilization


class FakeRateLimitEvent:
    """Real Python class used as RateLimitEvent in tests."""
    def __init__(self, status="rejected", resets_at=None, utilization=0.95):
        self.rate_limit_info = _RateLimitInfo(status, resets_at, utilization)


class FakeResultMessage:
    """Real Python class used as ResultMessage in tests."""
    def __init__(self, session_id="sess-test", total_cost_usd=0.01, num_turns=1):
        self.session_id = session_id
        self.total_cost_usd = total_cost_usd
        self.usage = {"input_tokens": 10, "output_tokens": 20}
        self.num_turns = num_turns
        self.subtype = "success"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def pool_env(tmp_path):
    """Provide a KeyPool tied to a fresh run, real DB, real crypto.

    Yields dict with keys: pool, run_id, db_path.
    MASTER_KEY_PATH is patched for the duration of the test.
    """
    import monitor.crypto as crypto_mod
    from cryptography.fernet import Fernet

    key_path = str(tmp_path / "master.key")
    Path(key_path).write_bytes(Fernet.generate_key())

    db_path = str(tmp_path / "runner_test.db")
    await agent_db.init_db(db_path)

    crypto_mod._fernet = None

    with patch("key_pool.MASTER_KEY_PATH", key_path):
        run_id = await agent_db.create_run("test/runner-key-rotation")
        pool = KeyPool(run_id=run_id)
        yield {"pool": pool, "run_id": run_id, "db_path": db_path, "key_path": key_path}

    await agent_db.close_db()
    agent_db._db = None
    crypto_mod._fernet = None


async def _add_key(pool, raw_key, label, priority=0, provider="claude_code"):
    return await pool.add_key(provider, raw_key, label=label, priority=priority)


def _make_mock_client(events):
    """Return a mock SDK client whose receive_response() yields the given events.

    After yielding all events the generator stops (simulates end of round).
    """
    async def _receive_response():
        for event in events:
            yield event

    client = MagicMock()
    client.receive_response = _receive_response
    client.query = AsyncMock()
    client.interrupt = AsyncMock()
    return client


def _base_patches(runner_mod, rate_limit_class=None, result_class=None):
    """Return a dict of patches to apply when calling _run_loop.

    Patches:
    - runner.RateLimitEvent / runner.ResultMessage → our real stub classes
    - runner.AssistantMessage, runner.StreamEvent → never-matching classes
    - runner.session_gate → returns has_ended=False, elapsed_minutes=0
    - runner.signals → no pending signals
    - runner.git_ops.push_branch → no-op
    - runner.hooks._agent_role → "worker"
    - runner.session_gate.time_remaining_str → ""
    """
    patches = {}

    # Patch isinstance targets
    patches["RateLimitEvent"] = rate_limit_class or FakeRateLimitEvent
    patches["ResultMessage"] = result_class or FakeResultMessage

    # These won't be used in our minimal tests — use classes that nothing inherits from
    patches["AssistantMessage"] = type("_NeverAssistant", (), {})
    patches["StreamEvent"] = type("_NeverStream", (), {})

    return patches


# ---------------------------------------------------------------------------
# Test 1 — rotates to second key on rejected rate limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_run_loop_rotates_on_rate_limit(pool_env):
    """_run_loop signals should_restart_client=True and updates CLAUDE_CODE_OAUTH_TOKEN
    when a RateLimitEvent(rejected) arrives and a second key is available."""
    import agent.runner as runner_mod

    pool = pool_env["pool"]
    run_id = pool_env["run_id"]

    key_a = await _add_key(pool, "sk-alpha-key", "alpha", priority=0)
    key_b = await _add_key(pool, "sk-beta-key", "beta", priority=1)

    # Simulate runner having selected key_a
    pool._active_key = key_a

    rate_event = FakeRateLimitEvent(status="rejected", resets_at=time.time() + 3600)
    client = _make_mock_client([rate_event])

    patches = _base_patches(runner_mod)

    with (
        patch.object(runner_mod, "RateLimitEvent", patches["RateLimitEvent"]),
        patch.object(runner_mod, "ResultMessage", patches["ResultMessage"]),
        patch.object(runner_mod, "AssistantMessage", patches["AssistantMessage"]),
        patch.object(runner_mod, "StreamEvent", patches["StreamEvent"]),
        patch.object(runner_mod.db, "log_audit", new_callable=AsyncMock),
        patch.object(runner_mod.db, "update_run_status", new_callable=AsyncMock),
        patch.object(runner_mod.db, "save_rate_limit_reset", new_callable=AsyncMock),
        patch.object(runner_mod.db, "save_session_id", new_callable=AsyncMock),
        patch.object(runner_mod.signals, "drain_signal", new_callable=AsyncMock, return_value=None),
        patch.object(runner_mod.signals, "has_pending_signals", return_value=False),
        patch.object(runner_mod.session_gate, "has_ended", return_value=False),
        patch.object(runner_mod.session_gate, "elapsed_minutes", return_value=0.0),
        patch.object(runner_mod.session_gate, "time_remaining_str", return_value="60m"),
        patch.object(runner_mod.session_gate, "is_unlocked", return_value=True),
        patch.object(runner_mod.git_ops, "push_branch", return_value=None),
        patch.object(runner_mod.git_ops, "get_work_dir", return_value="/tmp"),
        patch.object(runner_mod.hooks, "_agent_role", "worker"),
    ):
        result = await runner_mod._run_loop(
            client=client,
            run_id=run_id,
            branch_name="test/rotation",
            custom_prompt=None,
            duration_minutes=60,
            model="claude-opus-4-5",
            fallback_model=None,
            base_branch="main",
            key_pool=pool,
        )

    final_status, total_cost, input_tok, output_tok, should_restart = result

    assert should_restart is True, "Expected should_restart_client=True after key rotation"
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == key_b.decrypted_value, (
        "Expected CLAUDE_CODE_OAUTH_TOKEN to be updated to key_b after rotation"
    )


# ---------------------------------------------------------------------------
# Test 2 — pauses run when all keys exhausted and auto-wait is disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_run_loop_pauses_when_all_keys_exhausted(pool_env):
    """_run_loop returns should_restart_client=False and status='rate_limited'
    when the only key is exhausted and auto_wait is disabled."""
    import agent.runner as runner_mod

    pool = pool_env["pool"]
    run_id = pool_env["run_id"]

    # One key, auto-wait disabled
    key_only = await _add_key(pool, "sk-only-key", "only-key", priority=0)
    pool._active_key = key_only

    await pool.update_config({"auto_wait_enabled": "false"})

    resets_at = time.time() + 300
    rate_event = FakeRateLimitEvent(status="rejected", resets_at=resets_at)
    client = _make_mock_client([rate_event])

    mock_update_status = AsyncMock()

    with (
        patch.object(runner_mod, "RateLimitEvent", FakeRateLimitEvent),
        patch.object(runner_mod, "ResultMessage", FakeResultMessage),
        patch.object(runner_mod, "AssistantMessage", type("_NA", (), {})),
        patch.object(runner_mod, "StreamEvent", type("_NS", (), {})),
        patch.object(runner_mod.db, "log_audit", new_callable=AsyncMock),
        patch.object(runner_mod.db, "update_run_status", mock_update_status),
        patch.object(runner_mod.db, "save_rate_limit_reset", new_callable=AsyncMock),
        patch.object(runner_mod.db, "save_session_id", new_callable=AsyncMock),
        patch.object(runner_mod.signals, "drain_signal", new_callable=AsyncMock, return_value=None),
        patch.object(runner_mod.signals, "has_pending_signals", return_value=False),
        patch.object(runner_mod.session_gate, "has_ended", return_value=False),
        patch.object(runner_mod.session_gate, "elapsed_minutes", return_value=0.0),
        patch.object(runner_mod.session_gate, "time_remaining_str", return_value="60m"),
        patch.object(runner_mod.session_gate, "is_unlocked", return_value=True),
        patch.object(runner_mod.git_ops, "push_branch", return_value=None),
        patch.object(runner_mod.git_ops, "get_work_dir", return_value="/tmp"),
        patch.object(runner_mod.hooks, "_agent_role", "worker"),
    ):
        result = await runner_mod._run_loop(
            client=client,
            run_id=run_id,
            branch_name="test/exhausted",
            custom_prompt=None,
            duration_minutes=60,
            model="claude-opus-4-5",
            fallback_model=None,
            base_branch="main",
            key_pool=pool,
        )

    final_status, total_cost, input_tok, output_tok, should_restart = result

    assert final_status == "rate_limited", (
        f"Expected status='rate_limited', got '{final_status}'"
    )
    assert should_restart is False, (
        "Expected should_restart_client=False when all keys exhausted"
    )

    # DB must have been told about the rate limit
    mock_update_status.assert_any_call(run_id, "rate_limited")


# ---------------------------------------------------------------------------
# Test 3 — codex fallback mode: polls for Claude key then returns True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_run_loop_codex_fallback_polls_for_claude(pool_env):
    """When all claude_code keys are exhausted but a codex key is available,
    _run_loop enters codex mode, polls for a claude key, and returns
    should_restart_client=True once a key becomes available."""
    import agent.runner as runner_mod
    from agent.codex_client import CodexClient

    pool = pool_env["pool"]
    run_id = pool_env["run_id"]

    # One claude key (will be rate-limited), one codex key
    claude_key = await _add_key(pool, "sk-claude-x", "claude-only", priority=0, provider="claude_code")
    codex_key = await _add_key(pool, "sk-codex-x", "codex-fb", priority=0, provider="codex")

    await pool.update_config({"codex_fallback_enabled": "true", "max_wait_minutes": "2"})
    pool._active_key = claude_key

    resets_at = time.time() + 120
    rate_event = FakeRateLimitEvent(status="rejected", resets_at=resets_at)
    client = _make_mock_client([rate_event])

    # get_next_key: first call returns None (still rate-limited), second returns claude_key
    call_count = {"n": 0}
    original_get_next_key = pool.get_next_key

    async def _patched_get_next_key(provider="claude_code"):
        if provider == "claude_code":
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None
            return claude_key
        return await original_get_next_key(provider=provider)

    with (
        patch.object(runner_mod, "RateLimitEvent", FakeRateLimitEvent),
        patch.object(runner_mod, "ResultMessage", FakeResultMessage),
        patch.object(runner_mod, "AssistantMessage", type("_NA", (), {})),
        patch.object(runner_mod, "StreamEvent", type("_NS", (), {})),
        patch.object(runner_mod.db, "log_audit", new_callable=AsyncMock),
        patch.object(runner_mod.db, "update_run_status", new_callable=AsyncMock),
        patch.object(runner_mod.db, "save_rate_limit_reset", new_callable=AsyncMock),
        patch.object(runner_mod.db, "save_session_id", new_callable=AsyncMock),
        patch.object(runner_mod.signals, "drain_signal", new_callable=AsyncMock, return_value=None),
        patch.object(runner_mod.signals, "has_pending_signals", return_value=False),
        patch.object(runner_mod.session_gate, "has_ended", return_value=False),
        patch.object(runner_mod.session_gate, "elapsed_minutes", return_value=0.0),
        patch.object(runner_mod.session_gate, "time_remaining_str", return_value="60m"),
        patch.object(runner_mod.session_gate, "is_unlocked", return_value=True),
        patch.object(runner_mod.git_ops, "push_branch", return_value=None),
        patch.object(runner_mod.git_ops, "get_work_dir", return_value="/tmp"),
        patch.object(runner_mod.hooks, "_agent_role", "worker"),
        # Speed up the poll loop: skip actual sleep
        patch("agent.runner.asyncio.sleep", new_callable=AsyncMock),
        patch.object(pool, "get_next_key", side_effect=_patched_get_next_key),
    ):
        result = await runner_mod._run_loop(
            client=client,
            run_id=run_id,
            branch_name="test/codex-fallback",
            custom_prompt=None,
            duration_minutes=60,
            model="claude-opus-4-5",
            fallback_model=None,
            base_branch="main",
            key_pool=pool,
        )

    final_status, total_cost, input_tok, output_tok, should_restart = result

    assert should_restart is True, (
        "Expected should_restart_client=True once Claude key became available after codex mode"
    )
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == claude_key.decrypted_value, (
        "Expected CLAUDE_CODE_OAUTH_TOKEN to be updated to claude_key after codex polling"
    )
    # get_next_key must have been called at least twice (once None, once key)
    assert call_count["n"] >= 2, (
        f"Expected at least 2 polls for claude key, got {call_count['n']}"
    )


# ---------------------------------------------------------------------------
# Test 4 — legacy path (no key pool): rate limit with same fallback model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_run_loop_legacy_no_key_pool(pool_env):
    """When key_pool=None and fallback_model equals model (same), _run_loop
    takes the legacy path and sets status='rate_limited'."""
    import agent.runner as runner_mod

    run_id = pool_env["run_id"]

    resets_at = time.time() + 600
    rate_event = FakeRateLimitEvent(status="rejected", resets_at=resets_at)
    client = _make_mock_client([rate_event])

    MODEL = "claude-opus-4-5"  # same for both primary and fallback → legacy pause path

    mock_update_status = AsyncMock()
    mock_save_reset = AsyncMock()

    with (
        patch.object(runner_mod, "RateLimitEvent", FakeRateLimitEvent),
        patch.object(runner_mod, "ResultMessage", FakeResultMessage),
        patch.object(runner_mod, "AssistantMessage", type("_NA", (), {})),
        patch.object(runner_mod, "StreamEvent", type("_NS", (), {})),
        patch.object(runner_mod.db, "log_audit", new_callable=AsyncMock),
        patch.object(runner_mod.db, "update_run_status", mock_update_status),
        patch.object(runner_mod.db, "save_rate_limit_reset", mock_save_reset),
        patch.object(runner_mod.db, "save_session_id", new_callable=AsyncMock),
        patch.object(runner_mod.signals, "drain_signal", new_callable=AsyncMock, return_value=None),
        patch.object(runner_mod.signals, "has_pending_signals", return_value=False),
        patch.object(runner_mod.session_gate, "has_ended", return_value=False),
        patch.object(runner_mod.session_gate, "elapsed_minutes", return_value=0.0),
        patch.object(runner_mod.session_gate, "time_remaining_str", return_value="60m"),
        patch.object(runner_mod.session_gate, "is_unlocked", return_value=True),
        patch.object(runner_mod.git_ops, "push_branch", return_value=None),
        patch.object(runner_mod.git_ops, "get_work_dir", return_value="/tmp"),
        patch.object(runner_mod.hooks, "_agent_role", "worker"),
    ):
        result = await runner_mod._run_loop(
            client=client,
            run_id=run_id,
            branch_name="test/legacy",
            custom_prompt=None,
            duration_minutes=60,
            model=MODEL,
            fallback_model=MODEL,  # same → no fallback shortcut → pause
            base_branch="main",
            key_pool=None,          # explicit: no key pool
        )

    final_status, total_cost, input_tok, output_tok, should_restart = result

    assert final_status == "rate_limited", (
        f"Expected status='rate_limited' on legacy path, got '{final_status}'"
    )
    assert should_restart is False, (
        "Expected should_restart_client=False on legacy rate-limit path"
    )

    # DB must record the rate-limited status and reset time
    mock_update_status.assert_any_call(run_id, "rate_limited")
    mock_save_reset.assert_called_once()
    saved_reset_at = mock_save_reset.call_args[0][1]
    assert saved_reset_at == int(resets_at), (
        f"save_rate_limit_reset was called with {saved_reset_at}, expected {int(resets_at)}"
    )
