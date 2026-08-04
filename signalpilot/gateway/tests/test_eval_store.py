"""Verify evaluation state storage in gateway/store/evals.py.

The tests use in-memory SQLite. They verify configuration, runs, tasks, accuracy
records, and retention data.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayEvalAccuracyHistory, GatewayEvalRun
from gateway.store import evals as evals_store

ORG = "org-a"
OTHER = "org-b"


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory) -> AsyncSession:
    async with factory() as s:
        yield s


def _run_id(n: int) -> str:
    return f"run-20260101-{n:06d}-{n:06x}"


async def _mk_run(session, n: int, *, org: str = ORG, status: str = "completed", **kw):
    run = await evals_store.create_run(
        session,
        org_id=org,
        run_id=_run_id(n),
        created_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}+00:00",
        trigger=kw.pop("trigger", "manual"),
        doc_ids=kw.pop("doc_ids", []),
        doc_titles=kw.pop("doc_titles", []),
        task_filter=kw.pop("task_filter", None),
        repo_url=kw.pop("repo_url", "https://example.com/set.git"),
        model=kw.pop("model", "sonnet"),
    )
    if status != "preparing" or kw:
        await evals_store.update_run(
            session, org_id=org, run_id=run["id"], status=status, **kw
        )
    return run["id"]


class TestConfig:
    async def test_defaults_when_no_row(self, session) -> None:
        cfg = await evals_store.get_config(session, org_id=ORG)
        assert cfg == {
            "repo_url": "",
            "model": "sonnet",
            "max_tasks": 0,
            "prompt_preamble": "",
            "connection": "",
            "autorun_on_knowledge_add": False,
            "notify_emails": [],
        }

    async def test_roundtrip_including_notify_emails(self, session) -> None:
        saved = await evals_store.save_config(
            session,
            org_id=ORG,
            cfg={
                "repo_url": "https://example.com/set.git",
                "max_tasks": 12,
                "notify_emails": ["a@example.com", "b@example.com"],
            },
        )
        assert saved["notify_emails"] == ["a@example.com", "b@example.com"]
        cfg = await evals_store.get_config(session, org_id=ORG)
        assert cfg["repo_url"] == "https://example.com/set.git"
        assert cfg["max_tasks"] == 12
        assert cfg["notify_emails"] == ["a@example.com", "b@example.com"]
        # Untouched fields keep their defaults.
        assert cfg["model"] == "sonnet"

    async def test_partial_update_keeps_other_fields(self, session) -> None:
        await evals_store.save_config(
            session, org_id=ORG, cfg={"repo_url": "u", "notify_emails": ["a@example.com"]}
        )
        await evals_store.save_config(session, org_id=ORG, cfg={"model": "opus"})
        cfg = await evals_store.get_config(session, org_id=ORG)
        assert cfg["model"] == "opus"
        assert cfg["repo_url"] == "u"
        assert cfg["notify_emails"] == ["a@example.com"]

    async def test_config_is_per_org(self, session) -> None:
        await evals_store.save_config(session, org_id=ORG, cfg={"repo_url": "a"})
        assert (await evals_store.get_config(session, org_id=OTHER))["repo_url"] == ""


class TestRunsAndTasks:
    async def test_create_update_get_roundtrip(self, session) -> None:
        run_id = await _mk_run(session, 1, status="running", summary={"total": 2})
        run = await evals_store.get_run(session, org_id=ORG, run_id=run_id)
        assert run is not None
        assert run["status"] == "running"
        assert run["summary"] == {"total": 2}
        assert run["repo_url"] == "https://example.com/set.git"
        assert run["tasks"] == []
        assert await evals_store.run_exists(session, org_id=ORG, run_id=run_id) is True

    async def test_tasks_come_back_in_manifest_order(self, session) -> None:
        run_id = await _mk_run(session, 1)
        await evals_store.seed_tasks(
            session,
            org_id=ORG,
            run_id=run_id,
            tasks=[
                {"task_id": "zulu", "title": "Z"},
                {"task_id": "alpha", "title": "A"},
                {"task_id": "mike", "title": "M"},
            ],
        )
        tasks = await evals_store.get_tasks(session, org_id=ORG, run_id=run_id)
        assert [t["id"] for t in tasks] == ["zulu", "alpha", "mike"]
        assert [t["position"] for t in tasks] == [0, 1, 2]
        run = await evals_store.get_run(session, org_id=ORG, run_id=run_id)
        assert [t["id"] for t in run["tasks"]] == ["zulu", "alpha", "mike"]

    async def test_update_task(self, session) -> None:
        run_id = await _mk_run(session, 1)
        await evals_store.seed_tasks(
            session, org_id=ORG, run_id=run_id, tasks=[{"task_id": "q1"}]
        )
        await evals_store.update_task(
            session,
            org_id=ORG,
            run_id=run_id,
            task_id="q1",
            status="done",
            verdict="CORRECT",
            answer="42",
            duration_s=1.5,
        )
        (task,) = await evals_store.get_tasks(session, org_id=ORG, run_id=run_id)
        assert task["status"] == "done"
        assert task["verdict"] == "CORRECT"
        assert task["answer"] == "42"
        assert task["duration_s"] == 1.5

    async def test_list_runs_newest_first(self, session) -> None:
        for n in (1, 3, 2):
            await _mk_run(session, n)
        runs = await evals_store.list_runs(session, org_id=ORG)
        assert [r["id"] for r in runs] == [_run_id(3), _run_id(2), _run_id(1)]

    async def test_live_runs(self, session) -> None:
        """Verify that a live run requires an active status and a current lease."""
        await _mk_run(session, 1, status="completed")
        await _mk_run(session, 2, status="running")  # no lease ever taken
        await _mk_run(session, 3, status="preparing")  # no lease ever taken
        await _mk_run(session, 4, status="running")
        await _mk_run(session, 5, status="preparing")
        await _mk_run(session, 6, status="completed")
        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(4), ttl_s=60.0)
        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(5), ttl_s=60.0)
        # A fresh lease on a finished run still does not make it live.
        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(6), ttl_s=60.0)
        live = await evals_store.list_live_runs(session, org_id=ORG)
        assert {r["id"] for r in live} == {_run_id(4), _run_id(5)}

    async def test_an_expired_lease_is_not_live(self, session) -> None:
        await _mk_run(session, 1, status="running")
        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(1), ttl_s=-60.0)
        assert await evals_store.list_live_runs(session, org_id=ORG) == []

    async def test_stale_runs_are_live_status_without_a_valid_lease(self, session) -> None:
        """The crash-recovery boundary: everything still marked live whose
        lease is missing or expired, and nothing else."""
        await _mk_run(session, 1, status="completed")  # A completed run is not stale.
        await _mk_run(session, 2, status="running", api_key_id="key-2")  # lease never taken
        await _mk_run(session, 3, status="preparing")
        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(3), ttl_s=-1.0)
        await _mk_run(session, 4, status="running")
        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(4), ttl_s=300.0)
        await _mk_run(session, 5, org=OTHER, status="running")

        stale = await evals_store.list_stale_runs(session)
        # Cross-org on purpose: recovery reaps every crashed gateway's leavings.
        assert {r["id"] for r in stale} == {_run_id(2), _run_id(3), _run_id(5)}
        by_id = {r["id"]: r for r in stale}
        # Recovery needs the run-level credential id so it can revoke it.
        assert by_id[_run_id(2)]["api_key_id"] == "key-2"
        assert by_id[_run_id(5)]["api_key_id"] is None

    async def test_renew_lease_moves_a_run_from_stale_to_live(self, session) -> None:
        await _mk_run(session, 1, status="running")
        assert [r["id"] for r in await evals_store.list_stale_runs(session)] == [_run_id(1)]
        assert await evals_store.list_live_runs(session, org_id=ORG) == []

        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(1), ttl_s=120.0)
        assert [
            r["id"] for r in await evals_store.list_live_runs(session, org_id=ORG)
        ] == [_run_id(1)]
        assert await evals_store.list_stale_runs(session) == []

        # Renewal is org-scoped: the wrong org cannot kill (or extend) a lease.
        await evals_store.renew_lease(session, org_id=OTHER, run_id=_run_id(1), ttl_s=-999.0)
        assert [
            r["id"] for r in await evals_store.list_live_runs(session, org_id=ORG)
        ] == [_run_id(1)]

    async def test_live_runs_cross_org_when_unscoped(self, session) -> None:
        """Verify that a missing org_id returns leased runs from all organizations."""
        await _mk_run(session, 1, status="running")
        await _mk_run(session, 2, org=OTHER, status="running")
        await evals_store.renew_lease(session, org_id=ORG, run_id=_run_id(1), ttl_s=60.0)
        await evals_store.renew_lease(session, org_id=OTHER, run_id=_run_id(2), ttl_s=60.0)
        live = await evals_store.list_live_runs(session)
        assert {r["id"] for r in live} == {_run_id(1), _run_id(2)}
        assert {
            r["id"] for r in await evals_store.list_live_runs(session, org_id=ORG)
        } == {_run_id(1)}


class TestAccuracyHistory:
    @staticmethod
    def _entry(n: int, *, ref: str = "ref-1", fp: str = "fp-1", acc: float = 90.0, docs=None):
        return {
            "run_id": _run_id(n),
            "created_at": f"2026-01-01T00:00:{n:02d}+00:00",
            "trigger": "manual",
            "eval_set_name": "set",
            "eval_set_ref": ref,
            "build_fingerprint": fp,
            "tasks_total": 10,
            "tasks_passed": int(acc / 10),
            "accuracy_pct": acc,
            "coverage_pct": None,
            "kb_doc_ids": docs or [],
        }

    async def test_append_and_list(self, session) -> None:
        await evals_store.append_accuracy(session, org_id=ORG, entry=self._entry(1))
        await evals_store.append_accuracy(session, org_id=ORG, entry=self._entry(2, acc=80.0))
        history = await evals_store.list_accuracy(session, org_id=ORG)
        assert [h["run_id"] for h in history] == [_run_id(2), _run_id(1)]
        assert history[0]["accuracy_pct"] == 80.0
        assert await evals_store.list_accuracy(session, org_id=OTHER) == []

    async def test_trailing_baseline_filters_ref_fingerprint_and_time(self, session) -> None:
        await evals_store.append_accuracy(session, org_id=ORG, entry=self._entry(1, acc=90))
        await evals_store.append_accuracy(
            session, org_id=ORG, entry=self._entry(2, ref="ref-OTHER", acc=10)
        )
        await evals_store.append_accuracy(
            session, org_id=ORG, entry=self._entry(3, fp="fp-OTHER", acc=10)
        )
        await evals_store.append_accuracy(session, org_id=ORG, entry=self._entry(4, acc=85))
        await evals_store.append_accuracy(session, org_id=ORG, entry=self._entry(5, acc=50))

        baseline = await evals_store.trailing_baseline(
            session,
            org_id=ORG,
            eval_set_ref="ref-1",
            build_fingerprint="fp-1",
            before="2026-01-01T00:00:05+00:00",  # run 5 itself excluded
        )
        assert [b["run_id"] for b in baseline] == [_run_id(4), _run_id(1)]
        assert [b["accuracy_pct"] for b in baseline] == [85, 90]

    async def test_trailing_baseline_window(self, session) -> None:
        for n in range(1, 9):
            await evals_store.append_accuracy(session, org_id=ORG, entry=self._entry(n))
        baseline = await evals_store.trailing_baseline(
            session,
            org_id=ORG,
            eval_set_ref="ref-1",
            build_fingerprint="fp-1",
            before="2026-01-01T00:00:59+00:00",
            window=5,
        )
        assert len(baseline) == 5
        assert baseline[0]["run_id"] == _run_id(8)

    async def test_regressions_roundtrip(self, session) -> None:
        rid = await evals_store.record_regression(
            session,
            org_id=ORG,
            entry={
                "run_id": _run_id(9),
                "created_at": "2026-01-01T01:00:00+00:00",
                "baseline_run_ids": [_run_id(1)],
                "baseline_accuracy_pct": 90.0,
                "run_accuracy_pct": 60.0,
                "drop_pct": 30.0,
                "suspected_doc_ids": ["doc-9"],
                "sole_change": True,
                "flipped_tasks": [{"task_id": "q1", "title": "t", "verdict": "OFF"}],
                "recipients": ["a@example.com"],
                "notified_at": None,
            },
        )
        assert rid
        (reg,) = await evals_store.list_regressions(session, org_id=ORG)
        assert reg["drop_pct"] == 30.0
        assert reg["suspected_doc_ids"] == ["doc-9"]
        assert reg["sole_change"] is True
        assert await evals_store.list_regressions(session, org_id=OTHER) == []


class TestRetentionBookkeeping:
    async def test_runs_outside_window(self, session) -> None:
        for n in range(1, 16):
            await _mk_run(session, n)
        victims = await evals_store.runs_outside_window(
            session, org_id=ORG, window=10, flag="artifacts_pruned"
        )
        # Keep the 10 newest runs and select the five oldest runs.
        assert sorted(victims) == sorted(_run_id(n) for n in range(1, 6))

    async def test_live_runs_are_never_victims(self, session) -> None:
        for n in range(1, 15):
            await _mk_run(session, n)
        await _mk_run(session, 15, status="running")
        # run 15 is newest, so the window keeps 10 newest; among the rest only
        # Select only completed runs and exclude an active older run.
        await evals_store.update_run(
            session, org_id=ORG, run_id=_run_id(1), status="running"
        )
        victims = await evals_store.runs_outside_window(
            session, org_id=ORG, window=10, flag="artifacts_pruned"
        )
        assert _run_id(1) not in victims
        assert sorted(victims) == sorted(_run_id(n) for n in range(2, 6))

    async def test_mark_pruned_removes_from_future_sweeps(self, session) -> None:
        for n in range(1, 16):
            await _mk_run(session, n)
        victims = await evals_store.runs_outside_window(
            session, org_id=ORG, window=10, flag="artifacts_pruned"
        )
        await evals_store.mark_pruned(
            session, org_id=ORG, run_ids=victims, flag="artifacts_pruned"
        )
        assert (
            await evals_store.runs_outside_window(
                session, org_id=ORG, window=10, flag="artifacts_pruned"
            )
            == []
        )
        # The traces flag is independent.
        assert (
            await evals_store.runs_outside_window(
                session, org_id=ORG, window=10, flag="traces_pruned"
            )
            != []
        )

    async def test_delete_trace_rows_keeps_the_run_tombstone(self, session) -> None:
        run_id = await _mk_run(session, 1)
        await evals_store.seed_tasks(
            session, org_id=ORG, run_id=run_id, tasks=[{"task_id": "q1"}, {"task_id": "q2"}]
        )
        await evals_store.delete_trace_rows(session, org_id=ORG, run_ids=[run_id])
        assert await evals_store.get_tasks(session, org_id=ORG, run_id=run_id) == []
        assert (await evals_store.get_run(session, org_id=ORG, run_id=run_id)) is not None

    async def test_count_and_org_enumeration(self, session) -> None:
        await _mk_run(session, 1)
        await _mk_run(session, 2, org=OTHER)
        assert await evals_store.count_runs(session, org_id=ORG) == 1
        assert set(await evals_store.org_ids_with_runs(session)) == {ORG, OTHER}


class TestSandboxIndex:
    async def test_tasks_with_live_sandboxes(self, session) -> None:
        run_id = await _mk_run(session, 1, status="running")
        await evals_store.seed_tasks(
            session,
            org_id=ORG,
            run_id=run_id,
            tasks=[{"task_id": "q1", "title": "first"}, {"task_id": "q2", "title": "second"}],
        )
        await evals_store.update_task(
            session,
            org_id=ORG,
            run_id=run_id,
            task_id="q1",
            sandbox={"backend": "docker", "name": "cafebabe0000"},
        )
        index = await evals_store.tasks_with_live_sandboxes(session, org_id=ORG)
        # The index contains task_id, task_title, and task_phase keys.
        assert index == {
            "cafebabe0000": {
                "run_id": run_id,
                "task_id": "q1",
                "task_title": "first",
            }
        }

    async def test_index_is_org_scoped(self, session) -> None:
        run_id = await _mk_run(session, 1, status="running")
        await evals_store.seed_tasks(
            session, org_id=ORG, run_id=run_id, tasks=[{"task_id": "q1"}]
        )
        await evals_store.update_task(
            session, org_id=ORG, run_id=run_id, task_id="q1", sandbox={"name": "cafebabe0000"}
        )
        assert await evals_store.tasks_with_live_sandboxes(session, org_id=OTHER) == {}


class TestOrgScopingAtTheStoreLayer:
    async def test_get_run_never_crosses_orgs(self, session) -> None:
        run_id = await _mk_run(session, 1)
        assert await evals_store.get_run(session, org_id=OTHER, run_id=run_id) is None
        assert await evals_store.run_exists(session, org_id=OTHER, run_id=run_id) is False

    async def test_update_run_cannot_reach_a_foreign_run(self, session) -> None:
        run_id = await _mk_run(session, 1)
        await evals_store.update_run(
            session, org_id=OTHER, run_id=run_id, status="failed", error="tampered"
        )
        run = await evals_store.get_run(session, org_id=ORG, run_id=run_id)
        assert run["status"] == "completed"
        assert run["error"] is None
