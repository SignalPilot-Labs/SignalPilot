"use client";

import { useMemo, useState } from "react";
import type { KnowledgeDoc, RetrievalDocStats } from "~/lib/types";
import { useKnowledgeRetrievals } from "~/lib/hooks/use-gateway-data";
import { CATEGORY_META } from "./categories";
import { daysAgo, scopeLabel } from "./shared";
import { KbIcon } from "./icons";

const RANGES = [7, 30, 90] as const;
type Range = (typeof RANGES)[number];

const SOURCE_LABEL: Record<string, string> = {
  get_knowledge_baseline: "baseline load",
  get_knowledge_task: "task match",
  search_knowledge: "search",
  read_knowledge: "read",
};

/** Mint heat cell: opacity scales with count relative to the row max. */
function HeatCell({ count, max, title }: { count: number; max: number; title: string }) {
  const intensity = count === 0 ? 0 : 0.18 + 0.82 * Math.sqrt(count / Math.max(1, max));
  return (
    <span
      className="kb-heat-cell"
      title={title}
      style={{
        background:
          count === 0
            ? "rgba(255,255,255,0.045)"
            : `color-mix(in srgb, var(--color-success, #00ff88) ${Math.round(intensity * 100)}%, transparent)`,
      }}
    />
  );
}

function SourceChips({ bySource }: { bySource: Record<string, number> }) {
  return (
    <span className="kb-heat-sources">
      {Object.entries(bySource)
        .sort((a, b) => b[1] - a[1])
        .map(([src, n]) => (
          <span key={src} className="kb-heat-srcchip" title={`${SOURCE_LABEL[src] ?? src}: ${n}`}>
            {SOURCE_LABEL[src] ?? src} {n}
          </span>
        ))}
    </span>
  );
}

/** Merge a daily series into at most maxCells buckets so wide ranges fit. */
function compressSeries(series: number[], maxCells = 32): { cells: number[]; daysPerCell: number } {
  if (series.length <= maxCells) return { cells: series, daysPerCell: 1 };
  const daysPerCell = Math.ceil(series.length / maxCells);
  const cells: number[] = [];
  for (let i = 0; i < series.length; i += daysPerCell) {
    cells.push(series.slice(i, i + daysPerCell).reduce((a, b) => a + b, 0));
  }
  return { cells, daysPerCell };
}

