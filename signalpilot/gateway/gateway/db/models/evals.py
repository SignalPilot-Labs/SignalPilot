"""Define evaluation harness and improvement run models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase, TZDateTime

# Evaluation harness state.
# Retention windows remove run and task details.
# Accuracy history is the permanent record for the accuracy page.
# S3 stores transcripts, setup logs, and captures under evals/<org>/runs/<run_id>/.


class GatewayEvalConfig(GatewayBase):
    """Store the evaluation harness configuration for one organization."""

    __tablename__ = "gateway_eval_configs"

    org_id: Mapped[str] = mapped_column(String, primary_key=True)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    repo_installation_id: Mapped[str | None] = mapped_column(String(64))
    repo_id: Mapped[int | None] = mapped_column(BigInteger)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="sonnet")
    max_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_preamble: Mapped[str] = mapped_column(Text, nullable=False, default="")
    connection: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    autorun_on_knowledge_add: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Opt-in regression notifications (spec §3.7). Empty list = nobody opted in.
    notify_emails: Mapped[list | None] = mapped_column(JSON)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class GatewayEvalRun(GatewayBase):
    """Store one evaluation harness run.

    Retention removes detail rows after the trace window.
    gateway_eval_accuracy_history stores the permanent record.
    """

    __tablename__ = "gateway_eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preparing")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(40))
    doc_ids: Mapped[list | None] = mapped_column(JSON)
    doc_titles: Mapped[list | None] = mapped_column(JSON)
    task_filter: Mapped[list | None] = mapped_column(JSON)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    eval_set_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Exact references support regression attribution.
    # A notification identifies a cause only when all other inputs are unchanged.
    eval_set_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    project_repo: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    project_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    build_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    kb_doc_ids: Mapped[list | None] = mapped_column(JSON)
    summary: Mapped[dict | None] = mapped_column(JSON)
    progress: Mapped[dict | None] = mapped_column(JSON)
    coverage: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    artifact_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    artifacts_pruned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    traces_pruned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A live run refreshes the heartbeat lease.
    # Startup recovery and the reaper classify a run with an expired lease as inactive.
    # This classification releases credentials and branches after an interrupted gateway process.
    lease_expires_at: Mapped[float | None] = mapped_column(Float)
    api_key_id: Mapped[str | None] = mapped_column(String)
    # This hash contains the model, preamble, connection, and task limit.
    # Two runs must have the same hash for regression attribution.
    config_hash: Mapped[str | None] = mapped_column(String(40))

    __table_args__ = (
        Index("ix_gw_evalrun_org_created", "org_id", "created_at"),
        Index("ix_gw_evalrun_org_status", "org_id", "status"),
    )


class GatewayEvalRunTask(GatewayBase):
    """One task inside a run (read-only analytics question or write task)."""

    __tablename__ = "gateway_eval_run_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="query")
    task_class: Mapped[str] = mapped_column(String(10), nullable=False, default="read")
    gt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    checks: Mapped[list | None] = mapped_column(JSON)
    grade: Mapped[dict | None] = mapped_column(JSON)
    covers: Mapped[list | None] = mapped_column(JSON)
    builds: Mapped[list | None] = mapped_column(JSON)
    capture_spec: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    verdict: Mapped[str | None] = mapped_column(String(20))
    check_results: Mapped[list | None] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[str | None] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))
    sandbox: Mapped[dict | None] = mapped_column(JSON)
    branch_name: Mapped[str | None] = mapped_column(String(120))
    capture_result: Mapped[dict | None] = mapped_column(JSON)
    observed_tables: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("run_id", "task_id", name="uq_gw_evaltask_run_task"),
        Index("ix_gw_evaltask_org_run", "org_id", "run_id"),
    )


class GatewayEvalAccuracyHistory(GatewayBase):
    """Store one immutable accuracy record for each completed run.

    Retention does not remove this record.
    """

    __tablename__ = "gateway_eval_accuracy_history"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    eval_set_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    eval_set_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    build_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    tasks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tasks_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    coverage_pct: Mapped[float | None] = mapped_column(Float)
    kb_doc_ids: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("org_id", "run_id", name="uq_gw_evalacc_org_run"),
        Index("ix_gw_evalacc_org_created", "org_id", "created_at"),
    )


class GatewayEvalRegression(GatewayBase):
    """A detected accuracy drop, attributed (carefully) to KB changes."""

    __tablename__ = "gateway_eval_regressions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    baseline_run_ids: Mapped[list | None] = mapped_column(JSON)
    baseline_accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    drop_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # "Coincided with", not "caused by", unless sole_change is true.
    suspected_doc_ids: Mapped[list | None] = mapped_column(JSON)
    sole_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flipped_tasks: Mapped[list | None] = mapped_column(JSON)
    notified_at: Mapped[str | None] = mapped_column(String(40))
    recipients: Mapped[list | None] = mapped_column(JSON)
    # These fields identify all differences between the baseline and this run.
    # suspected_doc_ids contains both added and removed identifiers.
    # other_changes contains model and prompt configuration differences.
    added_doc_ids: Mapped[list | None] = mapped_column(JSON)
    removed_doc_ids: Mapped[list | None] = mapped_column(JSON)
    other_changes: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_gw_evalreg_org_created", "org_id", "created_at"),)


# Automated improvement runs.


class GatewayImprovementRun(GatewayBase):
    """One system-initiated improvement run attempt per org per ET calendar day.

    A row is written for every consumed day slot — seeded, skipped (no eligible
    project), or failed — so the (org_id, started_et_date) uniqueness makes
    double-fires impossible even across processes.
    """

    __tablename__ = "gateway_improvement_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", server_default="queued")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled", server_default="scheduled")
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    # The America/New_York calendar date (YYYY-MM-DD) this run counts for.
    # ET calendar day ("2026-08-11") for nightly slots; manual triggers use a
    # longer unique tag so they never consume the nightly slot.
    started_et_date: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "started_et_date", name="uq_gw_improvement_org_day"),
        Index("ix_gw_improvement_org_created", "org_id", "created_at"),
    )
