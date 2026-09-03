"use client";

/**
 * Inspector drawer for the selected model. Two tabs: Details (identity,
 * columns, tests, layer-labeled upstream/downstream lists) and SQL (raw or
 * compiled body, see inspector-sql.tsx). Actions: Focus (staged lineage
 * exploration) and Copy link (the model's shareable /lineage URL).
 */

import { Crosshair, Link2, Maximize2, Minimize2, X } from "lucide-react";
import React from "react";

import { Skeleton } from "~/components/ui/skeleton";
import { useToast } from "~/components/ui/toast";
import { LAYER_COLOR, LAYER_LABEL, matGlyph } from "./palette";
import type { MapColumn, MapModel, ParsedMap } from "./parse-map";
import { canonicalRef, lineagePath } from "./lineage-nav";
import { InspectorSql } from "./inspector-sql";
import { InspectorResizeHandle } from "./inspector-resize-handle";
import type { InspectorWidthState } from "./use-inspector-width";
import type { ModelSqlState } from "./use-dbt-map";

export type InspectorTab = "details" | "sql";
const TABS: InspectorTab[] = ["details", "sql"];

export function Inspector({
  parsed,
  model,
  columns,
  sql,
  tab,
  onTabChange,
  isFocused,
  onClose,
  onNavigate,
  onFocus,
  size,
}: {
  parsed: ParsedMap;
  model: MapModel;
  /** Resolved columns; null while the lazy request is in flight. */
  columns: MapColumn[] | null;
  sql: ModelSqlState;
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  isFocused: boolean;
  onClose: () => void;
  onNavigate: (id: string) => void;
  onFocus: (id: string) => void;
  /** Width state from use-inspector-width; the host owns it. */
  size: InspectorWidthState;
}) {
  const { toast } = useToast();
  const color = LAYER_COLOR[model.layer];

  const copyLink = () => {
    const url = `${window.location.origin}${lineagePath(canonicalRef(parsed, model.id))}`;
    void navigator.clipboard.writeText(url).then(
      () => toast("Link copied", "success"),
      () => toast("Could not copy the link", "error"),
    );
  };

  const relList = (ids: string[], label: string) =>
    ids.length > 0 && (
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
          {label} ({ids.length})
        </div>
        <div className="flex flex-col gap-px">
          {ids.map((id) => {
            const rel = parsed.models.get(id);
            if (!rel) return null;
            const relColor = LAYER_COLOR[rel.layer];
            return (
              <button
                key={id}
                type="button"
                onClick={() => onNavigate(id)}
                className="flex items-center gap-1.5 rounded px-1.5 py-1 text-left font-mono text-[11px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-[2px]" style={{ background: relColor }} aria-hidden="true" />
                <span className="truncate">{rel.name}</span>
                <span
                  className="ml-auto shrink-0 rounded-[4px] px-1 py-0.5 text-[8px] uppercase tracking-[0.08em]"
                  style={{ color: relColor, background: `${relColor}14` }}
                >
                  {LAYER_LABEL[rel.layer]}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    );

  return (
    <div
      data-testid="lineage-inspector"
      data-wide={size.wide ? "1" : "0"}
      style={{ width: size.width }}
      className="relative flex h-full shrink-0 flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-card)]/80 backdrop-blur"
    >
      <InspectorResizeHandle
        width={size.width}
        bounds={size.bounds}
        onPreview={size.preview}
        onCommit={size.commit}
        onReset={size.reset}
      />
      <div className="flex items-start justify-between gap-2 border-b border-[var(--color-border)] p-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px]" style={{ color, background: `${color}1f` }} aria-hidden="true">
              {matGlyph(model.materialized, model.layer)}
            </span>
            <span className="truncate font-mono text-xs font-bold text-[var(--color-text)]">{model.name}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[9px] leading-none">
            <span className="rounded-[4px] px-1.5 py-0.5 uppercase tracking-[0.08em]" style={{ color, background: `${color}1a`, border: `1px solid ${color}55` }}>
              {LAYER_LABEL[model.layer]}
            </span>
            <span className="rounded-[4px] border border-[var(--color-border)] px-1.5 py-0.5 text-[var(--color-text-muted)]">{model.materialized}</span>
            {model.tags.map((t) => (
              <span key={t} className="rounded-[4px] border border-[var(--color-border)] px-1.5 py-0.5 text-[var(--color-text-dim)]">#{t}</span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={size.toggleWide}
            aria-pressed={size.wide}
            aria-label={size.wide ? "Restore inspector width" : "Expand inspector"}
            title={size.wide ? "Restore width" : "Expand for SQL"}
            data-testid="inspector-expand"
            className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
          >
            {size.wide ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
          <button type="button" onClick={onClose} className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]" aria-label="Close inspector">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1.5 border-b border-[var(--color-border)] px-3 py-2">
        <button
          type="button"
          onClick={() => onFocus(model.id)}
          disabled={isFocused}
          className="flex items-center gap-1.5 rounded-[8px] border border-[var(--color-border)] px-2 py-1 text-[10px] text-[var(--color-text)] transition-colors hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] disabled:opacity-40"
        >
          <Crosshair className="h-3 w-3" />
          {isFocused ? "Focused" : "Focus"}
        </button>
        <button
          type="button"
          onClick={copyLink}
          className="flex items-center gap-1.5 rounded-[8px] border border-[var(--color-border)] px-2 py-1 text-[10px] text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
        >
          <Link2 className="h-3 w-3" />
          Copy link
        </button>
      </div>

      {/* Tabs: arrow keys move between them, the panel below follows. */}
      <div role="tablist" aria-label="Inspector sections" className="flex items-center gap-1 border-b border-[var(--color-border)] px-2 py-1.5">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            id={`inspector-tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`inspector-panel-${t}`}
            tabIndex={tab === t ? 0 : -1}
            data-testid={`inspector-tab-${t}`}
            onClick={() => onTabChange(t)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              e.preventDefault();
              const step = e.key === "ArrowRight" ? 1 : TABS.length - 1;
              const next = TABS[(TABS.indexOf(t) + step) % TABS.length];
              onTabChange(next);
              document.getElementById(`inspector-tab-${next}`)?.focus();
            }}
            className={`rounded-[7px] px-2.5 py-1 text-[10px] uppercase tracking-[0.1em] transition-colors ${
              tab === t
                ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "sql" ? (
        <div
          role="tabpanel"
          id="inspector-panel-sql"
          aria-labelledby="inspector-tab-sql"
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <InspectorSql state={sql} modelName={model.name} />
        </div>
      ) : (
      <div
        role="tabpanel"
        id="inspector-panel-details"
        aria-labelledby="inspector-tab-details"
        className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3"
      >
        <div className="font-mono text-[11px] text-[var(--color-text-dim)]">
          {[model.database, model.schema, model.name].filter(Boolean).join(".")}
        </div>
        {model.description && (
          <p className="text-[11px] leading-5 text-[var(--color-text-muted)]">{model.description}</p>
        )}
        {model.columnCount > 0 && (
          <div data-testid="inspector-columns" data-loaded={columns ? "1" : "0"}>
            <div className="mb-1 text-[9px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
              columns ({model.columnCount})
            </div>
            {/* Name / dimmed type (when the distilled graph carries one —
                data follow-up for the gateway payload), description visible
                on its own clamped line instead of tooltip-only. */}
            <div className="max-h-[40vh] overflow-y-auto rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)]">
              {columns === null && (
                <div className="space-y-1.5 px-2 py-1.5" aria-busy="true">
                  {Array.from({ length: Math.min(model.columnCount, 4) }, (_, i) => (
                    <Skeleton key={i} className={`h-2.5 ${i % 2 ? "w-24" : "w-32"}`} />
                  ))}
                </div>
              )}
              {(columns ?? []).map((c) => (
                <div key={c.name} className="border-b border-[var(--color-border)] px-2 py-1 last:border-b-0">
                  <div className="flex items-baseline gap-2">
                    <span className="min-w-0 truncate font-mono text-[11px] text-[var(--color-text-muted)]">
                      {c.name}
                    </span>
                    {c.dataType && (
                      <span className="ml-auto shrink-0 font-mono text-[9px] uppercase text-[var(--color-text-dim)]">
                        {c.dataType}
                      </span>
                    )}
                  </div>
                  {c.description && (
                    <div className="truncate text-[9px] leading-4 text-[var(--color-text-dim)]" title={c.description}>
                      {c.description}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        {model.tests.length > 0 && (
          <div>
            <div className="mb-1 text-[9px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
              tests ({model.tests.length})
            </div>
            <div className="flex flex-col gap-px">
              {model.tests.map((t, i) => (
                <div key={`${t.name}-${i}`} className="flex items-center gap-1.5 px-1.5 py-0.5 font-mono text-[11px] text-[var(--color-text-muted)]">
                  <span className="text-[var(--color-success)]" aria-hidden="true">✓</span>
                  <span className="truncate">{t.type}{t.column ? `(${t.column})` : ""}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {relList(model.parents, "upstream")}
        {relList(model.children, "downstream")}
      </div>
      )}
    </div>
  );
}
