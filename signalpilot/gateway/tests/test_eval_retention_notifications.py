"""Verify retention enforcement and regression notifications.

Retention keeps artifacts for 10 runs and traces for 100 runs. Retention does
not modify accuracy records. Regression notifications include the knowledge
base difference and go only to configured recipients.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.config.evals import EvalRunSettings, get_eval_run_settings
from gateway.db.models import GatewayBase, GatewayEvalRun, GatewayEvalRunTask
from gateway.evals import notifications, retention
from gateway.evals.object_store import EvalObjectStore
from gateway.store import evals as evals_store

ORG = "org-a"


async def test_project_presign_uses_runner_proxy_endpoint() -> None:
    settings = EvalRunSettings(
        SP_EVAL_S3_BUCKET="evidence",
        SP_EVAL_S3_ENDPOINT="http://minio:9000",
        SP_EVAL_S3_RUNNER_ENDPOINT="http://eval-object-proxy:9000",
        SP_EVAL_S3_ACCESS_KEY="access",
        SP_EVAL_S3_SECRET_KEY="secret",
    )
    obj = EvalObjectStore(settings)
    client = MagicMock()
    client.generate_presigned_url.return_value = "http://eval-object-proxy:9000/signed"
    with patch.object(obj, "_client", return_value=client) as build_client:
        url = await obj.presign_get("evals/org/runs/run/project.tgz")
    assert url.startswith("http://eval-object-proxy:9000/")
    build_client.assert_called_once_with(endpoint_url="http://eval-object-proxy:9000")


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest.fixture(autouse=True)
def _settings_cache():
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


def _run_id(n: int) -> str:
    return f"run-20260101-{n:06d}-{n:06x}"


def _created(n: int) -> str:
    return f"2026-01-01T{n // 3600:02d}:{(n // 60) % 60:02d}:{n % 60:02d}+00:00"


async def _seed_runs(factory, count: int, *, tasks_for: set[int] = frozenset()) -> None:
    """Bulk-insert completed runs (oldest = 1) in one commit."""
    async with factory() as session:
        for n in range(1, count + 1):
            session.add(
                GatewayEvalRun(
                    id=_run_id(n),
                    org_id=ORG,
                    status="completed",
                    trigger="manual",
                    created_at=_created(n),
                )
            )
            if n in tasks_for:
                session.add(
                    GatewayEvalRunTask(
                        run_id=_run_id(n), org_id=ORG, task_id="q1", position=0
                    )
                )
        await session.commit()


class _FakeObjectStore:
    """Records delete_prefix calls; key layout borrowed from the real store."""

    artifacts_prefix = EvalObjectStore.artifacts_prefix
    run_prefix = EvalObjectStore.run_prefix
    org_prefix = EvalObjectStore.org_prefix

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_prefix(self, prefix: str) -> int:
        self.deleted.append(prefix)
        return 3


@pytest.fixture
def fake_obj(monkeypatch: pytest.MonkeyPatch, factory) -> _FakeObjectStore:
    obj = _FakeObjectStore()
    monkeypatch.setattr(retention, "get_object_store", lambda: obj)
    monkeypatch.setattr(retention, "get_session_factory", lambda: factory)
    return obj


class TestEnforceRetention:
    async def test_artifacts_pruned_past_the_10_run_window(self, factory, fake_obj) -> None:
        await _seed_runs(factory, 15)
        pruned = await retention.enforce_retention(ORG)
        assert pruned["artifact_runs"] == 5
        assert pruned["trace_runs"] == 0  # well inside the 100-run trace window
        assert pruned["objects"] == 15  # Five runs contain three objects each.
        expected = {
            EvalObjectStore.artifacts_prefix(ORG, _run_id(n)) for n in range(1, 6)
        }
        assert set(fake_obj.deleted) == expected

    async def test_a_second_sweep_is_a_noop(self, factory, fake_obj) -> None:
        await _seed_runs(factory, 15)
        await retention.enforce_retention(ORG)
        fake_obj.deleted.clear()
        pruned = await retention.enforce_retention(ORG)
        assert pruned == {"artifact_runs": 0, "trace_runs": 0, "objects": 0}
        assert fake_obj.deleted == []

    async def test_traces_pruned_past_the_100_run_window(self, factory, fake_obj) -> None:
        await _seed_runs(factory, 105, tasks_for={1, 2, 3, 4, 5})
        pruned = await retention.enforce_retention(ORG)
        assert pruned["trace_runs"] == 5
        assert pruned["artifact_runs"] == 95  # everything past the 10-run window
        # Trace pruning deletes the whole run prefix and the task rows...
        for n in range(1, 6):
            assert EvalObjectStore.run_prefix(ORG, _run_id(n)) + "/" in fake_obj.deleted
            async with factory() as session:
                assert await evals_store.get_tasks(session, org_id=ORG, run_id=_run_id(n)) == []
        # ...but the run row stays as a tombstone.
        async with factory() as session:
            assert await evals_store.get_run(session, org_id=ORG, run_id=_run_id(1)) is not None

    async def test_accuracy_history_is_never_touched(self, factory, fake_obj) -> None:
        await _seed_runs(factory, 105)
        async with factory() as session:
            for n in range(1, 106):
                await evals_store.append_accuracy(
                    session,
                    org_id=ORG,
                    entry={
                        "run_id": _run_id(n),
                        "created_at": _created(n),
                        "trigger": "manual",
                        "eval_set_name": "s",
                        "eval_set_ref": "r",
                        "build_fingerprint": "f",
                        "tasks_total": 1,
                        "tasks_passed": 1,
                        "accuracy_pct": 100.0,
                        "coverage_pct": None,
                        "kb_doc_ids": [],
                    },
                )
        await retention.enforce_retention(ORG)
        async with factory() as session:
            history = await evals_store.list_accuracy(session, org_id=ORG, limit=1000)
        assert len(history) == 105

    async def test_a_failed_object_delete_defers_the_db_prune(
        self, factory, fake_obj, monkeypatch
    ) -> None:
        """The DB flag flips only after S3 is actually clean, so a transient
        S3 failure is retried on the next sweep instead of leaking forever."""
        await _seed_runs(factory, 11)

        async def boom(prefix: str) -> int:
            raise RuntimeError("s3 down")

        monkeypatch.setattr(fake_obj, "delete_prefix", boom)
        pruned = await retention.enforce_retention(ORG)
        assert pruned["artifact_runs"] == 0
        # Next sweep still sees the victim.
        async with factory() as session:
            victims = await evals_store.runs_outside_window(
                session, org_id=ORG, window=10, flag="artifacts_pruned"
            )
        assert victims == [_run_id(1)]


ACC_ENTRY_DEFAULTS = {
    "trigger": "manual",
    "eval_set_name": "set",
    "eval_set_ref": "ref-1",
    "build_fingerprint": "fp-1",
    "tasks_total": 10,
    "coverage_pct": None,
}


def _run(n: int, *, kb_docs: list[str]) -> dict:
    return {
        "id": _run_id(n),
        "created_at": _created(n),
        "eval_set_name": "set",
        "eval_set_ref": "ref-1",
        "build_fingerprint": "fp-1",
        "kb_doc_ids": kb_docs,
    }


TASKS = [
    {"task_id": "q1", "title": "first", "verdict": "CORRECT"},
    {"task_id": "q2", "title": "second", "verdict": "OFF"},
    {"task_id": "q3", "title": "third", "verdict": "UNGRADED"},
]


class TestCheckRegressionAndNotify:
    @pytest_asyncio.fixture
    async def wired(self, factory, monkeypatch):
        monkeypatch.setattr(notifications, "get_session_factory", lambda: factory)
        sent: list[dict] = []

        def capture(settings, recipients, org_id, run, entry, sole_change):
            sent.append(
                {"recipients": recipients, "entry": entry, "sole_change": sole_change}
            )

        monkeypatch.setattr(notifications, "_send_email", capture)
        return sent

    async def _baseline(
        self, factory, *, accs=(90.0, 92.0, 88.0), docs=("doc-a",), fp="fp-1"
    ):
        async with factory() as session:
            for i, acc in enumerate(accs, start=1):
                await evals_store.append_accuracy(
                    session,
                    org_id=ORG,
                    entry={
                        **ACC_ENTRY_DEFAULTS,
                        "run_id": _run_id(i),
                        "created_at": _created(i),
                        "build_fingerprint": fp,
                        "tasks_passed": int(acc / 10),
                        "accuracy_pct": acc,
                        "kb_doc_ids": list(docs),
                    },
                )

    async def test_big_drop_records_a_regression_with_the_kb_diff(
        self, factory, wired
    ) -> None:
        await self._baseline(factory)
        async with factory() as session:
            await evals_store.save_config(
                session, org_id=ORG, cfg={"notify_emails": ["ops@example.com", "not-an-email"]}
            )

        entry = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=["doc-a", "doc-new"]), TASKS, accuracy_pct=60.0
        )
        assert entry is not None
        assert entry["baseline_accuracy_pct"] == 90.0  # median of 88/90/92
        assert entry["run_accuracy_pct"] == 60.0
        assert entry["drop_pct"] == 30.0
        # Suspected documents exist in the current run but not the latest baseline.
        assert entry["suspected_doc_ids"] == ["doc-new"]
        assert entry["added_doc_ids"] == ["doc-new"]
        assert entry["removed_doc_ids"] == []
        assert entry["other_changes"] == []
        assert entry["sole_change"] is True
        assert {t["task_id"] for t in entry["flipped_tasks"]} == {"q2"}
        # Email went to the valid opted-in recipient only, and was recorded.
        assert wired[0]["recipients"] == ["ops@example.com"]
        assert entry["notified_at"] is not None
        async with factory() as session:
            (reg,) = await evals_store.list_regressions(session, org_id=ORG)
        assert reg["run_id"] == _run_id(50)
        assert reg["sole_change"] is True

    async def test_multiple_new_docs_is_not_sole_change(self, factory, wired) -> None:
        await self._baseline(factory)
        entry = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=["doc-a", "doc-x", "doc-y"]), TASKS, accuracy_pct=60.0
        )
        assert entry["suspected_doc_ids"] == ["doc-x", "doc-y"]
        assert entry["sole_change"] is False

    async def test_a_run_without_a_fingerprint_records_and_sends_nothing(
        self, factory, wired
    ) -> None:
        """Verify that a missing fingerprint prevents regression attribution.

        The run produces no regression record or email.
        """
        # Baseline rows whose fingerprint is ALSO empty, so the missing-baseline
        # The fingerprint check prevents the comparison.
        await self._baseline(factory, fp="")
        async with factory() as session:
            await evals_store.save_config(
                session, org_id=ORG, cfg={"notify_emails": ["ops@example.com"]}
            )
        run = _run(50, kb_docs=["doc-a", "doc-new"])
        run["build_fingerprint"] = ""

        result = await notifications.check_regression_and_notify(
            ORG, run, TASKS, accuracy_pct=10.0
        )
        assert result is None
        assert wired == []
        async with factory() as session:
            assert await evals_store.list_regressions(session, org_id=ORG) == []

    async def test_a_withdrawn_entry_counts_and_defeats_sole_change(
        self, factory, wired
    ) -> None:
        """Verify that the difference includes a deleted knowledge base entry.

        The notification must not attribute the result to one added entry.
        """
        await self._baseline(factory, docs=("doc-a", "doc-old"))
        entry = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=["doc-a"]), TASKS, accuracy_pct=60.0
        )
        assert entry is not None
        assert entry["added_doc_ids"] == []
        assert entry["removed_doc_ids"] == ["doc-old"]
        assert entry["suspected_doc_ids"] == ["doc-old"]
        assert entry["sole_change"] is False

    async def test_added_and_removed_docs_both_appear_in_the_entry(
        self, factory, wired
    ) -> None:
        await self._baseline(factory, docs=("doc-a", "doc-old"))
        entry = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=["doc-a", "doc-new"]), TASKS, accuracy_pct=60.0
        )
        assert entry is not None
        assert entry["added_doc_ids"] == ["doc-new"]
        assert entry["removed_doc_ids"] == ["doc-old"]
        # Build the suspected list from added entries followed by deleted entries.
        assert entry["suspected_doc_ids"] == ["doc-new", "doc-old"]
        assert entry["sole_change"] is False
        async with factory() as session:
            (reg,) = await evals_store.list_regressions(session, org_id=ORG)
        assert reg["suspected_doc_ids"] == ["doc-new", "doc-old"]
        assert reg["sole_change"] is False

    async def test_below_threshold_drop_is_none(self, factory, wired) -> None:
        """Default threshold is 10 points."""
        await self._baseline(factory)
        result = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=["doc-a"]), TASKS, accuracy_pct=85.0
        )
        assert result is None
        assert wired == []
        async with factory() as session:
            assert await evals_store.list_regressions(session, org_id=ORG) == []

    async def test_no_comparable_baseline_is_none(self, factory, wired) -> None:
        """Verify that different set references or fingerprints prevent comparison."""
        async with factory() as session:
            await evals_store.append_accuracy(
                session,
                org_id=ORG,
                entry={
                    **ACC_ENTRY_DEFAULTS,
                    "run_id": _run_id(1),
                    "created_at": _created(1),
                    "eval_set_ref": "some-other-ref",
                    "tasks_passed": 9,
                    "accuracy_pct": 90.0,
                    "kb_doc_ids": [],
                },
            )
        result = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=[]), TASKS, accuracy_pct=10.0
        )
        assert result is None

    async def test_nobody_opted_in_records_but_does_not_email(self, factory, wired) -> None:
        await self._baseline(factory)
        entry = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=["doc-a", "doc-new"]), TASKS, accuracy_pct=60.0
        )
        assert entry is not None
        assert entry["recipients"] == []
        assert entry["notified_at"] is None
        assert wired == []

    async def test_a_failed_email_still_records_the_regression(
        self, factory, wired, monkeypatch
    ) -> None:
        await self._baseline(factory)
        async with factory() as session:
            await evals_store.save_config(
                session, org_id=ORG, cfg={"notify_emails": ["ops@example.com"]}
            )

        def boom(*args):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(notifications, "_send_email", boom)
        entry = await notifications.check_regression_and_notify(
            ORG, _run(50, kb_docs=["doc-a"]), TASKS, accuracy_pct=60.0
        )
        assert entry is not None
        assert entry["notified_at"] is None
        async with factory() as session:
            assert len(await evals_store.list_regressions(session, org_id=ORG)) == 1
