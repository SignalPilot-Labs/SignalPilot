"""Verify progress derivation and runner markers in the evaluation sandbox panel.

Continues ``test_eval_sandbox_panel.py``: a failing task is an error, not a
hang, and progress is derived from the runner's markers during a run.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gateway.config.evals import get_eval_run_settings
from gateway.evals import runner
from gateway.store import evals as evals_store

from ._eval_sandbox_panel_support import POD_A, RUN_A, _client, _eval_secrets, db, sqlite_factory

# Verify run progress.


class TestDeriveProgress:
    def test_running_run_reports_active_tasks(self) -> None:
        run = {
            "id": RUN_A,
            "status": "running",
            "created_at": datetime.now(UTC).isoformat(),
            "progress": {
                "phase": "running",
                "done": 1,
                "total": 3,
                "active": [{"task_id": "q2", "title": "second", "phase": "agent"}],
                "started_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
        body = runner.derive_progress(run)
        assert body["phase"] == "running"
        assert body["done"] == 1
        assert body["total"] == 3
        assert body["active"][0]["task_id"] == "q2"
        assert body["elapsed_s"] is not None and body["elapsed_s"] >= 0

    def test_finished_run_without_markers_still_answers(self) -> None:
        body = runner.derive_progress({"id": RUN_A, "status": "completed", "progress": {}})
        assert body["phase"] == "finished"
        assert body["done"] == 0
        assert body["elapsed_s"] is None

    def test_bad_run_id_is_rejected(self) -> None:
        with _client("org-a") as client:
            assert client.get("/api/evals/runs/not-a-run/progress").status_code == 400


class TestRunnerMarkers:
    async def test_backend_start_callback_carries_the_pod_name(self) -> None:
        from gateway.evals.backends import ContainerRun, _notify_start

        seen: list[dict] = []
        spec = ContainerRun(
            image="img",
            command=["true"],
            env={},
            secret_env={},
            labels={},
            memory_bytes=1,
            nano_cpus=1,
            timeout_seconds=1,
            on_start=seen.append,
        )
        _notify_start(spec, {"backend": "vercel", "name": POD_A, "namespace": ""})
        assert seen[0]["name"] == POD_A
        assert seen[0]["started_at"]

    def test_a_failing_callback_does_not_break_the_run(self) -> None:
        from gateway.evals.backends import ContainerRun, _notify_start

        def boom(_info: dict) -> None:
            raise RuntimeError("disk full")

        spec = ContainerRun(
            image="img",
            command=["true"],
            env={},
            secret_env={},
            labels={},
            memory_bytes=1,
            nano_cpus=1,
            timeout_seconds=1,
            on_start=boom,
        )
        _notify_start(spec, {"backend": "docker", "name": "abc"})  # must not raise


# Verify a run with a backend test double.


class _FakeObjectStore:
    """In-memory evidence store with the real key layout."""

    from gateway.evals.object_store import EvalObjectStore as _Real

    transcript_key = _Real.transcript_key
    setup_log_key = _Real.setup_log_key
    artifact_key = _Real.artifact_key
    artifacts_prefix = _Real.artifacts_prefix
    run_prefix = _Real.run_prefix
    project_tarball_key = _Real.project_tarball_key

    def __init__(self) -> None:
        self.texts: dict[str, str] = {}
        self.blobs: dict[str, bytes] = {}

    async def put_text(self, key: str, text: str) -> int:
        self.texts[key] = text
        return len(text)

    async def put_bytes(self, key: str, data: bytes, content_type: str = "") -> int:
        self.blobs[key] = data
        return len(data)

    async def get_text(self, key: str) -> str | None:
        return self.texts.get(key)

    async def delete_prefix(self, prefix: str) -> int:
        return 0


class TestProgressDuringARun:
    """Exercise execute_run with a backend test double and SQLite.

    Tasks run concurrently. The runner records sandbox markers, grading results,
    the summary, and the permanent accuracy record.
    """

    @pytest.fixture
    def eval_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        repo = tmp_path / "projects" / "set-1"
        repo.mkdir(parents=True)
        (repo / "eval.json").write_text(
            json.dumps(
                {
                    "name": "t",
                    "tasks": [
                        {"id": "q1", "prompt_text": "what is 6*7?", "gt": "42"},
                        {"id": "q2", "prompt_text": "6*7 again?", "gt": "42"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("SP_EVAL_PROJECTS_DIR", str(tmp_path / "projects"))
        monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", "sp-eval-runner:latest")
        monkeypatch.setenv("SP_EVAL_S3_BUCKET", "eval-evidence")
        # Serialize tasks: the sqlite StaticPool shares one connection, which
        # concurrent sessions would fight over. One-at-a-time is still the
        # full lifecycle per task.
        monkeypatch.setenv("SP_EVAL_MAX_PARALLEL_TASKS", "1")
        get_eval_run_settings.cache_clear()
        yield repo
        get_eval_run_settings.cache_clear()

    @pytest.fixture
    def fake_obj(self, monkeypatch: pytest.MonkeyPatch) -> _FakeObjectStore:
        obj = _FakeObjectStore()
        from gateway.evals import retention

        monkeypatch.setattr(runner, "get_object_store", lambda: obj)
        monkeypatch.setattr(retention, "get_object_store", lambda: obj)
        return obj

    async def _start_run(self, db, org: str, repo: Path) -> str:
        run_id = runner.new_run_id()
        async with db() as session:
            await evals_store.save_config(
                session,
                org_id=org,
                cfg={"repo_url": str(repo), "connection": "eval-warehouse"},
            )
            await evals_store.create_run(
                session,
                org_id=org,
                run_id=run_id,
                created_at=datetime.now(UTC).isoformat(),
                trigger="manual",
                doc_ids=[],
                doc_titles=[],
                task_filter=None,
                repo_url=str(repo),
                model="sonnet",
            )
        return run_id

    async def test_a_full_run_lands_in_the_db(self, db, eval_repo, fake_obj, monkeypatch) -> None:
        observed: list[dict] = []

        class _Backend:
            def __init__(self) -> None:
                self.n = 0
                self._lock = asyncio.Lock()

            async def run(self, spec):
                async with self._lock:
                    self.n += 1
                    name = f"cafebabe{self.n:04d}"
                started = spec.on_start({"backend": "docker", "name": name})
                if inspect.isawaitable(started):
                    await started  # the marker write must land mid-task
                async with db() as session:
                    run = await evals_store.get_run(session, org_id="org-a", run_id=run_id)
                observed.append(runner.derive_progress(run))
                return 0, 'noise\n{"type":"result","result":"the answer is 42"}'

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(runner, "get_execution_backend", lambda *a, **k: _Backend())
        run_id = await self._start_run(db, "org-a", eval_repo)

        await runner.execute_run("org-a", run_id)

        async with db() as session:
            run = await evals_store.get_run(session, org_id="org-a", run_id=run_id)
        assert run["status"] == "completed"
        assert run["summary"]["total"] == 2
        assert run["summary"]["correct"] == 2
        assert run["eval_set_name"] == "t"
        assert run["eval_set_ref"].startswith("local-")

        # Task rows are graded and carry the extracted answer.
        assert [t["verdict"] for t in run["tasks"]] == ["CORRECT", "CORRECT"]
        assert all(t["status"] == "done" for t in run["tasks"])
        assert all("42" in t["answer"] for t in run["tasks"])

        # Transcripts landed in the evidence store under the run's keys.
        for task_id in ("q1", "q2"):
            key = _FakeObjectStore.transcript_key("org-a", run_id, task_id)
            assert "result" in fake_obj.texts[key]

        # The permanent accuracy record got its row.
        async with db() as session:
            history = await evals_store.list_accuracy(session, org_id="org-a")
        assert len(history) == 1
        assert history[0]["run_id"] == run_id
        assert history[0]["accuracy_pct"] == 100.0
        assert history[0]["tasks_total"] == 2

        # Mid-run the board reported live progress with the right shape.
        assert observed, "the backend never saw a mid-run progress snapshot"
        for snap in observed:
            assert snap["status"] == "running"
            assert snap["total"] == 2
            assert {"phase", "done", "total", "active"} <= set(snap)
        # At least one snapshot names an active task with its sandbox marker.
        active = [a for snap in observed for a in snap["active"]]
        assert any(a.get("sandbox", {}).get("name", "").startswith("cafebabe") for a in active)

        # And the final progress derivation says finished.
        final = runner.derive_progress(run)
        assert final["phase"] == "finished"
        assert final["done"] == 2
        assert final["active"] == []

        # Verify that execute_run revokes every task credential before return.
        from sqlalchemy import select

        from gateway.db.models import GatewayApiKey

        async with db() as session:
            leaked = (
                (await session.execute(select(GatewayApiKey).where(GatewayApiKey.eval_run_id == run_id)))
                .scalars()
                .all()
            )
        assert leaked == [], f"eval-bound API keys leaked: {[k.id for k in leaked]}"

    async def test_a_failing_task_is_an_error_not_a_hang(self, db, eval_repo, fake_obj, monkeypatch) -> None:
        class _Backend:
            async def run(self, spec):
                return 1, ""  # container died with no output

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(runner, "get_execution_backend", lambda *a, **k: _Backend())
        run_id = await self._start_run(db, "org-a", eval_repo)
        await runner.execute_run("org-a", run_id)

        async with db() as session:
            run = await evals_store.get_run(session, org_id="org-a", run_id=run_id)
        assert run["status"] == "failed"  # every task errored
        assert run["summary"]["error"] == 2
        assert all(t["verdict"] == "ERROR" for t in run["tasks"])

    async def test_markers_from_one_org_are_invisible_to_another(self, db, eval_repo, fake_obj, monkeypatch) -> None:
        class _Backend:
            async def run(self, spec):
                started = spec.on_start({"backend": "docker", "name": "cafebabe0001"})
                if inspect.isawaitable(started):
                    await started
                return 0, '{"type":"result","result":"42"}'

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(runner, "get_execution_backend", lambda *a, **k: _Backend())
        run_id = await self._start_run(db, "org-a", eval_repo)
        await runner.execute_run("org-a", run_id)

        assert await runner.run_exists("org-a", run_id) is True
        assert await runner.run_exists("org-b", run_id) is False
        assert await runner.sandbox_index("org-b") == {}
