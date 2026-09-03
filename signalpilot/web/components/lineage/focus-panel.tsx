"use client";

/**
 * Left panel while a model is focused. Two tabs:
 *  - Lineage: the cone grouped by stage, clickable to select on the canvas;
 *  - Raw tables: deduplicated raw sources feeding the model, with path
 *    counts, a declared-source hygiene tag, and path highlighting on hover.
 */

import { Check, Copy } from "lucide-react";
import React, { useMemo, useState } from "react";

import { LAYER_COLOR, matGlyph } from "./palette";
import type { ParsedMap } from "./parse-map";
import { lineageCone } from "./parse-map";
import { rawSourcesFor, stageColumns } from "./lineage-nav";

export type FocusTab = "lineage" | "raw";

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-[7px] px-2.5 py-1 text-[10px] uppercase tracking-[0.1em] transition-colors ${
        active
          ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
          : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
      }`}
    >
      {children}
    </button>
  );
}

export function FocusPanel({
  parsed,
  focusId,
  tab,
  selectedId,
  onTabChange,
  onSelect,
  onHighlightSource,
}: {
  parsed: ParsedMap;
  focusId: string;
  tab: FocusTab;
  selectedId: string | null;
  onTabChange: (tab: FocusTab) => void;
  onSelect: (id: string) => void;
  /** Hover/selection of a raw table -> highlight its path(s) on the canvas. */
  onHighlightSource: (sourceId: string | null) => void;
}) {
  const focus = parsed.models.get(focusId);
  const cone = useMemo(() => lineageCone(parsed, focusId), [parsed, focusId]);
  const staged = useMemo(() => stageColumns(parsed, cone), [parsed, cone]);
  const raw = useMemo(() => rawSourcesFor(parsed, focusId), [parsed, focusId]);
  // When every row shares one path count the badge column carries no signal —
  // collapse it into the header and show per-row badges only when they differ.
  const uniformPathCount = useMemo(() => {
    if (raw.rows.length === 0) return null;
    const first = raw.rows[0].pathCount;
    return raw.rows.every((r) => r.pathCount === first) ? first : null;
  }, [raw.rows]);
  const [pinnedSource, setPinnedSource] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const copyList = () => {
    const text = raw.rows
      .map((r) => [parsed.models.get(r.id)?.database, parsed.models.get(r.id)?.schema, r.name].filter(Boolean).join("."))
      .join("\n");
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const pinSource = (id: string) => {
    const next = pinnedSource === id ? null : id;
    setPinnedSource(next);
    onHighlightSource(next);
  };

  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-card)]/60">
      <div className="flex items-center gap-1 border-b border-[var(--color-border)] px-2 py-1.5">
        <TabButton active={tab === "lineage"} onClick={() => onTabChange("lineage")}>
          lineage
        </TabButton>
        <TabButton active={tab === "raw"} onClick={() => onTabChange("raw")}>
          raw tables
        </TabButton>
      </div>

      {tab === "lineage" ? (
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {staged.stages.map((stage) => (
            <div key={stage.label}>
              <div className="flex items-baseline gap-2 px-3 pb-0.5 pt-2">
                <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
                  {stage.label}
                </span>
                <span className="font-mono text-[9px] tabular-nums text-[var(--color-text-dim)]">
                  {stage.ids.length}
                </span>
              </div>
              {stage.ids.map((id) => {
                const m = parsed.models.get(id)!;
                const active = id === selectedId;
                const isFocus = id === focusId;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onSelect(id)}
                    className={`flex w-full items-center gap-1.5 py-[3px] pl-4 pr-2 text-left font-mono text-[11px] leading-tight transition-colors ${
                      active
                        ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                        : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]/60 hover:text-[var(--color-text)]"
                    }`}
                  >
                    <span className="w-3 shrink-0 text-center text-[9px]" style={{ color: LAYER_COLOR[m.layer] }} aria-hidden="true">
                      {matGlyph(m.materialized, m.layer)}
                    </span>
                    <span className={`truncate ${isFocus ? "font-bold text-[var(--color-text)]" : ""}`}>{m.name}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
            <span className="min-w-0 text-[9px] leading-4 text-[var(--color-text-dim)]">
              {raw.rows.length === 0
                ? "no raw tables"
                : `${raw.rows.length} table${raw.rows.length === 1 ? "" : "s"} feed${raw.rows.length === 1 ? "s" : ""} ${focus?.name ?? "this model"}`}
              {raw.rows.length > 1 && uniformPathCount !== null && uniformPathCount > 1 && (
                <span
                  className="block"
                  title={`every table reaches ${focus?.name ?? "the model"} through ${uniformPathCount} distinct dependency paths`}
                >
                  each by {uniformPathCount} paths
                </span>
              )}
            </span>
            {raw.rows.length > 0 && (
              <button
                type="button"
                onClick={copyList}
                className="flex items-center gap-1 rounded-[6px] border border-[var(--color-border)] px-1.5 py-0.5 text-[9px] text-[var(--color-text-dim)] transition-colors hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
              >
                {copied ? (
                  <>
                    <Check className="h-2.5 w-2.5 text-[var(--color-success)]" />
                    <span className="text-[var(--color-success)]">copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-2.5 w-2.5" />
                    copy list
                  </>
                )}
              </button>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto py-1" onMouseLeave={() => onHighlightSource(pinnedSource)}>
            {raw.rows.length === 0 ? (
              <div className="px-3 py-6 text-center">
                <p className="text-[11px] leading-5 text-[var(--color-text-muted)]">
                  No raw source tables feed this model directly.
                </p>
                {raw.buildsOn.length > 0 && (
                  <div className="mt-3 text-left">
                    <div className="mb-1 text-[9px] uppercase tracking-[0.12em] text-[var(--color-text-dim)]">
                      it builds on
                    </div>
                    {raw.buildsOn.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => onSelect(m.id)}
                        className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left font-mono text-[11px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                      >
                        <span className="h-1.5 w-1.5 shrink-0 rounded-[2px]" style={{ background: LAYER_COLOR[m.layer] }} aria-hidden="true" />
                        <span className="truncate">{m.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              raw.rows.map((row) => {
                const pinned = pinnedSource === row.id;
                return (
                  <button
                    key={row.id}
                    type="button"
                    onClick={() => pinSource(row.id)}
                    onMouseEnter={() => onHighlightSource(row.id)}
                    aria-pressed={pinned}
                    className={`block w-full border-l-2 px-3 py-2 text-left transition-colors ${
                      pinned
                        ? "border-l-[var(--color-border-active)] bg-[var(--color-bg-hover)]"
                        : "border-l-transparent hover:bg-[var(--color-bg-hover)]/60"
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-[2px]" style={{ background: LAYER_COLOR.source }} aria-hidden="true" />
                      <span className="truncate font-mono text-[11px] font-semibold text-[var(--color-text)]">
                        {row.name}
                      </span>
                      {uniformPathCount === null && (
                        <span
                          className="ml-auto shrink-0 rounded-[4px] border border-[var(--color-border)] px-1 py-0.5 font-mono text-[9px] tabular-nums text-[var(--color-text-dim)]"
                          title={`reaches ${focus?.name ?? "the model"} through ${row.pathCount} distinct dependency path${row.pathCount === 1 ? "" : "s"}`}
                        >
                          {row.pathCount} path{row.pathCount === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate pl-3 font-mono text-[9px] text-[var(--color-text-dim)]">
                      {row.relation}
                    </div>
                    {!row.declared && (
                      <div className="mt-1 inline-block rounded-[4px] border border-dashed border-[var(--color-border-hover)] px-1.5 py-0.5 text-[9px] text-[var(--color-text-dim)]">
                        not declared as a source
                      </div>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </>
      )}
    </div>
  );
}
