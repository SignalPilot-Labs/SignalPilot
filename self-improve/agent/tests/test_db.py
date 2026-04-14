"""Unit tests for agent/db.py — SQLite audit/run database layer.

Uses a real temporary SQLite database (no mocks of aiosqlite) so that
SQL constraints, migrations, and row-factory behaviour are all exercised.

Each test gets an isolated database file via the `initialized_db` fixture,
which also resets the module-global `_db` connection to prevent state leakage
between tests.
"""

import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Make the agent package importable from the tests sub-directory
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as db_module
from db import (
    init_db,
    get_db,
    close_db,
    create_run,
    save_rate_limit_reset,
    save_session_id,
    get_run_for_resume,
    finish_run,
    log_tool_call,
    log_audit,
    update_run_status,
    mark_crashed_runs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def initialized_db(tmp_path):
    """Open a fresh database for each test, then close it and reset _db."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    yield db_path
    await close_db()
    # Belt-and-suspenders: ensure the module global is cleared even if
    # close_db() was called earlier in the test body.
    db_module._db = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _fetch_run(run_id: str) -> dict | None:
    """Return a run row as a plain dict, or None if not found."""
    conn = get_db()
    cursor = await conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_init_db_creates_database_file(tmp_path):
    """init_db creates the SQLite file on disk."""
    db_path = tmp_path / "new.db"
    assert not db_path.exists()
    await init_db(str(db_path))
    try:
        assert db_path.exists()
    finally:
        await close_db()
        db_module._db = None


@pytest.mark.asyncio(loop_scope="function")
async def test_init_db_creates_expected_tables(tmp_path):
    """init_db creates all required tables: runs, tool_calls, audit_log, etc."""
    db_path = str(tmp_path / "schema.db")
    await init_db(db_path)
    try:
        conn = get_db()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in await cursor.fetchall()}
        assert {"runs", "tool_calls", "audit_log", "control_signals", "settings"} <= tables
    finally:
        await close_db()
        db_module._db = None


@pytest.mark.asyncio(loop_scope="function")
async def test_init_db_sets_wal_mode(tmp_path):
    """init_db configures WAL journal mode."""
    db_path = str(tmp_path / "wal.db")
    await init_db(db_path)
    try:
        conn = get_db()
        cursor = await conn.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row[0].lower() == "wal"
    finally:
        await close_db()
        db_module._db = None


@pytest.mark.asyncio(loop_scope="function")
async def test_init_db_idempotent_called_twice(tmp_path):
    """Calling init_db twice on the same file does not raise (migrations are idempotent)."""
    db_path = str(tmp_path / "twice.db")
    await init_db(db_path)
    await close_db()
    db_module._db = None
    # Second call must succeed without errors
    await init_db(db_path)
    try:
        conn = get_db()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
        )
        assert await cursor.fetchone() is not None
    finally:
        await close_db()
        db_module._db = None


# ---------------------------------------------------------------------------
# get_db
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_get_db_returns_connection_after_init(initialized_db):
    """get_db returns the active connection after init_db."""
    conn = get_db()
    assert conn is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_get_db_raises_before_init():
    """get_db raises RuntimeError when the database has not been initialized."""
    # Make sure _db is None (no fixture initialized it)
    original = db_module._db
    db_module._db = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            get_db()
    finally:
        db_module._db = original


# ---------------------------------------------------------------------------
# close_db
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_close_db_sets_connection_to_none(tmp_path):
    """close_db sets the module-global _db to None."""
    db_path = str(tmp_path / "close.db")
    await init_db(db_path)
    assert db_module._db is not None
    await close_db()
    assert db_module._db is None


@pytest.mark.asyncio(loop_scope="function")
async def test_close_db_is_idempotent(tmp_path):
    """close_db can be called multiple times without raising."""
    db_path = str(tmp_path / "close2.db")
    await init_db(db_path)
    await close_db()
    db_module._db = None
    # Calling again when already None must not raise
    await close_db()
    assert db_module._db is None


# ---------------------------------------------------------------------------
# create_run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_create_run_returns_uuid_string(initialized_db):
    """create_run returns a valid UUID4 string."""
    run_id = await create_run("test/branch")
    # Must be parse-able as a UUID without raising
    parsed = uuid.UUID(run_id)
    assert str(parsed) == run_id


@pytest.mark.asyncio(loop_scope="function")
async def test_create_run_is_queryable(initialized_db):
    """The run created by create_run can be retrieved from the database."""
    run_id = await create_run("feature/my-branch")
    row = await _fetch_run(run_id)
    assert row is not None
    assert row["id"] == run_id
    assert row["branch_name"] == "feature/my-branch"
    assert row["status"] == "running"


@pytest.mark.asyncio(loop_scope="function")
async def test_create_run_stores_optional_fields(initialized_db):
    """create_run persists custom_prompt, duration_minutes, base_branch, github_repo."""
    run_id = await create_run(
        "feat/x",
        custom_prompt="do something cool",
        duration_minutes=30.0,
        base_branch="develop",
        github_repo="github.com/org/repo",
    )
    row = await _fetch_run(run_id)
    assert row["custom_prompt"] == "do something cool"
    assert row["duration_minutes"] == 30.0
    assert row["base_branch"] == "develop"
    assert row["github_repo"] == "github.com/org/repo"


@pytest.mark.asyncio(loop_scope="function")
async def test_create_run_unique_ids(initialized_db):
    """Each call to create_run produces a different run_id."""
    id1 = await create_run("branch-a")
    id2 = await create_run("branch-b")
    assert id1 != id2


# ---------------------------------------------------------------------------
# save_rate_limit_reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_save_rate_limit_reset_updates_column(initialized_db):
    """save_rate_limit_reset writes the timestamp to rate_limit_resets_at."""
    run_id = await create_run("branch")
    resets_at = 9_999_999_999
    await save_rate_limit_reset(run_id, resets_at)
    row = await _fetch_run(run_id)
    assert row["rate_limit_resets_at"] == resets_at


# ---------------------------------------------------------------------------
# save_session_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_save_session_id_updates_column(initialized_db):
    """save_session_id writes the SDK session ID to sdk_session_id."""
    run_id = await create_run("branch")
    session = "sess_abc123"
    await save_session_id(run_id, session)
    row = await _fetch_run(run_id)
    assert row["sdk_session_id"] == session


@pytest.mark.asyncio(loop_scope="function")
async def test_save_session_id_can_overwrite(initialized_db):
    """save_session_id overwrites a previously saved session ID."""
    run_id = await create_run("branch")
    await save_session_id(run_id, "first-session")
    await save_session_id(run_id, "second-session")
    row = await _fetch_run(run_id)
    assert row["sdk_session_id"] == "second-session"


# ---------------------------------------------------------------------------
# get_run_for_resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_get_run_for_resume_returns_none_for_nonexistent(initialized_db):
    """get_run_for_resume returns None when the run_id does not exist."""
    result = await get_run_for_resume(str(uuid.uuid4()))
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_get_run_for_resume_returns_dict_for_existing(initialized_db):
    """get_run_for_resume returns a dict with expected keys for a real run."""
    run_id = await create_run("branch", custom_prompt="resume me", duration_minutes=15.0)
    await save_session_id(run_id, "sess-xyz")
    result = await get_run_for_resume(run_id)
    assert result is not None
    assert isinstance(result, dict)
    assert result["id"] == run_id
    assert result["branch_name"] == "branch"
    assert result["status"] == "running"
    assert result["sdk_session_id"] == "sess-xyz"
    assert result["custom_prompt"] == "resume me"
    assert result["duration_minutes"] == 15.0


@pytest.mark.asyncio(loop_scope="function")
async def test_get_run_for_resume_contains_token_fields(initialized_db):
    """get_run_for_resume includes token/cost fields."""
    run_id = await create_run("branch")
    result = await get_run_for_resume(run_id)
    for field in ("total_cost_usd", "total_input_tokens", "total_output_tokens"):
        assert field in result


# ---------------------------------------------------------------------------
# finish_run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_finish_run_sets_status(initialized_db):
    """finish_run updates the status column."""
    run_id = await create_run("branch")
    await finish_run(run_id, status="success")
    row = await _fetch_run(run_id)
    assert row["status"] == "success"


@pytest.mark.asyncio(loop_scope="function")
async def test_finish_run_sets_ended_at(initialized_db):
    """finish_run populates the ended_at timestamp."""
    run_id = await create_run("branch")
    await finish_run(run_id, status="success")
    row = await _fetch_run(run_id)
    assert row["ended_at"] is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_finish_run_stores_cost_and_tokens(initialized_db):
    """finish_run persists cost and token counts."""
    run_id = await create_run("branch")
    await finish_run(
        run_id,
        status="success",
        total_cost_usd=1.23,
        total_input_tokens=1000,
        total_output_tokens=500,
    )
    row = await _fetch_run(run_id)
    assert row["total_cost_usd"] == pytest.approx(1.23)
    assert row["total_input_tokens"] == 1000
    assert row["total_output_tokens"] == 500


@pytest.mark.asyncio(loop_scope="function")
async def test_finish_run_counts_pre_phase_tool_calls(initialized_db):
    """finish_run sets total_tool_calls to the count of 'pre' phase tool_calls rows."""
    run_id = await create_run("branch")
    # Log 3 pre-phase and 1 post-phase tool call
    for _ in range(3):
        await log_tool_call(run_id, phase="pre", tool_name="Read")
    await log_tool_call(run_id, phase="post", tool_name="Read")
    await finish_run(run_id, status="success")
    row = await _fetch_run(run_id)
    assert row["total_tool_calls"] == 3


@pytest.mark.asyncio(loop_scope="function")
async def test_finish_run_stores_error_message(initialized_db):
    """finish_run persists the error_message field."""
    run_id = await create_run("branch")
    await finish_run(run_id, status="error", error_message="something went wrong")
    row = await _fetch_run(run_id)
    assert row["error_message"] == "something went wrong"


@pytest.mark.asyncio(loop_scope="function")
async def test_finish_run_stores_pr_url(initialized_db):
    """finish_run persists the pr_url field."""
    run_id = await create_run("branch")
    await finish_run(run_id, status="success", pr_url="https://github.com/org/repo/pull/42")
    row = await _fetch_run(run_id)
    assert row["pr_url"] == "https://github.com/org/repo/pull/42"


# ---------------------------------------------------------------------------
# log_tool_call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_log_tool_call_returns_lastrowid(initialized_db):
    """log_tool_call returns a positive integer row ID."""
    run_id = await create_run("branch")
    row_id = await log_tool_call(run_id, phase="pre", tool_name="Bash")
    assert isinstance(row_id, int)
    assert row_id > 0


@pytest.mark.asyncio(loop_scope="function")
async def test_log_tool_call_row_ids_increment(initialized_db):
    """Successive log_tool_call calls return incrementing row IDs."""
    run_id = await create_run("branch")
    id1 = await log_tool_call(run_id, phase="pre", tool_name="Read")
    id2 = await log_tool_call(run_id, phase="pre", tool_name="Write")
    assert id2 > id1


@pytest.mark.asyncio(loop_scope="function")
async def test_log_tool_call_inserts_record(initialized_db):
    """log_tool_call stores all expected fields in the database."""
    run_id = await create_run("branch")
    row_id = await log_tool_call(
        run_id,
        phase="pre",
        tool_name="Bash",
        input_data={"command": "ls"},
        output_data={"result": "file.txt"},
        duration_ms=42,
        permitted=False,
        deny_reason="blocked path",
        agent_role="ceo",
        tool_use_id="tu_abc",
        session_id="sess_1",
        agent_id="agent_1",
    )
    conn = get_db()
    cursor = await conn.execute("SELECT * FROM tool_calls WHERE id = ?", (row_id,))
    row = dict(await cursor.fetchone())
    assert row["run_id"] == run_id
    assert row["phase"] == "pre"
    assert row["tool_name"] == "Bash"
    assert row["duration_ms"] == 42
    assert row["permitted"] == 0  # stored as integer 0
    assert row["deny_reason"] == "blocked path"
    assert row["agent_role"] == "ceo"
    assert row["tool_use_id"] == "tu_abc"
    assert row["session_id"] == "sess_1"
    assert row["agent_id"] == "agent_1"
    # JSON-serialized fields
    import json
    assert json.loads(row["input_data"]) == {"command": "ls"}
    assert json.loads(row["output_data"]) == {"result": "file.txt"}


@pytest.mark.asyncio(loop_scope="function")
async def test_log_tool_call_permitted_defaults_to_true(initialized_db):
    """log_tool_call stores permitted=1 when not explicitly set to False."""
    run_id = await create_run("branch")
    row_id = await log_tool_call(run_id, phase="post", tool_name="Read")
    conn = get_db()
    cursor = await conn.execute(
        "SELECT permitted FROM tool_calls WHERE id = ?", (row_id,)
    )
    row = await cursor.fetchone()
    assert row[0] == 1


# ---------------------------------------------------------------------------
# log_audit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_log_audit_inserts_record(initialized_db):
    """log_audit inserts a row into audit_log with the correct fields."""
    run_id = await create_run("branch")
    await log_audit(run_id, event_type="run_started", details={"key": "value"})
    conn = get_db()
    cursor = await conn.execute(
        "SELECT * FROM audit_log WHERE run_id = ?", (run_id,)
    )
    row = dict(await cursor.fetchone())
    assert row["run_id"] == run_id
    assert row["event_type"] == "run_started"
    import json
    assert json.loads(row["details"]) == {"key": "value"}


@pytest.mark.asyncio(loop_scope="function")
async def test_log_audit_defaults_details_to_empty_dict(initialized_db):
    """log_audit uses {} as the default details when none are provided."""
    run_id = await create_run("branch")
    await log_audit(run_id, event_type="heartbeat")
    conn = get_db()
    cursor = await conn.execute(
        "SELECT details FROM audit_log WHERE run_id = ?", (run_id,)
    )
    row = await cursor.fetchone()
    import json
    assert json.loads(row[0]) == {}


@pytest.mark.asyncio(loop_scope="function")
async def test_log_audit_multiple_entries(initialized_db):
    """Multiple log_audit calls for the same run all appear in audit_log."""
    run_id = await create_run("branch")
    events = ["start", "pause", "resume", "finish"]
    for event in events:
        await log_audit(run_id, event_type=event)
    conn = get_db()
    cursor = await conn.execute(
        "SELECT count(*) FROM audit_log WHERE run_id = ?", (run_id,)
    )
    count_row = await cursor.fetchone()
    assert count_row[0] == len(events)


# ---------------------------------------------------------------------------
# update_run_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_update_run_status_changes_status(initialized_db):
    """update_run_status changes the status field to the given value."""
    run_id = await create_run("branch")
    await update_run_status(run_id, "paused")
    row = await _fetch_run(run_id)
    assert row["status"] == "paused"


@pytest.mark.asyncio(loop_scope="function")
async def test_update_run_status_can_transition_multiple_times(initialized_db):
    """update_run_status can be called multiple times on the same run."""
    run_id = await create_run("branch")
    for status in ("paused", "running", "paused"):
        await update_run_status(run_id, status)
    row = await _fetch_run(run_id)
    assert row["status"] == "paused"


# ---------------------------------------------------------------------------
# mark_crashed_runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_mark_crashed_runs_marks_running_as_crashed(initialized_db):
    """mark_crashed_runs transitions 'running' runs to 'crashed'."""
    run_id = await create_run("branch")
    assert (await _fetch_run(run_id))["status"] == "running"
    await mark_crashed_runs()
    assert (await _fetch_run(run_id))["status"] == "crashed"


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_crashed_runs_marks_paused_as_crashed(initialized_db):
    """mark_crashed_runs transitions 'paused' runs to 'crashed'."""
    run_id = await create_run("branch")
    await update_run_status(run_id, "paused")
    await mark_crashed_runs()
    assert (await _fetch_run(run_id))["status"] == "crashed"


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_crashed_runs_returns_affected_count(initialized_db):
    """mark_crashed_runs returns the number of rows it updated."""
    # Create 2 running and 1 paused run
    id1 = await create_run("branch-1")
    id2 = await create_run("branch-2")
    id3 = await create_run("branch-3")
    await update_run_status(id3, "paused")
    count = await mark_crashed_runs()
    assert count == 3


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_crashed_runs_does_not_affect_finished_runs(initialized_db):
    """mark_crashed_runs leaves 'success' and 'error' runs untouched."""
    run_id = await create_run("branch")
    await finish_run(run_id, status="success")
    count = await mark_crashed_runs()
    assert count == 0
    assert (await _fetch_run(run_id))["status"] == "success"


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_crashed_runs_sets_ended_at(initialized_db):
    """mark_crashed_runs populates ended_at on the crashed runs."""
    run_id = await create_run("branch")
    await mark_crashed_runs()
    row = await _fetch_run(run_id)
    assert row["ended_at"] is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_crashed_runs_sets_error_message(initialized_db):
    """mark_crashed_runs writes a crash error_message."""
    run_id = await create_run("branch")
    await mark_crashed_runs()
    row = await _fetch_run(run_id)
    assert row["error_message"] is not None
    assert len(row["error_message"]) > 0


@pytest.mark.asyncio(loop_scope="function")
async def test_mark_crashed_runs_zero_when_nothing_running(initialized_db):
    """mark_crashed_runs returns 0 when there are no running or paused runs."""
    count = await mark_crashed_runs()
    assert count == 0
