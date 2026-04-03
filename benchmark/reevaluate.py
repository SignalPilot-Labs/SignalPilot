"""
Re-evaluate all existing benchmark results against gold CSVs.

For each instance_id seen across all run JSON files, pick the BEST
predicted_rows (most rows, tie-broken by most-recent run), then run
evaluate_task() against the gold CSV(s) and report which tasks flip
and what the final accuracy is.

Run with:
    python -m benchmark.reevaluate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from benchmark.config import SPIDER2_EVAL_CONFIG, SPIDER2_GOLD_EXEC
from benchmark.eval import evaluate_task, load_eval_config, load_gold_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_result_files() -> list[Path]:
    """Return all JSON result files sorted oldest-first (by filename/run_id)."""
    results_dir = Path("/bench/results")
    if not results_dir.exists():
        print(f"[ERROR] Results directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)
    files = sorted(results_dir.glob("*.json"))
    if not files:
        print("[ERROR] No JSON result files found in /bench/results/", file=sys.stderr)
        sys.exit(1)
    return files


def _gold_paths_for(instance_id: str, gold_dir: Path) -> list[Path]:
    """
    Resolve gold CSV path(s) for an instance.

    Checks for:
      {gold_dir}/{instance_id}.csv               (plain)
      {gold_dir}/{instance_id}_a.csv, _b.csv … (variants)
    Returns an empty list when no gold file exists.
    """
    plain = gold_dir / f"{instance_id}.csv"
    if plain.exists():
        return [plain]

    variants: list[Path] = []
    suffix = "a"
    while True:
        candidate = gold_dir / f"{instance_id}_{suffix}.csv"
        if not candidate.exists():
            break
        variants.append(candidate)
        suffix = chr(ord(suffix) + 1)

    return variants


# ---------------------------------------------------------------------------
# Candidate selection: pick the BEST predicted_rows per instance
# ---------------------------------------------------------------------------

def _collect_candidates(
    files: list[Path],
) -> dict[str, dict[str, Any]]:
    """
    Scan every result file and, for each instance_id, keep the candidate with
    the most predicted rows.  Ties are broken by taking the more-recent file
    (files are sorted oldest-first, so later entries naturally overwrite).

    Returns a mapping:
        instance_id -> {
            "predicted_rows": [...],
            "was_correct":    bool,   # as stored in original run
            "run_id":         str,
            "source_file":    str,
        }
    """
    best: dict[str, dict[str, Any]] = {}

    for path in files:
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[WARN] Could not read {path.name}: {exc}", file=sys.stderr)
            continue

        run_id = data.get("run_id", path.stem)
        results = data.get("results", [])
        if not isinstance(results, list):
            continue

        for entry in results:
            iid = entry.get("instance_id", "")
            if not iid:
                continue

            predicted_rows: list[dict] = entry.get("predicted_rows") or []
            # Skip entries with no rows (errors / no-SQL-produced tasks)
            if not predicted_rows:
                continue

            existing = best.get(iid)
            if existing is None or len(predicted_rows) > len(existing["predicted_rows"]):
                best[iid] = {
                    "predicted_rows": predicted_rows,
                    "was_correct": entry.get("correct", False),
                    "run_id": run_id,
                    "source_file": path.name,
                }

    return best


# ---------------------------------------------------------------------------
# Main re-evaluation logic
# ---------------------------------------------------------------------------

def reevaluate() -> None:
    files = _collect_result_files()
    print(f"Scanning {len(files)} result file(s)…\n")

    candidates = _collect_candidates(files)
    if not candidates:
        print("No tasks with predicted_rows found across all result files.")
        return

    eval_config_map = load_eval_config(SPIDER2_EVAL_CONFIG)
    gold_dir = SPIDER2_GOLD_EXEC

    total = 0
    now_correct = 0
    flips: list[str] = []  # lines describing flip events

    for instance_id, info in sorted(candidates.items()):
        gold_paths = _gold_paths_for(instance_id, gold_dir)
        if not gold_paths:
            print(f"  [SKIP] {instance_id}: no gold CSV found")
            continue

        predicted_rows: list[dict] = info["predicted_rows"]
        was_correct: bool = info["was_correct"]
        run_id: str = info["run_id"]

        eval_cfg = eval_config_map.get(instance_id)
        is_correct = evaluate_task(
            instance_id=instance_id,
            predicted_rows=predicted_rows,
            gold_csv_path=gold_paths,
            eval_config=eval_cfg,
        )

        total += 1
        if is_correct:
            now_correct += 1

        if is_correct != was_correct:
            direction = "WRONG -> CORRECT" if is_correct else "CORRECT -> WRONG"
            flips.append(
                f"  {direction:20s}  {instance_id:<20s}  (run: {run_id}, rows: {len(predicted_rows)})"
            )

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------
    print("=" * 70)
    if flips:
        print(f"Tasks that FLIPPED ({len(flips)}):\n")
        for line in flips:
            print(line)
        print()
    else:
        print("No tasks flipped (re-evaluation agrees with stored results).\n")

    if total == 0:
        print("No evaluable tasks found (all lacked gold CSVs).")
        return

    accuracy = now_correct / total * 100
    print("=" * 70)
    print(f"Re-evaluated tasks : {total}")
    print(f"Correct            : {now_correct}")
    print(f"Incorrect          : {total - now_correct}")
    print(f"Execution accuracy : {accuracy:.2f}%")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    reevaluate()
