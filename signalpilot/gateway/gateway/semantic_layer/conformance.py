"""Metric conformance engine: same metric through the warehouse-native
semantic layer AND the agent-built model, diff the numbers per group.

The model table is assumed to be aggregated at the requested dimension grain
(a mart row per group) — the standard shape of an agent-built metric mart.
Duplicate keys on the model side therefore mean the model is NOT at grain,
which is itself a failure (`duplicate_in_model`), not something to overwrite.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from decimal import Decimal

DEFAULT_REL_TOLERANCE = 0.005  # 0.5% relative drift


def _norm_scalar(v) -> str:
    """Normalize one dimension value for cross-system alignment."""
    if v is None:
        return "\x00null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, Decimal)):
        f = float(v)
        if math.isnan(f):
            return "\x00nan"
        return str(int(f)) if f.is_integer() else format(f, ".10g")
    if isinstance(v, _dt.datetime):
        # midnight datetimes align with plain dates
        if v.time() == _dt.time.min:
            return v.date().isoformat()
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    return str(v).strip().lower()


def _norm_key(values: tuple) -> tuple:
    return tuple(_norm_scalar(v) for v in values)


def _as_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _is_nan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


@dataclass
class GroupDiff:
    key: tuple
    reference: float | None
    model: float | None
    abs_diff: float | None = None
    rel_diff: float | None = None
    # match | drift | missing_in_model | missing_in_reference | non_numeric | duplicate_in_model
    status: str = "match"


@dataclass
class ConformanceReport:
    metric: str
    dimensions: list[str]
    tolerance: float
    groups: list[GroupDiff] = field(default_factory=list)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.groups:
            # nothing to compare is not a pass — surface loudly
            return "warn"
        if any(
            g.status in ("drift", "missing_in_model", "missing_in_reference", "duplicate_in_model")
            for g in self.groups
        ):
            return "fail"
        if any(g.status == "non_numeric" for g in self.groups) or self.truncated:
            return "warn"
        return "pass"

    @property
    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for g in self.groups:
            by_status[g.status] = by_status.get(g.status, 0) + 1
        finite = [g for g in self.groups if g.rel_diff is not None and math.isfinite(g.rel_diff)]
        worst = max(finite, key=lambda g: abs(g.rel_diff), default=None)
        infinite_drift = sum(1 for g in self.groups if g.rel_diff is not None and math.isinf(g.rel_diff))
        return {
            "verdict": self.verdict,
            "groups": len(self.groups),
            "by_status": by_status,
            # JSON-safe: inf drift reported via count, not a float
            "worst_rel_diff": worst.rel_diff if worst else None,
            "worst_group": list(worst.key) if worst else None,
            "groups_with_infinite_drift": infinite_drift,
            "tolerance": self.tolerance,
            "truncated": self.truncated,
            "notes": self.notes,
        }


def compare_metric(
    *,
    metric: str,
    dimensions: list[str],
    reference_rows: list[dict],
    model_rows: list[dict],
    reference_metric_col: str,
    model_metric_col: str,
    reference_dim_cols: list[str],
    model_dim_cols: list[str],
    tolerance: float = DEFAULT_REL_TOLERANCE,
    max_groups: int = 5000,
) -> ConformanceReport:
    """Align rows by normalized dimension key and diff the metric values."""
    if len(reference_dim_cols) != len(dimensions) or len(model_dim_cols) != len(dimensions):
        raise ValueError("dimension column lists must match the dimensions list length")

    def _index(rows: list[dict], dim_cols: list[str], metric_col: str):
        out: dict[tuple, object] = {}
        dups: set[tuple] = set()
        for r in rows:
            # column lookup is case-insensitive: warehouses disagree on case
            lower = {str(k).lower(): v for k, v in r.items()}
            key = _norm_key(tuple(lower.get(c.lower()) for c in dim_cols))
            if key in out:
                dups.add(key)
            out[key] = lower.get(metric_col.lower())
        return out, dups

    ref, ref_dups = _index(reference_rows, reference_dim_cols, reference_metric_col)
    mod, mod_dups = _index(model_rows, model_dim_cols, model_metric_col)

    report = ConformanceReport(metric=metric, dimensions=dimensions, tolerance=tolerance)
    if not reference_rows:
        report.notes.append("semantic layer returned no rows — nothing to verify against")
    if not model_rows:
        report.notes.append("model table returned no rows")

    all_keys = sorted(set(ref) | set(mod))
    if len(all_keys) > max_groups:
        report.truncated = True
        report.notes.append(f"compared first {max_groups} of {len(all_keys)} groups")
        all_keys = all_keys[:max_groups]

    for key in all_keys:
        r_raw, m_raw = ref.get(key), mod.get(key)
        g = GroupDiff(key=key, reference=_as_float(r_raw), model=_as_float(m_raw))
        if key in mod_dups:
            # model not aggregated at the requested grain — a defect on its own
            g.status = "duplicate_in_model"
        elif key not in mod:
            g.status = "missing_in_model"
        elif key not in ref:
            g.status = "missing_in_reference"
        elif _is_nan(r_raw) or _is_nan(m_raw):
            g.status = "non_numeric"
        elif g.reference is None or g.model is None:
            # both present but at least one non-numeric — only a warn if raw
            # values also differ as strings
            g.status = "match" if str(r_raw) == str(m_raw) else "non_numeric"
        else:
            g.abs_diff = g.model - g.reference
            base = abs(g.reference)
            g.rel_diff = (g.abs_diff / base) if base > 0 else (0.0 if g.abs_diff == 0 else math.inf)
            g.status = "match" if abs(g.rel_diff) <= tolerance else "drift"
        report.groups.append(g)
    if ref_dups:
        report.notes.append(f"{len(ref_dups)} duplicate group key(s) in the semantic-layer result")
    return report


def render_conformance_markdown(report: ConformanceReport, *, source_name: str, model_name: str) -> str:
    s = report.summary
    emoji = {"pass": "✅", "warn": "⚠️", "fail": "❌"}[report.verdict]
    lines = [
        f"## {emoji} MetricProof — `{report.metric}` vs `{source_name}`",
        "",
        f"Model `{model_name}` checked against the warehouse-native semantic layer "
        f"across {s['groups']} group(s) of ({', '.join(report.dimensions) or 'total'}).",
        f"Tolerance ±{report.tolerance * 100:.2f}% · verdict **{report.verdict}**.",
        "",
    ]
    for note in report.notes:
        lines.append(f"> {note}")
    bad = [g for g in report.groups if g.status != "match"]
    if bad:
        lines += ["", "| Group | Semantic layer | Model | Δ | Status |", "|---|---:|---:|---:|---|"]
        for g in bad[:25]:
            key = ", ".join(str(k).replace("\x00null", "∅") for k in g.key) or "(total)"
            rel = (
                f"{g.rel_diff * 100:+.2f}%"
                if g.rel_diff is not None and math.isfinite(g.rel_diff)
                else "∞" if g.rel_diff is not None else "—"
            )
            ref = f"{g.reference:,.2f}" if g.reference is not None else "—"
            mod = f"{g.model:,.2f}" if g.model is not None else "—"
            lines.append(f"| {key} | {ref} | {mod} | {rel} | {g.status} |")
        if len(bad) > 25:
            lines.append(f"| … {len(bad) - 25} more | | | | |")
    elif report.groups:
        lines.append("All groups agree within tolerance.")
    return "\n".join(lines)
