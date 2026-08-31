"""Fast checks for the packaged gateway Alembic graph."""

from __future__ import annotations

from alembic.script import ScriptDirectory

from gateway.db.migrate import build_alembic_config


def test_external_stamp_compatibility_chain_is_the_tracked_head() -> None:
    config = build_alembic_config("postgresql://unused:unused@localhost/unused")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "0016"

    revision_0016 = scripts.get_revision("0016")
    assert revision_0016 is not None
    assert revision_0016.down_revision == "0015"

    revision_0015 = scripts.get_revision("0015")
    assert revision_0015 is not None
    assert revision_0015.down_revision == "0013"
