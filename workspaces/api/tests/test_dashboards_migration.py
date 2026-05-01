"""Text-grep tests for the dashboards Alembic migration."""

from __future__ import annotations

import pathlib


_MIGRATION_PATH = (
    pathlib.Path(__file__).parent.parent
    / "alembic" / "versions" / "20260501_0002_dashboards.py"
)


class TestDashboardsMigration:
    def test_migration_file_exists_with_correct_tables(self) -> None:
        assert _MIGRATION_PATH.exists(), f"Migration file not found: {_MIGRATION_PATH}"
        text = _MIGRATION_PATH.read_text()
        assert "chart" in text
        assert "chart_query" in text
        assert "chart_cache" in text

    def test_migration_down_revision_matches_r2(self) -> None:
        text = _MIGRATION_PATH.read_text()
        assert 'down_revision = "20260501_0001"' in text

    def test_downgrade_drops_three_tables(self) -> None:
        text = _MIGRATION_PATH.read_text()
        # Verify downgrade() exists and drops the three new tables
        assert "def downgrade" in text
        assert 'drop_table("chart_cache"' in text
        assert 'drop_table("chart_query"' in text
        assert 'drop_table("chart"' in text
