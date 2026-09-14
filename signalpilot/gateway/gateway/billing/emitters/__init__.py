"""Credit emitters, one module per metered unit.

``queries``    governed executions (query_executor, runtime_datasets)
``threads``    chat run finalizer (store.standalone_chat.lifecycle)
``eval_runs``  eval run reaching ``running`` (store.evals.update_run)
``tokens``     agent cost per chat run (store.standalone_chat.worker)
``daily``      model_day + seat_day snapshot (background.loops)
``returns``    thread reversals (feedback path, when it lands)

Every public function is a no-op in local mode, idempotent, and never raises.
"""

from __future__ import annotations

from .daily import run_credit_daily_snapshot, snapshot_org
from .eval_runs import emit_eval_run_credit
from .queries import emit_query_credit
from .returns import return_thread
from .threads import emit_thread_credit
from .tokens import emit_token_credit

__all__ = [
    "emit_eval_run_credit",
    "emit_query_credit",
    "emit_thread_credit",
    "emit_token_credit",
    "return_thread",
    "run_credit_daily_snapshot",
    "snapshot_org",
]
