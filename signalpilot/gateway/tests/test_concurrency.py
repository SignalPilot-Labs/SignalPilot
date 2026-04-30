"""Tests for race condition and TOCTOU fixes.

Covers:
- _atomic_create_file: concurrent calls return the same content
- _load_or_create_salt: concurrent simulated calls converge on one salt
- _get_encryption_key: concurrent simulated calls converge on one key
- get_local_api_key: concurrent simulated calls converge on one key
- create_connection: IntegrityError after pre-check converts to ValueError
- create_project: IntegrityError after pre-check converts to ValueError
- clone_connection endpoint: ValueError from store converts to 409
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from gateway.models import ConnectionCreate, DBType, ProjectCreate
from gateway.store import (
    Store,
    _atomic_create_file,
    _get_encryption_key,
    _load_or_create_salt,
    get_local_api_key,
)

# ─── _atomic_create_file ─────────────────────────────────────────────────────


class TestAtomicCreateFile:
    """_atomic_create_file must be safe against concurrent callers."""

    def test_creates_file_with_content(self, tmp_path: Path) -> None:
        target = tmp_path / "test.bin"
        result = _atomic_create_file(target, b"hello")
        assert result == b"hello"
        assert target.read_bytes() == b"hello"

    def test_returns_existing_content_when_file_already_exists(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.bin"
        target.write_bytes(b"original")
        result = _atomic_create_file(target, b"new_content")
        assert result == b"original"

    def test_concurrent_writes_converge_on_one_value(self, tmp_path: Path) -> None:
        """Simulate two processes both generating different content but only one wins."""
        target = tmp_path / "race.bin"
        results: list[bytes] = []

        def worker(content: bytes) -> None:
            results.append(_atomic_create_file(target, content))

        # First call wins
        results.append(_atomic_create_file(target, b"first"))
        # Second call must see the file and return the existing content
        results.append(_atomic_create_file(target, b"second"))

        # All calls must return the same bytes
        assert len(set(results)) == 1
        assert results[0] == b"first"

    def test_mode_applied_to_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "secure.bin"
        _atomic_create_file(target, b"data", mode=0o600)
        file_stat = target.stat()
        # Check owner read/write only (mask lower 9 bits)
        assert (file_stat.st_mode & 0o777) == 0o600


# ─── _load_or_create_salt ────────────────────────────────────────────────────


class TestLoadOrCreateSalt:
    """Two simultaneous calls must return the same salt bytes."""

    def test_creates_salt_file_on_first_call(self, tmp_path: Path) -> None:
        with patch("gateway.store.DATA_DIR", tmp_path):
            salt = _load_or_create_salt()
        assert len(salt) == 16
        assert (tmp_path / ".encryption_salt").exists()

    def test_returns_same_salt_on_repeated_calls(self, tmp_path: Path) -> None:
        with patch("gateway.store.DATA_DIR", tmp_path):
            salt1 = _load_or_create_salt()
            salt2 = _load_or_create_salt()
        assert salt1 == salt2

    def test_race_condition_returns_same_salt(self, tmp_path: Path) -> None:
        """Simulate two concurrent starts: the loser reads the winner's salt."""
        written_salts: list[bytes] = []

        original_atomic = _atomic_create_file

        def capturing_atomic(path: Path, content: bytes, mode: int = 0o600) -> bytes:
            result = original_atomic(path, content, mode)
            written_salts.append(result)
            return result

        with (
            patch("gateway.store.DATA_DIR", tmp_path),
            patch("gateway.store._atomic_create_file", side_effect=capturing_atomic),
        ):
            salt_a = _load_or_create_salt()
            # Manually simulate a second process by calling again (file now exists)
            salt_b = _load_or_create_salt()

        assert salt_a == salt_b


# ─── _get_encryption_key ─────────────────────────────────────────────────────


