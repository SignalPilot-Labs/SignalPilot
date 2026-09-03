"use client";

/**
 * Inspector drawer for the selected model: identity, columns, tests, and
 * layer-labeled upstream/downstream lists. Actions: Focus (staged lineage
 * exploration) and Copy link (the model's shareable /lineage URL).
 */

import { Crosshair, Link2, X } from "lucide-react";
import React from "react";

import { useToast } from "~/components/ui/toast";
import { LAYER_COLOR, LAYER_LABEL, matGlyph } from "./palette";
import type { MapModel, ParsedMap } from "./parse-map";
import { canonicalRef, lineagePath } from "./lineage-nav";

export function Inspector({
  parsed,
  model,
  isFocused,
  onClose,
  onNavigate,
  onFocus,
}: {
  parsed: ParsedMap;
  model: MapModel;
  isFocused: boolean;
  onClose: () => void;
  onNavigate: (id: string) => void;
  onFocus: (id: string) => void;
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
    <div className="flex h-full w-72 shrink-0 flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-card)]/80 backdrop-blur">
      <div className="flex items-start justify-between gap-2 border-b border-[var(--color-border)] p-3">
        <div className="min-w-0">
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
        <button type="button" onClick={onClose} className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]" aria-label="Close inspector">
          <X className="h-3.5 w-3.5" />
        </button>
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

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        <div className="font-mono text-[11px] text-[var(--color-text-dim)]">
          {[model.database, model.schema, model.name].filter(Boolean).join(".")}
        </div>
        {model.description && (
          <p className="text-[11px] leading-5 text-[var(--color-text-muted)]">{model.description}</p>
        )}
        {model.columns.length > 0 && (
          <div>
            <div className="mb-1 text-[9px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
              columns ({model.columns.length})
            </div>
            {/* Name / dimmed type (when the distilled graph carries one —
                data follow-up for the gateway payload), description visible
                on its own clamped line instead of tooltip-only. */}
            <div className="max-h-48 overflow-y-auto rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)]">
              {model.columns.map((c) => (
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
    </div>
  );
}
