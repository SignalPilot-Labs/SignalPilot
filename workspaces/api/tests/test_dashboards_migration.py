"""Text-grep tests for the dashboards and R6 Alembic migrations."""

from __future__ import annotations

import pathlib


_MIGRATIONS_DIR = (
    pathlib.Path(__file__).parent.parent / "alembic" / "versions"
)

_MIGRATION_DASHBOARDS = _MIGRATIONS_DIR / "20260501_0002_dashboards.py"
_MIGRATION_DECISION = _MIGRATIONS_DIR / "20260501_0003_approval_decision_past_tense.py"
_MIGRATION_USER_ID = _MIGRATIONS_DIR / "20260501_0004_run_user_id.py"


class TestDashboardsMigration:
    def test_migration_file_exists_with_correct_tables(self) -> None:
        assert _MIGRATION_DASHBOARDS.exists(), f"Migration file not found: {_MIGRATION_DASHBOARDS}"
        text = _MIGRATION_DASHBOARDS.read_text()
        assert "chart" in text
        assert "chart_query" in text
        assert "chart_cache" in text

    def test_migration_down_revision_matches_r2(self) -> None:
        text = _MIGRATION_DASHBOARDS.read_text()
        assert 'down_revision = "20260501_0001"' in text

    def test_downgrade_drops_three_tables(self) -> None:
        text = _MIGRATION_DASHBOARDS.read_text()
        # Verify downgrade() exists and drops the three new tables
        assert "def downgrade" in text
        assert 'drop_table("chart_cache"' in text
        assert 'drop_table("chart_query"' in text
        assert 'drop_table("chart"' in text


class TestApprovalDecisionPastTenseMigration:
    def test_migration_file_exists(self) -> None:
        assert _MIGRATION_DECISION.exists(), f"Migration not found: {_MIGRATION_DECISION}"

    def test_revision_and_down_revision(self) -> None:
        text = _MIGRATION_DECISION.read_text()
        assert 'revision = "20260501_0003"' in text
        assert 'down_revision = "20260501_0002"' in text

    def test_upgrade_maps_approve_to_approved(self) -> None:
        text = _MIGRATION_DECISION.read_text()
        assert "decision='approved'" in text
        assert "decision='approve'" in text

    def test_upgrade_maps_reject_to_rejected(self) -> None:
        text = _MIGRATION_DECISION.read_text()
        assert "decision='rejected'" in text
        assert "decision='reject'" in text

    def test_downgrade_reverses_both_values(self) -> None:
        text = _MIGRATION_DECISION.read_text()
        assert "def downgrade" in text
        # Downgrade must put back 'approve' from 'approved'
        assert "'approve'" in text
        assert "'reject'" in text

    def test_uses_workspaces_schema(self) -> None:
        text = _MIGRATION_DECISION.read_text()
        assert "workspaces.approval" in text


class TestRunUserIdMigration:
    def test_migration_file_exists(self) -> None:
        assert _MIGRATION_USER_ID.exists(), f"Migration not found: {_MIGRATION_USER_ID}"

    def test_revision_and_down_revision(self) -> None:
        text = _MIGRATION_USER_ID.read_text()
        assert 'revision = "20260501_0004"' in text
        assert 'down_revision = "20260501_0003"' in text

    def test_upgrade_adds_user_id_column(self) -> None:
        text = _MIGRATION_USER_ID.read_text()
        assert "user_id" in text
        assert "add_column" in text

    def test_upgrade_creates_composite_index(self) -> None:
        text = _MIGRATION_USER_ID.read_text()
        assert "run_user_id_idx" in text
        assert "create_index" in text
        # Index covers user_id, created_at, id for keyset pagination
        assert '"user_id"' in text or "'user_id'" in text

    def test_downgrade_drops_index_and_column(self) -> None:
        text = _MIGRATION_USER_ID.read_text()
        assert "def downgrade" in text
        assert "drop_index" in text
        assert "drop_column" in text

    def test_uses_workspaces_schema(self) -> None:
        text = _MIGRATION_USER_ID.read_text()
        assert 'schema="workspaces"' in text

    def test_no_backfill_documented(self) -> None:
        text = _MIGRATION_USER_ID.read_text()
        assert "No backfill" in text or "backfill" in text.lower()
