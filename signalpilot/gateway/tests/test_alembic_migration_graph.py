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

    assert scripts.get_current_head() == "0025"

    # Top-level dashboard authoring follows the connector and chat settings
    # migrations introduced on main.
    revision_0025 = scripts.get_revision("0025")
    assert revision_0025 is not None
    assert revision_0025.down_revision == "0024"

    # 0024 stores the per-chat thinking effort on top of the connector chain.
    revision_0024 = scripts.get_revision("0024")
    assert revision_0024 is not None
    assert revision_0024.down_revision == "0023"

    # The connector migrations (0022, 0023) sit behind the dashboard
    # authoring migrations (0020, 0021) in one linear chain.
    revision_0023 = scripts.get_revision("0023")
    assert revision_0023 is not None
    assert revision_0023.down_revision == "0022"

    revision_0022 = scripts.get_revision("0022")
    assert revision_0022 is not None
    assert revision_0022.down_revision == "0021"

    revision_0021 = scripts.get_revision("0021")
    assert revision_0021 is not None
    assert revision_0021.down_revision == "0020"

    revision_0020 = scripts.get_revision("0020")
    assert revision_0020 is not None
    assert revision_0020.down_revision == "0019"
