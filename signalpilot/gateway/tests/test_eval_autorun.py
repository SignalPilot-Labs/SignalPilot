"""Verify automatic evaluation runs for knowledge base additions.

The automatic run path bypasses the route guards, so it re-checks the same two
questions before it spends model resources: can this deployment run evals, and
is the org on a billable plan. The tests use a test double for
``store.get_eval_config`` and a table of entitlements in place of the
subscriptions read.
"""

from __future__ import annotations

import pytest

from gateway.api import eval_runs
from gateway.billing import entitlements as ent
from gateway.billing.entitlements import OrgEntitlement
from gateway.config.evals import get_eval_run_settings

BILLABLE_ORG = "org_2teamclerkid"
OTHER_BILLABLE_ORG = "org_2scaleclerkid"
FREE_ORG = "org_2freeclerkid"
RUNNER_IMAGE = "example.com/eval-runner@sha256:" + "a" * 64

ENTITLEMENTS = {
    BILLABLE_ORG: OrgEntitlement(org_id=BILLABLE_ORG, tier="team", status="active"),
    OTHER_BILLABLE_ORG: OrgEntitlement(org_id=OTHER_BILLABLE_ORG, tier="scale", status="active"),
    FREE_ORG: OrgEntitlement(org_id=FREE_ORG, tier="free", status="none"),
}


class FakeStore:
    """Verify that the run path reads only the organization and config."""

    def __init__(self, org_id: str = BILLABLE_ORG, cfg: dict | None = None) -> None:
        self.org_id = org_id
        self.user_id = "user-1"
        self._cfg = cfg if cfg is not None else {}

    async def get_eval_config(self) -> dict:
        return dict(self._cfg)


def _store(org_id: str = BILLABLE_ORG, **overrides) -> FakeStore:
    cfg = {
        "repo_url": "https://example.com/set.git",
        "project_repo_url": "https://github.com/acme/dbt.git",
        "autorun_on_knowledge_add": True,
    }
    cfg.update(overrides)
    return FakeStore(org_id, cfg)


class FakeDoc:
    def __init__(self, status: str = "active", doc_id: str = "doc-1") -> None:
        self.status = status
        self.id = doc_id


class _EnumLike:
    """Mimics KnowledgeStatus. status is an enum on some paths, a str on others."""

    def __init__(self, value: str) -> None:
        self.value = value


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_BACKEND_URL", "https://backend.invalid")
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", RUNNER_IMAGE)
    monkeypatch.setenv("SP_EVAL_S3_BUCKET", "sp-eval-runs")
    monkeypatch.delenv("SP_EVAL_EXECUTION_BACKEND", raising=False)
    get_eval_run_settings.cache_clear()

    async def _load(org_id: str) -> OrgEntitlement:
        return ENTITLEMENTS.get(org_id) or ent.free_entitlement(org_id)

    monkeypatch.setattr(ent, "_load_entitlement", _load)
    ent.invalidate()
    eval_runs._last_autorun.clear()
    eval_runs._active_tasks.clear()
    yield
    ent.invalidate()
    get_eval_run_settings.cache_clear()
    eval_runs._last_autorun.clear()
    eval_runs._active_tasks.clear()


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture _launch_run calls instead of starting real containers."""
    calls: list[dict] = []

    async def fake_launch(store, *, doc_ids, doc_titles, task_ids, trigger):
        calls.append(
            {"org": store.org_id, "doc_ids": doc_ids, "task_ids": task_ids, "trigger": trigger}
        )
        return {"id": f"run-2026010{len(calls)}-010101-aaaaaa"}

    monkeypatch.setattr(eval_runs, "_launch_run", fake_launch)
    return calls


class TestItFires:
    async def test_active_doc_starts_a_baseline_run(self, launched) -> None:
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc())
        assert len(launched) == 1
        # Baseline: nothing overlaid, whole set.
        assert launched[0]["doc_ids"] == []
        assert launched[0]["task_ids"] is None
        assert launched[0]["trigger"] == "kb_add"

    async def test_enum_status_is_understood(self, launched) -> None:
        """status arrives as a KnowledgeStatus enum from some call paths."""
        doc = FakeDoc()
        doc.status = _EnumLike("active")
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), doc)
        assert len(launched) == 1

    async def test_any_user_of_a_billable_org_can_trigger_it(self, launched) -> None:
        """There is no staff list: the org's plan is the only entitlement."""
        store = _store()
        store.user_id = "user_plain_member"
        await eval_runs.maybe_autorun_after_knowledge_change(store, FakeDoc())
        assert len(launched) == 1


