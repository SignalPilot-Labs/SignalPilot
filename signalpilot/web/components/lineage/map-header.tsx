"use client";

/**
 * Top bar of the dbt map page: title, project picker, search, the focused
 * model breadcrumb chip (with copy-link), the provenance stamp
 * ("main · rev 4 · parsed 2h ago"), watched-branch auto-update pill, and
 * the compile action.
 *
 * Responsive collapse ladder (never wraps, never overlaps):
 *  - the focus chip is the one flexible item (min-w-0 + truncate);
 *  - everything else is shrink-0 + whitespace-nowrap;
 *  - the auto-push pill shows only at xl+ (its content lives in its tooltip
 *    and in the info popover);
 *  - below lg, provenance + auto-push + dbt version fold into an "i" popover.
 */

import { Hammer, Info, Link2, Loader2, RefreshCw, Search, X } from "lucide-react";
import React, { useState } from "react";

import { TimeAgo } from "~/components/ui/time-ago";
import { useToast } from "~/components/ui/toast";
import type { DbtMapInfo, WorkspaceProjectInfo } from "~/lib/types";
import { LAYER_COLOR } from "./palette";
import type { MapModel } from "./parse-map";
import type { MapStatus } from "./use-dbt-map";

function Provenance({ mapInfo, mapStatus }: { mapInfo: DbtMapInfo; mapStatus: MapStatus }) {
  if (mapStatus === "running" || mapStatus === "queued") {
    return (
      <span className="hidden items-center gap-1.5 whitespace-nowrap font-mono text-[10px] text-[var(--color-text-dim)] lg:flex">
        <Loader2 className="h-3 w-3 animate-spin text-[var(--color-warning)]" />
        compiling on sandbox…
      </span>
    );
  }
  if (mapStatus === "failed") {
    return (
      <span className="hidden whitespace-nowrap font-mono text-[10px] text-[var(--color-error)] lg:flex">
        last compile failed
      </span>
    );
  }
  return (
    <span className="hidden items-center gap-1.5 whitespace-nowrap font-mono text-[10px] text-[var(--color-text-dim)] lg:flex">
      <span className="text-[var(--color-text-muted)]">{mapInfo.branch}</span>
      {/* "rev 0" (first compile) reads as a bug, not provenance — omit it. */}
      {mapInfo.revision > 0 && (
        <>
          <span aria-hidden="true">·</span>
          <span>rev {mapInfo.revision}</span>
        </>
      )}
      <span aria-hidden="true">·</span>
      <span>
        parsed <TimeAgo timestamp={mapInfo.updated_at} live /> ago
      </span>
      {mapInfo.dbt_version ? (
        <span className="hidden xl:inline"> · dbt {mapInfo.dbt_version}</span>
      ) : null}
    </span>
  );
}

/** <lg fold of provenance + auto-push + dbt version into one popover. */
function InfoPopover({
  mapInfo,
  mapStatus,
  watched,
}: {
  mapInfo: DbtMapInfo;
  mapStatus: MapStatus;
  watched: string[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative lg:hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
        aria-label="Map provenance"
        aria-expanded={open}
        className="flex h-6 w-6 items-center justify-center rounded-[8px] border border-[var(--color-border)] text-[var(--color-text-dim)] transition-colors hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
      >
        <Info className="h-3 w-3" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1.5 w-56 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-card)] p-2.5 font-mono text-[10px] leading-5 text-[var(--color-text-muted)] shadow-[0_12px_32px_rgba(0,0,0,0.5)]">
          <div>branch {mapInfo.branch}</div>
          {mapInfo.revision > 0 && <div>rev {mapInfo.revision}</div>}
          {mapStatus === "running" || mapStatus === "queued" ? (
            <div>compiling on sandbox…</div>
          ) : mapStatus === "failed" ? (
            <div className="text-[var(--color-error)]">last compile failed</div>
          ) : (
            <div>
              parsed <TimeAgo timestamp={mapInfo.updated_at} live /> ago
            </div>
          )}
          {mapInfo.dbt_version && <div>dbt {mapInfo.dbt_version}</div>}
          {watched.length > 0 && (
            <div className="text-[var(--color-text-dim)]">auto · push → {watched.join(", ")}</div>
          )}
        </div>
      )}
    </div>
  );
}

