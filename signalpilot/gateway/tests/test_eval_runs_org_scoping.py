"""Org-scoping and staff-gating tests for /api/evals/* run routes.

Eval state is file-based, so scoping is proven on disk (one org cannot read or
overwrite another's config, runs, or transcripts) and through the routes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.api.deps import get_store
from gateway.api.eval_runs import router as eval_runs_router
from gateway.config import get_governance_settings
from gateway.evals import runner

STAFF_USER = "platform-staff"
RUN_A = "run-20260101-010101-aaaaaa"
RUN_B = "run-20260101-020202-bbbbbb"


class FakeStore:
    """Stands in for the org-scoped Store — the routes only read these two."""

    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    yield


@pytest.fixture(autouse=True)
def _staff_ids(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_ADMIN_USER_IDS", STAFF_USER)
    get_governance_settings.cache_clear()
    yield
    get_governance_settings.cache_clear()


def _client(org_id: str, user_id: str = STAFF_USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)
    return TestClient(app)


def _seed_run(org_id: str, run_id: str, *, transcript: str) -> None:
    run_dir = runner.eval_root(org_id) / run_id
    (run_dir / "questions").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps({"id": run_id, "status": "completed", "created_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    (run_dir / "questions" / "q1.log").write_text(transcript, encoding="utf-8")
    (run_dir / "setup-clean.log").write_text(f"setup for {org_id}", encoding="utf-8")


# ─── Storage-layer scoping ───────────────────────────────────────────────────


class TestRunnerOrgScoping:
    def test_config_is_per_org(self) -> None:
        runner.save_eval_config("org-a", {"repo_url": "https://example.com/a.git"})
        runner.save_eval_config("org-b", {"repo_url": "https://example.com/b.git"})

        assert runner.load_eval_config("org-a")["repo_url"] == "https://example.com/a.git"
        assert runner.load_eval_config("org-b")["repo_url"] == "https://example.com/b.git"
        assert runner.config_path("org-a") != runner.config_path("org-b")

    def test_org_without_config_sees_nothing(self) -> None:
        runner.save_eval_config("org-a", {"repo_url": "https://example.com/a.git"})
        assert runner.load_eval_config("org-b") == {}

    def test_run_state_is_per_org(self) -> None:
        _seed_run("org-a", RUN_A, transcript="secret-a")
        assert runner.read_run("org-a", RUN_A) is not None
        assert runner.read_run("org-b", RUN_A) is None
        assert runner.list_runs("org-b") == []
        assert runner.read_transcript("org-b", RUN_A, "q1") is None
        assert runner.read_setup_log("org-b", RUN_A, "clean") is None

    def test_org_ids_differing_only_in_punctuation_do_not_collide(self) -> None:
        runner.save_eval_config("org/a", {"repo_url": "slash"})
        runner.save_eval_config("org:a", {"repo_url": "colon"})
        assert runner.load_eval_config("org/a")["repo_url"] == "slash"
        assert runner.load_eval_config("org:a")["repo_url"] == "colon"

    def test_blank_org_id_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            runner.eval_root("")


# ─── Route-level scoping ─────────────────────────────────────────────────────


class TestEvalRouteOrgScoping:
    def test_config_written_by_one_org_is_invisible_to_another(self) -> None:
        with _client("org-a") as client:
            assert client.put("/api/evals/config", json={"repo_url": "https://a.example/a.git"}).status_code == 200
        with _client("org-b") as client:
            body = client.get("/api/evals/config").json()
        assert body["repo_url"] == ""

    def test_one_org_cannot_overwrite_anothers_config(self) -> None:
        with _client("org-a") as client:
            client.put("/api/evals/config", json={"repo_url": "https://a.example/a.git"})
        with _client("org-b") as client:
            client.put("/api/evals/config", json={"repo_url": "https://b.example/b.git"})
        with _client("org-a") as client:
            assert client.get("/api/evals/config").json()["repo_url"] == "https://a.example/a.git"

    def test_run_listing_is_scoped(self) -> None:
        _seed_run("org-a", RUN_A, transcript="secret-a")
        _seed_run("org-b", RUN_B, transcript="secret-b")

        with _client("org-a") as client:
            ids = [r["id"] for r in client.get("/api/evals/runs").json()["runs"]]
        assert ids == [RUN_A]

    def test_foreign_run_detail_is_404(self) -> None:
        _seed_run("org-a", RUN_A, transcript="secret-a")
        with _client("org-b") as client:
            assert client.get(f"/api/evals/runs/{RUN_A}").status_code == 404

    def test_foreign_transcript_is_404(self) -> None:
        _seed_run("org-a", RUN_A, transcript="secret-a")
        with _client("org-b") as client:
            assert client.get(f"/api/evals/runs/{RUN_A}/questions/q1/transcript").status_code == 404
        with _client("org-a") as client:
            resp = client.get(f"/api/evals/runs/{RUN_A}/questions/q1/transcript")
        assert resp.status_code == 200
        assert resp.text == "secret-a"

    def test_foreign_setup_log_is_404(self) -> None:
        _seed_run("org-a", RUN_A, transcript="secret-a")
        with _client("org-b") as client:
            assert client.get(f"/api/evals/runs/{RUN_A}/setup/clean/log").status_code == 404


# ─── Staff gating ────────────────────────────────────────────────────────────

_ROUTES = [
    ("get", "/api/evals/config"),
    ("get", "/api/evals/questions"),
    ("get", "/api/evals/runs"),
    ("get", f"/api/evals/runs/{RUN_A}"),
    ("get", f"/api/evals/runs/{RUN_A}/setup/clean/log"),
    ("get", f"/api/evals/runs/{RUN_A}/questions/q1/transcript"),
]