export function RetrievalHeatmap({
  docs,
  onSelect,
}: {
  docs: KnowledgeDoc[];
  onSelect: (id: string) => void;
}) {
  const [range, setRange] = useState<Range>(30);
  const { data, isLoading, error } = useKnowledgeRetrievals(range);

  const docById = useMemo(() => new Map(docs.map((d) => [d.id, d])), [docs]);

  const { rows, cold, fresh, totalPulls, globalMax } = useMemo(() => {
    // Until data arrives, derive nothing — otherwise every doc flashes "cold"
    // on first load and on each range switch (each range is a new SWR key).
    if (!data) return { rows: [], cold: [], fresh: [], totalPulls: 0, globalMax: 1 };
    const stats: RetrievalDocStats[] = data.docs;
    // Rows: retrieved docs that still exist and are active, hottest first.
    const rows = stats
      .map((s) => ({ stats: s, doc: docById.get(s.doc_id) }))
      .filter((r): r is { stats: RetrievalDocStats; doc: KnowledgeDoc } => !!r.doc)
      .sort((a, b) => b.stats.total - a.stats.total);
    const retrievedIds = new Set(stats.map((s) => s.doc_id));
    const windowStart = Date.now() / 1000 - range * 86400;
    const notRetrieved = docs.filter((d) => !retrievedIds.has(d.id));
    // Docs created inside the window haven't had a fair chance — not "stale".
    const fresh = notRetrieved.filter((d) => d.created_at >= windowStart);
    const cold = notRetrieved
      .filter((d) => d.created_at < windowStart)
      .sort((a, b) => a.updated_at - b.updated_at);
    // Count only pulls of docs shown as rows so header and table agree
    // (events for since-archived docs are excluded both places).
    const totalPulls = rows.reduce((acc, r) => acc + r.stats.total, 0);
    const globalMax = Math.max(1, ...rows.flatMap((r) => r.stats.series));
    return { rows, cold, fresh, totalPulls, globalMax };
  }, [data, docs, docById, range]);

  return (
    <div className="kb-heat-root">
      <div className="kb-heat-bar">
        <div className="kb-list-title">
          <KbIcon name="pull" size={17} style={{ color: "var(--color-success)" }} />
          <span className="tx">Retrieval heat</span>
          <span className="c">
            {totalPulls} pull{totalPulls === 1 ? "" : "s"} · {rows.length} doc{rows.length === 1 ? "" : "s"} · last {range}d
          </span>
        </div>
        <div className="kb-heat-ranges">
          {RANGES.map((r) => (
            <button key={r} className={range === r ? "sel" : ""} onClick={() => setRange(r)}>
              {r}d
            </button>
          ))}
        </div>
      </div>
      <div className="kb-list-subtitle" style={{ padding: "0 14px 10px" }}>
        Which docs agents actually pull — baseline loads, task matches, searches, and reads.
        Human browsing is not counted.
      </div>

      <div className="kb-heat-scroll">
        {error ? (
          <div className="kb-list-empty">
            Could not load retrieval data — {error instanceof Error ? error.message : "request failed"}.
          </div>
        ) : !data ? (
          <div className="kb-list-empty">loading retrieval data…</div>
        ) : rows.length === 0 ? (
          <div className="kb-list-empty">
            No agent retrievals in the last {range} days. Once agents call get_knowledge or
            search_knowledge, usage lands here.
          </div>
        ) : (
          <div className="kb-heat-table">
            {rows.map(({ stats, doc }) => {
              const { cells, daysPerCell } = compressSeries(stats.series);
              return (
              <button key={doc.id} className="kb-heat-row" onClick={() => onSelect(doc.id)}>
                <span className="catdot" style={{ background: CATEGORY_META[doc.category].color }} title={doc.category} />
                <span className="kb-heat-title" title={doc.title}>
                  {doc.title}
                </span>
                <span className="kb-heat-scope">{scopeLabel(doc)}</span>
                <span className="kb-heat-grid" aria-label="pulls over time, oldest to newest">
                  {cells.map((n, i) => {
                    const endAgo = (cells.length - 1 - i) * daysPerCell;
                    const when =
                      daysPerCell === 1
                        ? endAgo === 0 ? "today" : `${endAgo}d ago`
                        : `${endAgo}–${endAgo + daysPerCell - 1}d ago`;
                    return (
                      <HeatCell key={i} count={n} max={globalMax * daysPerCell}
                        title={`${n} pull${n === 1 ? "" : "s"}, ${when}`} />
                    );
                  })}
                </span>
                <span className="kb-heat-total" title="total pulls in window">
                  {stats.total}
                </span>
                <SourceChips bySource={stats.by_source} />
                <span className="kb-heat-last">
                  {stats.last_retrieved_at ? daysAgo(stats.last_retrieved_at) : "—"}
                </span>
              </button>
              );
            })}
          </div>
        )}

        {data && cold.length > 0 && (
          <div className="kb-heat-coldsec">
            <div className="kb-heat-coldhead">
              <KbIcon name="slash" size={13} />
              Not pulled in {range} days
              <span className="c">{cold.length}</span>
            </div>
            <div className="kb-heat-coldlist">
              {cold.map((d) => (
                <button key={d.id} className="kb-heat-coldchip" onClick={() => onSelect(d.id)} title={d.title}>
                  <span className="catdot" style={{ background: CATEGORY_META[d.category].color }} />
                  {d.title}
                  <span className="age">{daysAgo(d.updated_at)}</span>
                </button>
              ))}
            </div>
            <div className="kb-heat-coldnote">
              Stale candidates — consider updating, merging, or archiving docs agents never use.
              {fresh.length > 0 && (
                <> {fresh.length} newer doc{fresh.length === 1 ? "" : "s"} created inside this window
                {" "}{fresh.length === 1 ? "is" : "are"} not counted.</>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
