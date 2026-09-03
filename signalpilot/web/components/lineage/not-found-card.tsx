"use client";

/**
 * Overlay card for deep links that can't be shown yet: unknown model (with
 * fuzzy "did you mean" suggestions), ambiguous name (disambiguation list),
 * and project-not-mapped. The full map stays dimmed behind it and the bad
 * URL stays in the address bar so the typo remains visible and correctable.
 */

import { ArrowRight, Hammer, Loader2, SearchX } from "lucide-react";
import React from "react";

import { LAYER_COLOR, LAYER_LABEL } from "./palette";
import type { ParsedMap } from "./parse-map";
import type { ModelResolution } from "./lineage-nav";

function CardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-[var(--color-bg)]/70 backdrop-blur-[2px]">
      <div className="animate-fade-in w-full max-w-sm rounded-[14px] border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 shadow-[0_16px_48px_rgba(0,0,0,0.5)]">
        {children}
      </div>
    </div>
  );
}

export function NotFoundCard({
  parsed,
  targetRef,
  resolution,
  onPick,
  onShowFullMap,
}: {
  parsed: ParsedMap;
  targetRef: string;
  resolution: ModelResolution;
  onPick: (ref: string) => void;
  onShowFullMap: () => void;
}) {
  if (resolution.kind === "found") return null;

  return (
    <CardShell>
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-input)]">
          <SearchX className="h-4 w-4 text-[var(--color-text-dim)]" />
        </span>
        <p className="text-[13px] leading-5 text-[var(--color-text)]">
          {resolution.kind === "ambiguous" ? (
            <>
              More than one model is named{" "}
              <span className="font-mono text-[12px]">{targetRef}</span>.
            </>
          ) : (
            <>
              No model named <span className="font-mono text-[12px]">{targetRef}</span> in
              this project.
            </>
          )}
        </p>
      </div>

      {resolution.kind === "ambiguous" && (
        <div className="mb-4 flex flex-col gap-1">
          <div className="mb-0.5 text-[10px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
            pick one
          </div>
          {resolution.ids.map((id) => {
            const m = parsed.models.get(id);
            const color = m ? LAYER_COLOR[m.layer] : "var(--color-text-dim)";
            return (
              <button
                key={id}
                type="button"
                onClick={() => onPick(id)}
                className="flex items-center gap-2 rounded-[8px] border border-[var(--color-border)] px-2.5 py-1.5 text-left font-mono text-[11px] text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-[2px]" style={{ background: color }} aria-hidden="true" />
                <span className="truncate">{id}</span>
                {m && (
                  <span className="ml-auto shrink-0 text-[8px] uppercase tracking-[0.08em]" style={{ color }}>
                    {LAYER_LABEL[m.layer]}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {resolution.kind === "not-found" && resolution.suggestions.length > 0 && (
        <div className="mb-4 flex flex-col gap-0.5">
          {/* Link-styled rows — the single bordered rectangle below stays the
              one primary action. The name and "?" share a text node so no flex
              gap floats the question mark. */}
          {resolution.suggestions.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => onPick(name)}
              className="group flex items-center gap-1.5 rounded-[8px] px-2 py-1.5 text-left text-[11px] text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
            >
              <ArrowRight
                className="h-3 w-3 shrink-0 text-[var(--color-text-dim)] transition-colors group-hover:text-[var(--color-text)]"
                aria-hidden="true"
              />
              <span className="min-w-0 truncate">
                Did you mean{" "}
                <span className="font-mono text-[var(--color-text)] group-hover:underline">{name}</span>?
              </span>
            </button>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={onShowFullMap}
        className="w-full rounded-[8px] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text)] transition-colors hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)]"
      >
        Show full map
      </button>
    </CardShell>
  );
}

/** Deep link into a project whose manifest hasn't been parsed yet. */
export function UnmappedCard({
  targetRef,
  status,
  compiling,
  onCompile,
}: {
  targetRef: string;
  status: string;
  compiling: boolean;
  onCompile: () => void;
}) {
  const inFlight = status === "running" || status === "queued";
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <div className="animate-fade-in w-full max-w-sm rounded-[14px] border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
        <p className="text-[13px] leading-5 text-[var(--color-text)]">
          This project hasn&apos;t been mapped yet.
        </p>
        <p className="mt-1.5 text-[11px] leading-5 text-[var(--color-text-muted)]">
          The lineage for <span className="font-mono">{targetRef}</span> will be here once the
          dbt map compiles.
        </p>
        <button
          type="button"
          onClick={onCompile}
          disabled={compiling || inFlight}
          className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-[8px] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text)] transition-colors hover:border-[var(--color-border-hover)] disabled:opacity-50"
        >
          {compiling || inFlight ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" /> compiling on a sandbox…
            </>
          ) : (
            <>
              <Hammer className="h-3 w-3" /> compile dbt map
            </>
          )}
        </button>
      </div>
    </div>
  );
}
