"use client";

/** Collapsible, filterable list of eval runs. */

import { useMemo, useState } from "react";
import { FlaskConical, Search, X } from "lucide-react";
import { type EvalRun } from "~/lib/api";
import { StatusDot } from "./badges";

const RUNS_COLLAPSED = 8;

export function RunsList({ runs, selectedRun, onSelect }: { runs: EvalRun[]; selectedRun: string | null; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return runs;
    return runs.filter(
      (r) =>
        r.id.toLowerCase().includes(needle) ||
        r.doc_titles.some((t) => t.toLowerCase().includes(needle)) ||
        r.doc_ids.some((t) => t.toLowerCase().includes(needle)) ||
        (r.trigger ?? "").includes(needle) ||
        r.status.includes(needle),
    );
  }, [runs, query]);

  const visible = showAll || query ? filtered : filtered.slice(0, RUNS_COLLAPSED);
  const hidden = filtered.length - visible.length;

  return (
    <div className="ev-card p-5">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
          Runs{runs.length > 0 && <span className="ml-1.5 normal-case tracking-normal text-[var(--color-text-dim)]">{runs.length}</span>}
        </h2>
        {runs.length > RUNS_COLLAPSED && (
          <div className="ev-search ev-search--sm">
            <Search className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter runs…" aria-label="filter runs" />
            {query && (
              <button onClick={() => setQuery("")} aria-label="clear filter" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        )}
      </div>
      {runs.length === 0 ? (
        <p className="text-sm text-[var(--color-text-dim)] flex items-center gap-2">
          <FlaskConical className="w-4 h-4" strokeWidth={1.5} />
          No runs yet — open a pending knowledge entry and click “Evaluate Change”.
        </p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-[var(--color-text-dim)]">no runs match “{query}”</p>
      ) : (
        <>
          <div className="divide-y divide-[var(--color-border)]">
            {visible.map((r) => {
              const s = r.summary ?? {};
              return (
                <button
                  key={r.id}
                  onClick={() => onSelect(r.id)}
                  className={`w-full flex items-center justify-between py-2.5 px-2 rounded-[10px] text-left hover:bg-[var(--color-bg)] transition-colors duration-150 ${selectedRun === r.id ? "bg-[var(--color-bg)]" : ""}`}
                >
                  <div className="min-w-0 flex items-baseline gap-3">
                    <code className="text-sm text-[var(--color-text)] whitespace-nowrap">{r.id}</code>
                    {r.trigger && <span className="ev-badge flex-shrink-0">{r.trigger}</span>}
                    <p className="text-xs text-[var(--color-text-muted)] truncate">
                      {r.doc_titles.join(", ") || r.doc_ids.join(", ") || "whole set"}
                    </p>
                  </div>
                  <div className="flex items-center gap-4 flex-shrink-0 ml-4">
                    {r.status === "completed" && (
                      <span className="text-xs text-[var(--color-text-muted)] tabular-nums">{s.correct ?? 0}/{s.total ?? 0} correct</span>
                    )}
                    <StatusDot status={r.status} />
                  </div>
                </button>
              );
            })}
          </div>
          {hidden > 0 && (
            <button
              onClick={() => setShowAll(true)}
              className="mt-2 w-full py-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            >
              Show all {filtered.length} runs
            </button>
          )}
          {showAll && !query && filtered.length > RUNS_COLLAPSED && (
            <button
              onClick={() => setShowAll(false)}
              className="mt-2 w-full py-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            >
              Show recent only
            </button>
          )}
        </>
      )}
    </div>
  );
}
