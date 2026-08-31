"""Fast checks for the packaged gateway Alembic graph."""

from __future__ import annotations

from alembic.script import ScriptDirectory

from gateway.db.migrate import build_alembic_config


def test_external_0015_stamp_is_the_tracked_head() -> None:
    config = build_alembic_config("postgresql://unused:unused@localhost/unused")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "0015"
    revision = scripts.get_revision("0015")
    assert revision is not None
    assert revision.down_revision == "0013"
