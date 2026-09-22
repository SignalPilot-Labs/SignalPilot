"""Eval harness state, scoped by org_id.

Runs, tasks, config, accuracy history and regressions live in Postgres so the
harness works across gateway replicas and survives restarts. Bulky evidence
(transcripts, setup logs, table captures) lives in S3 under
``evals/<org>/runs/<run_id>/``. These rows contain only pointers and summaries.

Accuracy history is immutable and never pruned; everything else is subject to
the retention windows (10 runs of artifacts, 100 runs of traces).
"""

from __future__ import annotations

from .evals_accuracy import (
    append_accuracy,
    delete_trace_rows,
    list_accuracy,
    list_regressions,
    list_task_performance,
    mark_pruned,
    record_regression,
    runs_outside_window,
    trailing_baseline,
)
from .evals_runs import (
    count_runs,
    create_run,
    get_config,
    get_run,
    list_live_runs,
    list_runs,
    list_stale_runs,
    org_ids_with_runs,
    renew_lease,
    run_dict,
    run_exists,
    save_config,
    update_run,
)
from .evals_tasks import (
    cancel_open_tasks,
    get_tasks,
    live_vercel_sandboxes,
    seed_tasks,
    task_dict,
    tasks_with_live_sandboxes,
    update_task,
)

# Retention windows (spec §3.5). Artifacts are heavy (table captures); traces
# are the transcripts + run/task rows. History is forever.
ARTIFACT_RUN_WINDOW = 10
TRACE_RUN_WINDOW = 100

__all__ = [
    "ARTIFACT_RUN_WINDOW",
    "TRACE_RUN_WINDOW",
    "append_accuracy",
    "cancel_open_tasks",
    "count_runs",
    "create_run",
    "delete_trace_rows",
    "get_config",
    "get_run",
    "get_tasks",
    "list_accuracy",
    "list_live_runs",
    "list_regressions",
    "list_runs",
    "list_stale_runs",
    "list_task_performance",
    "live_vercel_sandboxes",
    "mark_pruned",
    "org_ids_with_runs",
    "record_regression",
    "renew_lease",
    "run_dict",
    "run_exists",
    "runs_outside_window",
    "save_config",
    "seed_tasks",
    "task_dict",
    "tasks_with_live_sandboxes",
    "trailing_baseline",
    "update_run",
    "update_task",
]
