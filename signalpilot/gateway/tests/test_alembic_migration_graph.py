"""Fast checks for the packaged gateway Alembic graph."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from alembic.script import ScriptDirectory

from gateway.db.migrate import build_alembic_config


def _revision_id(path: Path) -> str | None:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return None


def test_migration_revision_ids_are_unique() -> None:
    versions_dir = Path(__file__).parents[1] / "gateway/db/migrations/versions"
    revisions = [revision for path in versions_dir.glob("*.py") if (revision := _revision_id(path)) is not None]
    duplicates = sorted(revision for revision, count in Counter(revisions).items() if count > 1)

    assert duplicates == [], f"Duplicate Alembic revision IDs: {', '.join(duplicates)}"


def test_real_migration_chain_is_the_tracked_head() -> None:
    config = build_alembic_config("postgresql://unused:unused@localhost/unused")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "0016"

    revision_0016 = scripts.get_revision("0016")
    assert revision_0016 is not None
    assert revision_0016.down_revision == "0015"

    revision_0015 = scripts.get_revision("0015")
    assert revision_0015 is not None
    assert revision_0015.down_revision == "0014"

    revision_0014 = scripts.get_revision("0014")
    assert revision_0014 is not None
    assert revision_0014.down_revision == "0013"