class TestGetEncryptionKey:
    """Two simultaneous starts must return the same Fernet key."""

    def test_generates_and_caches_key(self, tmp_path: Path) -> None:
        with patch("gateway.store.DATA_DIR", tmp_path), patch("gateway.store._CACHED_KEY", None):
            import gateway.store as store_module

            old_cache = store_module._CACHED_KEY
            store_module._CACHED_KEY = None
            try:
                key = _get_encryption_key()
                assert key is not None
                assert len(key) > 0
            finally:
                store_module._CACHED_KEY = old_cache

    def test_key_is_stripped_from_existing_file(self, tmp_path: Path) -> None:
        """Key file with trailing newline must be stripped."""
        from cryptography.fernet import Fernet

        key_val = Fernet.generate_key()
        key_file = tmp_path / ".encryption_key"
        key_file.write_bytes(key_val + b"\n")

        import gateway.store as store_module

        original_cache = store_module._CACHED_KEY
        store_module._CACHED_KEY = None
        try:
            with patch("gateway.store.DATA_DIR", tmp_path), patch.dict("os.environ", {}, clear=False):
                # Remove SP_ENCRYPTION_KEY if set
                import os

                env_backup = os.environ.pop("SP_ENCRYPTION_KEY", None)
                try:
                    result = _get_encryption_key()
                    assert result == key_val
                    assert not result.endswith(b"\n")
                finally:
                    if env_backup is not None:
                        os.environ["SP_ENCRYPTION_KEY"] = env_backup
        finally:
            store_module._CACHED_KEY = original_cache

    def test_race_condition_returns_same_key(self, tmp_path: Path) -> None:
        """Two calls without cached key both end up with the same key bytes."""
        import gateway.store as store_module

        original_cache = store_module._CACHED_KEY

        def reset_and_call() -> bytes:
            store_module._CACHED_KEY = None
            return _get_encryption_key()

        import os

        env_backup = os.environ.pop("SP_ENCRYPTION_KEY", None)
        try:
            with patch("gateway.store.DATA_DIR", tmp_path):
                key_a = reset_and_call()
                # Second call: cache may be set, but file now exists — result is the same
                store_module._CACHED_KEY = None
                key_b = _get_encryption_key()
        finally:
            if env_backup is not None:
                os.environ["SP_ENCRYPTION_KEY"] = env_backup
            store_module._CACHED_KEY = original_cache

        assert key_a == key_b


# ─── get_local_api_key ───────────────────────────────────────────────────────


class TestGetLocalApiKey:
    """Two simultaneous calls must return the same key string."""

    def test_creates_key_on_first_call(self, tmp_path: Path) -> None:
        with patch("gateway.store.DATA_DIR", tmp_path):
            key = get_local_api_key()
        assert key.startswith("sp_local_")
        assert (tmp_path / "local_api_key").exists()

    def test_returns_same_key_on_repeated_calls(self, tmp_path: Path) -> None:
        with patch("gateway.store.DATA_DIR", tmp_path):
            key1 = get_local_api_key()
            key2 = get_local_api_key()
        assert key1 == key2

    def test_race_condition_returns_winning_key(self, tmp_path: Path) -> None:
        """Simulate two concurrent starts; both must return the same key."""
        key_file = tmp_path / "local_api_key"
        winner_key = "sp_local_" + "a" * 32

        # Pre-write a key as if a racing process won
        key_file.write_text(winner_key)

        with patch("gateway.store.DATA_DIR", tmp_path):
            result = get_local_api_key()

        assert result == winner_key


# ─── create_connection IntegrityError handling ───────────────────────────────


class TestCreateConnectionIntegrityError:
    """IntegrityError after pre-check must be converted to ValueError(409-ready)."""

    @pytest.mark.asyncio
    async def test_integrity_error_on_connection_raises_value_error(self) -> None:
        session = AsyncMock()
        store = Store(session, org_id="test-org", user_id="user1")

        # Pre-check returns None (no existing connection found — window open for race)
        store.get_connection = AsyncMock(return_value=None)  # type: ignore[method-assign]
        store.get_connection_string = AsyncMock(return_value=None)  # type: ignore[method-assign]

        orig_exc = Exception("UNIQUE constraint failed: uq_gw_conn_org_name")
        integrity_err = IntegrityError("INSERT", {}, orig_exc)

        session.commit = AsyncMock(side_effect=integrity_err)
        session.rollback = AsyncMock()

        conn = ConnectionCreate(
            name="my_conn",
            db_type=DBType.postgres,
            host="localhost",
            port=5432,
            database="db",
            username="user",
            connection_string="postgresql://user@localhost/db",
        )

        with pytest.raises(ValueError, match="Connection 'my_conn' already exists"):
            await store.create_connection(conn)

        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_uniqueness_integrity_error_reraises(self) -> None:
        session = AsyncMock()
        store = Store(session, org_id="test-org", user_id="user1")
        store.get_connection = AsyncMock(return_value=None)  # type: ignore[method-assign]
        store.get_connection_string = AsyncMock(return_value=None)  # type: ignore[method-assign]

        orig_exc = Exception("NOT NULL constraint failed: gateway_connections.host")
        integrity_err = IntegrityError("INSERT", {}, orig_exc)

        session.commit = AsyncMock(side_effect=integrity_err)
        session.rollback = AsyncMock()

        conn = ConnectionCreate(
            name="my_conn",
            db_type=DBType.postgres,
            host="localhost",
            port=5432,
            database="db",
            username="user",
            connection_string="postgresql://user@localhost/db",
        )

        with pytest.raises(IntegrityError):
            await store.create_connection(conn)


