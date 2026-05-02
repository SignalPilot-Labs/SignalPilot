"""Per-round stratified sampler.

Composition (defaults, configurable):
- 60% fresh exploration: tasks not run in last K rounds, stratified by DB,
                         capped at 2 per DB to avoid within-DB redundancy.
- 30% targeted re-attempts: previously-failed tasks (most-recent FAIL).
- 10% regression anchors: random sample from the passing pool.

A held-out set (configurable, default 20 tasks) is excluded from all sampling.
The held-out set is computed deterministically from a seed so it stays stable
across runs.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from ..core.suite import BenchmarkSuite, get_suite_config
from ..core.tasks import load_task_for_suite
from . import registry as reg


@dataclass
class SampleComposition:
    fresh: list[str]
    targeted: list[str]
    regression: list[str]

    @property
    def all_tasks(self) -> list[str]:
        return self.fresh + self.targeted + self.regression

    def summary(self) -> str:
        return (
            f"  fresh:      {len(self.fresh):>3} {self.fresh}\n"
            f"  targeted:   {len(self.targeted):>3} {self.targeted}\n"
            f"  regression: {len(self.regression):>3} {self.regression}"
        )


def list_all_tasks(suite: BenchmarkSuite) -> list[str]:
    """All instance ids defined in the suite's task JSONL.

    Reads instance_id from each line of <suite>.jsonl. The gold dir contains
    tasks across multiple backends (BigQuery bq*, Snowflake sf*, local*) so
    filtering by JSONL is more precise — and lets us scope to one backend.
    """
    import json as _json
    config = get_suite_config(suite)
    if not config.task_jsonl.exists():
        return []
    ids: list[str] = []
    for line in config.task_jsonl.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = _json.loads(line)
        except Exception:
            continue
        iid = row.get("instance_id") or row.get("id")
        if iid:
            ids.append(iid)
    return sorted(set(ids))


def list_local_tasks(suite: BenchmarkSuite) -> list[str]:
    """Only instance ids starting with 'local' — i.e., the SQLite subset of spider2-lite."""
    return [t for t in list_all_tasks(suite) if t.startswith("local")]


def task_db(suite: BenchmarkSuite, task_id: str) -> str:
    config = get_suite_config(suite)
    try:
        task = load_task_for_suite(task_id, config)
    except Exception:
        return "unknown"
    return task.get("db") or task.get("db_id") or "unknown"


def _matches_filters(task_id: str, task_filter: str | None, task_filters: list[str] | None) -> bool:
    """Return True if task_id matches any of task_filters (preferred) or task_filter (fallback)."""
    if task_filters:
        return any(task_id.startswith(p) for p in task_filters)
    if task_filter:
        return task_id.startswith(task_filter)
    return True


def held_out_set(
    suite: BenchmarkSuite,
    n: int = 20,
    seed: int = 42,
    task_filter: str = "local",
    task_filters: list[str] | None = None,
) -> set[str]:
    """Deterministic held-out set — never used in sampling.

    If task_filters is provided it wins over task_filter; a task matches if any
    prefix in task_filters matches. Same seed → same holdout across runs.
    """
    rng = random.Random(seed)
    tasks = list_all_tasks(suite)
    tasks = [t for t in tasks if _matches_filters(t, task_filter, task_filters)]
    if len(tasks) <= n:
        return set(tasks)
    return set(rng.sample(tasks, n))


def cloud_held_out_set(suite: BenchmarkSuite, seed: int = 42) -> set[str]:
    """Stratified n=30 cloud holdout: 14 sf + 13 bq + 3 ga (seed=42).

    Sacred — never re-roll. See AUTOFYN_CLOUD_PROMPT.md §3.2.
    """
    rng = random.Random(seed)
    pool = list_all_tasks(suite)
    sf = sorted(t for t in pool if t.startswith("sf"))
    bq = sorted(t for t in pool if t.startswith("bq"))
    ga = sorted(t for t in pool if t.startswith("ga"))
    return set(
        rng.sample(sf, min(14, len(sf)))
        + rng.sample(bq, min(13, len(bq)))
        + rng.sample(ga, min(3, len(ga)))
    )


def sample_round(
    suite: BenchmarkSuite,
    n_total: int = 30,
    fresh_frac: float = 0.6,
    targeted_frac: float = 0.3,
    regression_frac: float = 0.1,
    cooldown_rounds: int = 2,
    per_db_cap: int = 2,
    holdout_size: int = 20,
    holdout_seed: int = 42,
    seed: int | None = None,
    task_filter: str = "local",
    task_filters: list[str] | None = None,
) -> SampleComposition:
    """Build one round's sample. seed=None uses the registry round number for reproducibility.

    task_filter="local" restricts to spider2-lite SQLite tasks (the runnable subset
    on this machine). Use "" or None to include all tasks in the JSONL. If
    task_filters is provided (e.g. ["sf","bq","ga"] for cloud), it overrides
    task_filter and a task matches if any prefix matches.
    """
    records = reg.load_all()
    next_round = reg.current_round(records)
    rng = random.Random(seed if seed is not None else next_round * 1000 + 7)

    pool = list_all_tasks(suite)
    pool = [t for t in pool if _matches_filters(t, task_filter, task_filters)]

    # When task_filters is set (cloud mode), use the dedicated cloud holdout
    # (n=30, stratified across sf/bq/ga). Otherwise fall back to the legacy
    # single-prefix holdout.
    if task_filters and set(task_filters) >= {"sf", "bq", "ga"}:
        holdout = cloud_held_out_set(suite, seed=holdout_seed)
    else:
        holdout = held_out_set(
            suite,
            n=holdout_size,
            seed=holdout_seed,
            task_filter=task_filter,
            task_filters=task_filters,
        )
    all_tasks = [t for t in pool if t not in holdout]

    recent = reg.recently_run(records, cooldown_rounds)
    passing = reg.passing_pool(records)
    failing = reg.failing_pool(records)

    n_fresh = int(round(n_total * fresh_frac))
    n_target = int(round(n_total * targeted_frac))
    n_reg = max(0, n_total - n_fresh - n_target)

    # ── fresh: exclude recently-run, stratify by DB, cap per DB ────────────────
    fresh_candidates = [t for t in all_tasks if t not in recent and t not in passing and t not in failing]
    # If we've run everything, allow re-running long-cooldown tasks
    if not fresh_candidates:
        fresh_candidates = [t for t in all_tasks if t not in recent]

    by_db: dict[str, list[str]] = defaultdict(list)
    for t in fresh_candidates:
        by_db[task_db(suite, t)].append(t)

    fresh: list[str] = []
    db_keys = list(by_db.keys())
    rng.shuffle(db_keys)
    db_picks: dict[str, int] = defaultdict(int)
    while len(fresh) < n_fresh and db_keys:
        progress = False
        for db in db_keys:
            if len(fresh) >= n_fresh:
                break
            if db_picks[db] >= per_db_cap:
                continue
            pool = by_db[db]
            remaining = [t for t in pool if t not in fresh]
            if not remaining:
                continue
            fresh.append(rng.choice(remaining))
            db_picks[db] += 1
            progress = True
        if not progress:
            break

    # ── targeted: previously-FAIL tasks not run in cooldown ────────────────────
    # CRITICAL: must exclude holdout AND respect the active filter (registry
    # may contain tasks from a different filter scope, e.g. local* records when
    # we're now sampling cloud).
    target_candidates = [
        t for t in failing
        if t not in recent and t not in fresh and t not in holdout
        and _matches_filters(t, task_filter, task_filters)
    ]
    rng.shuffle(target_candidates)
    targeted = target_candidates[:n_target]

    # ── regression: random from passing-pool, exclude already-picked + holdout ─
    reg_candidates = [
        t for t in passing
        if t not in recent and t not in fresh and t not in targeted and t not in holdout
        and _matches_filters(t, task_filter, task_filters)
    ]
    rng.shuffle(reg_candidates)
    regression = reg_candidates[:n_reg]

    # ── top-up: if targeted/regression underfilled (e.g. early rounds with
    # everything in cooldown), pad with more fresh exploration so we hit n_total.
    deficit = n_total - (len(fresh) + len(targeted) + len(regression))
    if deficit > 0:
        already = set(fresh) | set(targeted) | set(regression)
        # Reuse the by-DB structure but raise the cap; if still short, allow recent
        spare: list[str] = [t for t in fresh_candidates if t not in already]
        rng.shuffle(spare)
        fresh.extend(spare[:deficit])
        deficit = n_total - (len(fresh) + len(targeted) + len(regression))
        if deficit > 0:
            broader = [t for t in all_tasks if t not in (set(fresh) | set(targeted) | set(regression))]
            rng.shuffle(broader)
            fresh.extend(broader[:deficit])

    return SampleComposition(fresh=fresh, targeted=targeted, regression=regression)
