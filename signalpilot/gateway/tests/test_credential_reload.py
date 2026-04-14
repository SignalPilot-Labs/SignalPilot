"""Tests for reload-on-miss behavior in store.get_connection_string and get_credential_extras."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import gateway.store as store
from gateway.models import ConnectionCreate, DBType


def _make_sqlite_conn(name: str) -> ConnectionCreate:
    return ConnectionCreate(name=name, db_type=DBType.sqlite, database=":memory:")


@pytest.fixture()
def isolated_store(tmp_path: Path):
    """Redirect store globals to a fresh tmp directory and reset vault state after each test."""
    creds_file = tmp_path / "credentials.enc"
    conns_file = tmp_path / "connections.json"

    orig_data_dir = store.DATA_DIR
    orig_creds_file = store.CREDENTIALS_FILE
    orig_conns_file = store.CONNECTIONS_FILE
    orig_vault = store._credential_vault.copy()
    orig_extras = store._credential_extras.copy()

    store.DATA_DIR = tmp_path
    store.CREDENTIALS_FILE = creds_file
    store.CONNECTIONS_FILE = conns_file
    store._credential_vault = {}
    store._credential_extras = {}

    # Patch the encryption key env so tests are deterministic
    with patch.dict(os.environ, {"SP_ENCRYPTION_KEY": "test-key-for-unit-tests-only"}):
        yield tmp_path

    store.DATA_DIR = orig_data_dir
    store.CREDENTIALS_FILE = orig_creds_file
    store.CONNECTIONS_FILE = orig_conns_file
    store._credential_vault = orig_vault
    store._credential_extras = orig_extras


class TestGetConnectionStringReloadsOnMiss:
    def test_returns_credential_after_reload(self, isolated_store: Path) -> None:
        """If vault is empty but credentials.enc on disk has the entry, reload happens."""
        conn = _make_sqlite_conn("test_conn")
        # Write credential to disk via create_connection (populates vault + saves)
        store.create_connection(conn)

        # Simulate stale in-memory state (another process wrote the file)
        store._credential_vault.clear()

        result = store.get_connection_string("test_conn")
        assert result is not None
        assert ":memory:" in result

    def test_returns_none_for_nonexistent_connection(self, isolated_store: Path) -> None:
        """Missing key returns None without looping — reload fires once and gives up."""
        result = store.get_connection_string("does_not_exist")
        assert result is None

    def test_reload_called_exactly_once_on_miss(self, isolated_store: Path) -> None:
        """Verifies no infinite loop: _load_credentials called once on cache miss."""
        call_count: list[int] = [0]
        original_load = store._load_credentials

        def counting_load() -> None:
            call_count[0] += 1
            original_load()

        with patch.object(store, "_load_credentials", side_effect=counting_load):
            store.get_connection_string("no_such_connection")

        assert call_count[0] == 1

    def test_hit_path_does_not_reload(self, isolated_store: Path) -> None:
        """When key is present in vault, _load_credentials must NOT be called."""
        conn = _make_sqlite_conn("cached_conn")
        store.create_connection(conn)
        # vault is populated — should return without reloading
        call_count: list[int] = [0]

        def fail_if_called() -> None:
            call_count[0] += 1

        with patch.object(store, "_load_credentials", side_effect=fail_if_called):
            result = store.get_connection_string("cached_conn")

        assert result is not None
        assert call_count[0] == 0


class TestGetCredentialExtrasReloadsOnMiss:
    def test_returns_extras_after_reload(self, isolated_store: Path) -> None:
        """If extras dict is empty but disk has data, reload fetches it."""
        conn = ConnectionCreate(
            name="bq_conn",
            db_type=DBType.bigquery,
            project="my-project",
            credentials_json='{"type": "service_account"}',
        )
        store.create_connection(conn)

        # Stale in-process state
        store._credential_extras.clear()

        extras = store.get_credential_extras("bq_conn")
        assert "credentials_json" in extras

    def test_returns_empty_dict_for_missing_connection(self, isolated_store: Path) -> None:
        """Missing key returns empty dict — no infinite loop."""
        result = store.get_credential_extras("ghost_conn")
        assert result == {}

    def test_reload_called_exactly_once_on_miss(self, isolated_store: Path) -> None:
        """_load_credentials called exactly once when key is absent from extras."""
        call_count: list[int] = [0]
        original_load = store._load_credentials

        def counting_load() -> None:
            call_count[0] += 1
            original_load()

        with patch.object(store, "_load_credentials", side_effect=counting_load):
            store.get_credential_extras("missing_extras_key")

        assert call_count[0] == 1

    def test_present_empty_dict_does_not_reload(self, isolated_store: Path) -> None:
        """Key present with empty dict is a valid state — must NOT trigger reload."""
        store._credential_extras["explicit_empty"] = {}

        call_count: list[int] = [0]

        def fail_if_called() -> None:
            call_count[0] += 1

        with patch.object(store, "_load_credentials", side_effect=fail_if_called):
            result = store.get_credential_extras("explicit_empty")

        assert result == {}
        assert call_count[0] == 0


class TestReloadCredentials:
    def test_reload_credentials_refreshes_vault(self, isolated_store: Path) -> None:
        """Public reload_credentials() re-reads disk and populates vault."""
        conn = _make_sqlite_conn("reload_test")
        store.create_connection(conn)
        store._credential_vault.clear()
        store._credential_extras.clear()

        store.reload_credentials()

        assert "reload_test" in store._credential_vault

    def test_reload_credentials_no_file_is_noop(self, isolated_store: Path) -> None:
        """reload_credentials() with no credentials file on disk doesn't crash."""
        assert not store.CREDENTIALS_FILE.exists()
        store.reload_credentials()  # must not raise