# ─── create_project IntegrityError handling ──────────────────────────────────


class TestCreateProjectIntegrityError:
    """IntegrityError after pre-check must be converted to ValueError."""

    @pytest.mark.asyncio
    async def test_integrity_error_on_project_raises_value_error(self) -> None:
        session = AsyncMock()
        store = Store(session, org_id="test-org", user_id="user1")
        store.get_project = AsyncMock(return_value=None)  # type: ignore[method-assign]

        fake_connection = MagicMock()
        fake_connection.db_type = "postgres"
        fake_connection.host = "localhost"
        fake_connection.port = 5432
        fake_connection.database = "db"
        fake_connection.username = "user"
        store.get_connection = AsyncMock(return_value=fake_connection)  # type: ignore[method-assign]

        orig_exc = Exception("UNIQUE constraint failed: uq_gw_proj_org_name")
        integrity_err = IntegrityError("INSERT", {}, orig_exc)

        session.commit = AsyncMock(side_effect=integrity_err)
        session.rollback = AsyncMock()

        proj = ProjectCreate(
            name="my_project",
            connection_name="my_conn",
            source="new",
        )

        with pytest.raises(ValueError, match="Project 'my_project' already exists"):
            await store.create_project(proj)

        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_uniqueness_integrity_error_on_project_reraises(self) -> None:
        session = AsyncMock()
        store = Store(session, org_id="test-org", user_id="user1")
        store.get_project = AsyncMock(return_value=None)  # type: ignore[method-assign]

        fake_connection = MagicMock()
        fake_connection.db_type = "postgres"
        store.get_connection = AsyncMock(return_value=fake_connection)  # type: ignore[method-assign]

        orig_exc = Exception("FK constraint failed: some_other_constraint")
        integrity_err = IntegrityError("INSERT", {}, orig_exc)

        session.commit = AsyncMock(side_effect=integrity_err)
        session.rollback = AsyncMock()

        proj = ProjectCreate(
            name="my_project",
            connection_name="my_conn",
            source="new",
        )

        with pytest.raises(IntegrityError):
            await store.create_project(proj)


# ─── clone_connection endpoint returns 409 on race ───────────────────────────


class TestCloneConnectionRace:
    """clone_connection must return 409 when store.create_connection raises ValueError."""

    @pytest.mark.asyncio
    async def test_clone_raises_409_on_value_error(self) -> None:
        """Directly test the endpoint logic: ValueError from store -> HTTPException 409."""
        from gateway.api.connections import clone_connection
        from gateway.models import ConnectionInfo

        existing_conn = MagicMock(spec=ConnectionInfo)
        existing_conn.db_type = "postgres"
        existing_conn.description = None
        existing_conn.host = "localhost"
        existing_conn.port = 5432
        existing_conn.database = "db"
        existing_conn.username = "user"
        existing_conn.account = None
        existing_conn.warehouse = None
        existing_conn.schema_name = None
        existing_conn.role = None
        existing_conn.project = None
        existing_conn.dataset = None
        existing_conn.http_path = None
        existing_conn.catalog = None

        store = AsyncMock()
        store.get_connection = AsyncMock(side_effect=[existing_conn, None])
        store.get_connection_string = AsyncMock(return_value=None)
        store.create_connection = AsyncMock(side_effect=ValueError("Connection 'clone_name' already exists"))

        with pytest.raises(HTTPException) as exc_info:
            await clone_connection("source_conn", store, new_name="clone_name")

        assert exc_info.value.status_code == 409
        assert "clone_name" in exc_info.value.detail
