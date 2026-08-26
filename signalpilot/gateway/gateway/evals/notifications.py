"""Detect regressions and send optional email notifications.

Compare a completed run with the trailing median for the same evaluation-set reference and build fingerprint.
Record a regression when the decrease exceeds the configured threshold.

Identify a cause only when one knowledge-base entry is the only changed input.
Otherwise, report that the regression coincided with all identified changes.
"""

from __future__ import annotations

import logging
import smtplib
import statistics
from email.message import EmailMessage

from starlette.concurrency import run_in_threadpool

from ..config.evals import get_eval_run_settings
from ..db.engine import get_session_factory
from ..store import evals as evals_store

logger = logging.getLogger(__name__)


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


async def check_regression_and_notify(
    org_id: str, run: dict, tasks: list[dict], accuracy_pct: float
) -> dict | None:
    settings = get_eval_run_settings()
    factory = get_session_factory()

    async with factory() as session:
        baseline = await evals_store.trailing_baseline(
            session,
            org_id=org_id,
            eval_set_ref=run.get("eval_set_ref", ""),
            build_fingerprint=run.get("build_fingerprint", ""),
            before=run["created_at"],
        )
    if not baseline:
        return None  # No comparable run exists for this evaluation set and build.

    # A fingerprint is what makes two runs comparable at all. Without one we
    # cannot tell an agent regression from a warehouse that changed underneath
    # us, so we record nothing rather than send a causal-sounding email.
    if not run.get("build_fingerprint"):
        logger.info(
            "run %s has no build fingerprint — skipping regression attribution", run["id"]
        )
        return None

    baseline_acc = statistics.median(b["accuracy_pct"] for b in baseline)
    drop = baseline_acc - accuracy_pct
    if drop < settings.regression_drop_pct:
        return None

    # Include added, edited, and withdrawn entries in the comparison.
    # Each type of change modifies the agent context.
    latest_baseline_docs = set(baseline[0].get("kb_doc_ids") or [])
    current_docs = set(run.get("kb_doc_ids") or [])
    added = sorted(current_docs - latest_baseline_docs)
    removed = sorted(latest_baseline_docs - current_docs)
    suspected = added + removed
    # Config the operator can change between runs is also a variable; the
    # model and prompt preamble ride on the run row.
    other_changes: list[str] = []
    baseline_meta = baseline[0].get("meta") or {}
    if baseline_meta.get("model") and baseline_meta["model"] != run.get("model"):
        other_changes.append(f"model ({baseline_meta['model']} -> {run.get('model')})")
    if (
        baseline_meta.get("config_hash")
        and run.get("config_hash")
        and baseline_meta["config_hash"] != run["config_hash"]
    ):
        other_changes.append("eval configuration (model, preamble, connection or task cap)")
    sole_change = len(suspected) == 1 and not removed and not other_changes

    flipped = [
        {"task_id": t["task_id"], "title": t["title"], "verdict": t["verdict"]}
        for t in tasks
        if t.get("verdict") not in ("CORRECT", "UNGRADED", None)
    ]

    async with factory() as session:
        cfg = await evals_store.get_config(session, org_id=org_id)
    recipients = [e for e in (cfg.get("notify_emails") or []) if "@" in e]

    entry = {
        "run_id": run["id"],
        "created_at": _now(),
        "baseline_run_ids": [b["run_id"] for b in baseline],
        "baseline_accuracy_pct": round(baseline_acc, 2),
        "run_accuracy_pct": round(accuracy_pct, 2),
        "drop_pct": round(drop, 2),
        "suspected_doc_ids": suspected,
        "sole_change": sole_change,
        "flipped_tasks": flipped[:50],
        "recipients": recipients,
        "notified_at": None,
        "added_doc_ids": added,
        "removed_doc_ids": removed,
        "other_changes": other_changes,
    }

    if recipients:
        try:
            await run_in_threadpool(
                _send_email, settings, recipients, org_id, run, entry, sole_change
            )
            entry["notified_at"] = _now()
        except Exception:
            logger.exception("regression email failed for run %s", run["id"])

    async with factory() as session:
        await evals_store.record_regression(session, org_id=org_id, entry=entry)
    logger.warning(
        "eval regression on org %s run %s: %.1f%% -> %.1f%% (drop %.1f)",
        org_id,
        run["id"],
        baseline_acc,
        accuracy_pct,
        drop,
    )
    return entry


def _send_email(settings, recipients, org_id, run, entry, sole_change) -> None:
    # Identify a cause only when one entry is the only changed input.
    # Report all other cases as coincident changes.
    verb = "caused by" if sole_change else "coincided with"
    suspected = entry["suspected_doc_ids"]
    lines = [
        f"Eval accuracy dropped on run {run['id']}.",
        "",
        f"  baseline (median of {len(entry['baseline_run_ids'])} runs): {entry['baseline_accuracy_pct']}%",
        f"  this run: {entry['run_accuracy_pct']}%",
        f"  drop: {entry['drop_pct']} points",
        "",
        (
            f"The drop {verb} {len(suspected)} knowledge-base "
            f"entr{'y' if len(suspected) == 1 else 'ies'} added since the baseline:"
            if suspected
            else "No knowledge-base entries changed since the baseline — "
            "the drop is NOT attributable to the KB."
        ),
    ]
    lines += [f"  - added: {doc_id}" for doc_id in entry.get("added_doc_ids") or []]
    lines += [f"  - removed: {doc_id}" for doc_id in entry.get("removed_doc_ids") or []]
    if entry.get("other_changes"):
        lines += [
            "",
            "Other things that also changed since the baseline (so this is a "
            "coincidence, not an attribution):",
        ]
        lines += [f"  - {c}" for c in entry["other_changes"]]
    if entry["flipped_tasks"]:
        lines += ["", "Tasks not passing in this run:"]
        lines += [
            f"  - {t['task_id']}: {t['verdict']} ({t['title']})"
            for t in entry["flipped_tasks"][:20]
        ]
    lines += [
        "",
        f"Eval set: {run.get('eval_set_name', '')} @ {run.get('eval_set_ref', '')[:12]}",
        f"Build fingerprint: {run.get('build_fingerprint', '')}",
        "",
        "Open the evals page for the full diff and transcripts.",
    ]

    msg = EmailMessage()
    msg["Subject"] = (
        f"[SignalPilot evals] accuracy dropped "
        f"{entry['baseline_accuracy_pct']}% → {entry['run_accuracy_pct']}%"
    )
    msg["From"] = settings.notify_from
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))

    if settings.smtp_host:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.send_message(msg)
        return

    import boto3

    boto3.client("ses", region_name=settings.s3_region or "us-east-1").send_email(
        Source=settings.notify_from,
        Destination={"ToAddresses": recipients},
        Message={
            "Subject": {"Data": msg["Subject"]},
            "Body": {"Text": {"Data": "\n".join(lines)}},
        },
    )
