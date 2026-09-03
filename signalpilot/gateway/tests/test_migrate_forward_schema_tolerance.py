"""Boot must survive a database stamped by newer code (unknown revision)."""

import pytest
from alembic.util.exc import CommandError

from gateway.db import migrate


def test_unknown_newer_revision_warns_instead_of_raising(monkeypatch, caplog):
    def _raise_unknown(url: str) -> None:
        raise CommandError("Can't locate revision identified by '9999'")

    monkeypatch.setattr(migrate, "upgrade_to_head", _raise_unknown)
    with caplog.at_level("WARNING"):
        migrate.upgrade_to_head_tolerating_newer("postgresql://x/y")
    assert "not known to this build" in caplog.text


def test_other_alembic_errors_still_raise(monkeypatch):
    def _raise_other(url: str) -> None:
        raise CommandError("Target database is not up to date.")

    monkeypatch.setattr(migrate, "upgrade_to_head", _raise_other)
    with pytest.raises(CommandError):
        migrate.upgrade_to_head_tolerating_newer("postgresql://x/y")


def test_success_path_passes_through(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(migrate, "upgrade_to_head", calls.append)
    migrate.upgrade_to_head_tolerating_newer("postgresql://x/y")
    assert calls == ["postgresql://x/y"]
