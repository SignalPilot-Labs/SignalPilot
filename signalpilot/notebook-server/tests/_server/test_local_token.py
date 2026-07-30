from __future__ import annotations

from pathlib import Path

import pytest

from signalpilot._server.local_token import ensure_token_file


def test_generates_and_persists_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SP_NOTEBOOK_TOKEN", raising=False)
    path = tmp_path / "nested" / "token"

    token = ensure_token_file(path)

    assert len(token) >= 40
    assert path.read_text(encoding="utf-8") == token


def test_reuses_persisted_token_across_boots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SP_NOTEBOOK_TOKEN", raising=False)
    path = tmp_path / "token"

    first = ensure_token_file(path)
    assert ensure_token_file(path) == first


def test_env_override_replaces_persisted_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "token"
    monkeypatch.delenv("SP_NOTEBOOK_TOKEN", raising=False)
    generated = ensure_token_file(path)

    monkeypatch.setenv("SP_NOTEBOOK_TOKEN", "operator-supplied")
    assert ensure_token_file(path) == "operator-supplied"
    assert path.read_text(encoding="utf-8") == "operator-supplied"
    assert generated != "operator-supplied"


def test_blank_env_override_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "token"
    monkeypatch.delenv("SP_NOTEBOOK_TOKEN", raising=False)
    generated = ensure_token_file(path)

    monkeypatch.setenv("SP_NOTEBOOK_TOKEN", "   ")
    assert ensure_token_file(path) == generated


def test_never_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty persisted file must not produce a tokenless boot."""
    monkeypatch.delenv("SP_NOTEBOOK_TOKEN", raising=False)
    path = tmp_path / "token"
    path.write_text("   \n", encoding="utf-8")

    token = ensure_token_file(path)
    assert len(token) >= 40
