"""Migration smoke test — cheap insurance only.

This test is explicitly labeled as a text-grep, not a live upgrade test.
It verifies that the migration source contains the required DDL strings.
Live upgrade against Postgres is deferred to R8 (testcontainers).
"""

from __future__ import annotations

import pathlib


_MIGRATION_PATH = (
    pathlib.Path(__file__).parent.parent
    / "alembic"
    / "versions"
    / "20260501_0001_workspaces_initial.py"
)


class TestMigrationSmoke:
    def test_migration_file_exists(self) -> None:
        assert _MIGRATION_PATH.exists(), f"Migration file not found: {_MIGRATION_PATH}"

    def test_migration_contains_create_schema(self) -> None:
        source = _MIGRATION_PATH.read_text()
        assert "CREATE SCHEMA IF NOT EXISTS workspaces" in source

    def test_migration_contains_workspaces_run_table(self) -> None:
        source = _MIGRATION_PATH.read_text()
        assert "workspaces.run" in source or '"run"' in source

    def test_migration_references_run_event(self) -> None:
        source = _MIGRATION_PATH.read_text()
        assert "run_event" in source

    def test_migration_references_approval(self) -> None:
        source = _MIGRATION_PATH.read_text()
        assert "approval" in source

    def test_migration_downgrade_drops_schema(self) -> None:
        source = _MIGRATION_PATH.read_text()
        assert "DROP SCHEMA workspaces" in source