export function MapHeader({
  projects,
  projectId,
  onProjectChange,
  query,
  onQueryChange,
  searchRef,
  focusModel,
  rawView,
  focusUrl,
  onExitFocus,
  mapInfo,
  mapStatus,
  watched,
  compiling,
  onCompile,
}: {
  projects: WorkspaceProjectInfo[];
  projectId: string | null;
  onProjectChange: (id: string) => void;
  query: string;
  onQueryChange: (q: string) => void;
  searchRef: React.RefObject<HTMLInputElement | null>;
  focusModel: MapModel | null;
  rawView: boolean;
  /** Absolute path of the current focus view, for the copy-link action. */
  focusUrl: string | null;
  onExitFocus: () => void;
  mapInfo: DbtMapInfo | null;
  mapStatus: MapStatus;
  watched: string[];
  compiling: boolean;
  onCompile: () => void;
}) {
  const { toast } = useToast();

  const copyFocusLink = () => {
    if (!focusUrl) return;
    void navigator.clipboard.writeText(`${window.location.origin}${focusUrl}`).then(
      () => toast("Link copied", "success"),
      () => toast("Could not copy the link", "error"),
    );
  };

  return (
    <div className="flex items-center gap-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg-card)]/40 px-3 py-2.5 lg:gap-4 lg:px-5">
      <div className="flex shrink-0 items-baseline gap-2 whitespace-nowrap">
        <h1 className="text-sm font-bold lowercase text-[var(--color-text)]">dbt map</h1>
        <span className="hidden text-[10px] text-[var(--color-text-dim)] lg:inline">lineage</span>
      </div>

      <select
        value={projectId ?? ""}
        onChange={(e) => onProjectChange(e.target.value)}
        className="max-w-36 shrink-0 rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1 font-mono text-[11px] text-[var(--color-text)] focus:outline-none lg:max-w-52"
        aria-label="Project"
      >
        {projects.map((p) => (
          <option key={p.id} value={p.id}>{p.display_name || p.name}</option>
        ))}
      </select>

      <div className="relative shrink-0">
        <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--color-text-dim)]" />
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder={focusModel ? "search this lineage…" : "search models…"}
          aria-label={focusModel ? "Search this lineage" : "Search models"}
          className="w-32 rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] py-1 pl-7 pr-7 font-mono text-[11px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none md:w-44 xl:w-52"
        />
        {!query && (
          <kbd className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 rounded border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1 py-px font-mono text-[9px] leading-none text-[var(--color-text-dim)]">
            /
          </kbd>
        )}
      </div>

      {focusModel && (
        <div
          className="flex min-w-0 items-center gap-1 rounded-[8px] border py-0.5 pl-2.5 pr-1"
          style={{ borderColor: `${LAYER_COLOR[focusModel.layer]}66`, background: `${LAYER_COLOR[focusModel.layer]}12` }}
          data-testid="focus-chip"
        >
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-[2px]"
            style={{ background: LAYER_COLOR[focusModel.layer] }}
            aria-hidden="true"
          />
          <span className="min-w-14 max-w-40 truncate font-mono text-[11px] text-[var(--color-text)] xl:max-w-56">
            {focusModel.name}
          </span>
          {/* Below lg the panel's highlighted tab already says "raw tables". */}
          {rawView && (
            <span className="ml-0.5 hidden shrink-0 whitespace-nowrap rounded-[4px] border border-[var(--color-border)] px-1 py-px text-[8px] uppercase tracking-[0.08em] text-[var(--color-text-muted)] lg:inline">
              raw tables
            </span>
          )}
          <button
            type="button"
            onClick={copyFocusLink}
            aria-label="Copy link to this view"
            title="Copy link to this view"
            className="ml-0.5 hidden shrink-0 rounded p-1 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] lg:block"
          >
            <Link2 className="h-3 w-3" />
          </button>
          <button
            type="button"
            onClick={onExitFocus}
            aria-label="Back to full map"
            title="Back to full map (Esc)"
            className="shrink-0 rounded p-1 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      <div className="ml-auto flex shrink-0 items-center gap-2 lg:gap-3">
        {mapInfo && <Provenance mapInfo={mapInfo} mapStatus={mapStatus} />}
        {watched.length > 0 && (
          <span
            className="hidden items-center gap-1.5 whitespace-nowrap rounded-full border border-[var(--color-border)] px-2 py-1 text-[9px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] xl:flex"
            title={`This map recompiles automatically on pushes to: ${watched.join(", ")}`}
          >
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--color-success)] opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
            </span>
            auto · push → {watched.join(", ")}
          </span>
        )}
        {mapInfo && <InfoPopover mapInfo={mapInfo} mapStatus={mapStatus} watched={watched} />}
        <button
          type="button"
          onClick={onCompile}
          disabled={compiling || mapStatus === "running"}
          className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[8px] border border-[var(--color-border)] px-2.5 py-1 text-[10px] text-[var(--color-text)] hover:border-[var(--color-border-hover)] disabled:opacity-40"
        >
          {compiling || mapStatus === "running" ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Hammer className="h-3 w-3" />}
          compile
        </button>
      </div>
    </div>
  );
}