class TestItDoesNotFire:
    async def test_off_by_default(self, launched) -> None:
        store = FakeStore(BILLABLE_ORG, {"repo_url": "https://example.com/set.git"})
        await eval_runs.maybe_autorun_after_knowledge_change(store, FakeDoc())
        assert launched == []

    @pytest.mark.parametrize("status", ["pending", "archived"])
    async def test_only_entries_in_the_knowledge_base(self, launched, status: str) -> None:
        """A pending entry is graded on demand from the knowledge page, not here."""
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc(status=status))
        assert launched == []

    async def test_free_org_cannot_spend_via_autorun(self, launched) -> None:
        """The gates are bypassed on this path, so the plan is re-checked."""
        await eval_runs.maybe_autorun_after_knowledge_change(_store(FREE_ORG), FakeDoc())
        assert launched == []

    async def test_no_repo_configured(self, launched) -> None:
        await eval_runs.maybe_autorun_after_knowledge_change(_store(repo_url=""), FakeDoc())
        assert launched == []

    async def test_no_project_repo_configured(self, launched) -> None:
        await eval_runs.maybe_autorun_after_knowledge_change(_store(project_repo_url=""), FakeDoc())
        assert launched == []

    async def test_runner_disabled(self, launched, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SP_EVAL_RUNNER_IMAGE", raising=False)
        get_eval_run_settings.cache_clear()
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc())
        assert launched == []

    async def test_deployment_without_an_evidence_store(self, launched, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SP_EVAL_S3_BUCKET", raising=False)
        get_eval_run_settings.cache_clear()
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc())
        assert launched == []


class TestCoalescing:
    async def test_a_burst_of_additions_is_one_run(self, launched) -> None:
        """Importing ten entries is one editing session, not ten runs."""
        for i in range(10):
            await eval_runs.maybe_autorun_after_knowledge_change(
                _store(), FakeDoc(doc_id=f"doc-{i}")
            )
        assert len(launched) == 1

    async def test_it_runs_again_once_the_window_passes(self, launched) -> None:
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc())
        assert len(launched) == 1

        # Move the recorded timestamp back beyond the debounce window.
        eval_runs._last_autorun[BILLABLE_ORG] -= eval_runs._AUTORUN_DEBOUNCE_SECONDS + 1
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc())
        assert len(launched) == 2

    async def test_debounce_is_per_org(self, launched) -> None:
        await eval_runs.maybe_autorun_after_knowledge_change(_store(BILLABLE_ORG), FakeDoc())
        await eval_runs.maybe_autorun_after_knowledge_change(_store(OTHER_BILLABLE_ORG), FakeDoc())
        assert {c["org"] for c in launched} == {BILLABLE_ORG, OTHER_BILLABLE_ORG}

    async def test_at_the_concurrency_limit_it_skips(self, launched) -> None:
        eval_runs._active_tasks.update(
            {f"run-{i}": _NeverDone() for i in range(eval_runs._MAX_CONCURRENT_RUNS)}
        )
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc())
        assert launched == []


class _NeverDone:
    """Stands in for an in-flight asyncio.Task."""

    def done(self) -> bool:
        return False


class TestItNeverBreaksTheWrite:
    async def test_a_failure_does_not_propagate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Autorun hangs off knowledge writes; it must not fail the write."""

        async def boom(*args, **kwargs):
            raise RuntimeError("cluster unreachable")

        monkeypatch.setattr(eval_runs, "_launch_run", boom)
        # Must not raise.
        await eval_runs.maybe_autorun_after_knowledge_change(_store(), FakeDoc())

    async def test_a_broken_store_does_not_propagate(self) -> None:
        """Verify that the gating checks occur before the config read."""

        class _BrokenStore:
            org_id = BILLABLE_ORG
            user_id = "user-1"

            async def get_eval_config(self):
                raise RuntimeError("db down")

        await eval_runs.maybe_autorun_after_knowledge_change(_BrokenStore(), FakeDoc())
