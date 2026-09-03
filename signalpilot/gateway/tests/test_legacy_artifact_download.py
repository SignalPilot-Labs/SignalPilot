"""Legacy published artifacts stay downloadable for the saved-reports library."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gateway.api.chat_routes import legacy_artifacts as routes
from tests.test_chat_reports import _artifact, _seed_project, db_session


def _store(db, user_id: str = "user-a"):
    return SimpleNamespace(session=db, user_id=user_id, _require_org_id=lambda: "org-a")


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "1")


@pytest.mark.asyncio
async def test_inline_table_downloads_as_csv(db_session, enabled):
    await _seed_project(db_session)
    artifact = await _artifact(db_session, value=42)
    response = await routes.download_legacy_artifact(artifact.id, _store(db_session), "csv")
    assert response.media_type == "text/csv; charset=utf-8"
    assert b"42" in response.body
    assert 'filename="revenue.csv"' in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_format_must_match_kind(db_session, enabled):
    await _seed_project(db_session)
    artifact = await _artifact(db_session)
    with pytest.raises(HTTPException) as excinfo:
        await routes.download_legacy_artifact(artifact.id, _store(db_session), "png")
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_other_user_gets_404(db_session, enabled):
    await _seed_project(db_session)
    artifact = await _artifact(db_session)
    with pytest.raises(HTTPException) as excinfo:
        await routes.download_legacy_artifact(artifact.id, _store(db_session, "user-b"), "csv")
    assert excinfo.value.status_code == 404
