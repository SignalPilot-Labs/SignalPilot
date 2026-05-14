"use client";

import { useState, useCallback } from "react";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyState, EmptyList } from "@/components/ui/empty-states";
import { Skeleton } from "@/components/ui/skeleton";
import { useNotebookVersions } from "@/lib/hooks/use-gateway-data";
import { getNotebookVersions } from "@/lib/api";
import type { NotebookVersionInfo } from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20;

// Metric field labels for the table header and row rendering
const METRIC_FIELDS = [
  { key: "total_cells" as const, label: "cells" },
  { key: "code_cells" as const, label: "code" },
  { key: "error_cells" as const, label: "errors" },
  { key: "total_code_lines" as const, label: "lines" },
  { key: "functions_count" as const, label: "functions" },
  { key: "imports_count" as const, label: "imports" },
] satisfies { key: keyof NotebookVersionInfo; label: string }[];

// Fields where a higher value is a regression (red) vs improvement (green)
const REGRESSION_ON_INCREASE = new Set<keyof NotebookVersionInfo>(["error_cells"]);
// Fields where a higher value is an improvement (green) vs neutral
const IMPROVEMENT_ON_INCREASE = new Set<keyof NotebookVersionInfo>([
  "code_cells",
  "total_code_lines",
  "functions_count",
  "imports_count",
]);

// ── Delta helpers ─────────────────────────────────────────────────────────────

type MetricKey = (typeof METRIC_FIELDS)[number]["key"];

function computeDelta(
  current: NotebookVersionInfo,
  prev: NotebookVersionInfo | undefined,
  key: MetricKey,
): number | null {
  if (!prev) return null;
  return (current[key] as number) - (prev[key] as number);
}

function deltaColor(key: MetricKey, delta: number): string {
  if (delta === 0) return "text-[var(--color-text-dim)]";
  if (REGRESSION_ON_INCREASE.has(key)) {
    // More errors = red; fewer errors = green
    return delta > 0 ? "text-[var(--color-error)]" : "text-[var(--color-success)]";
  }
  if (IMPROVEMENT_ON_INCREASE.has(key)) {
    // More coverage/functions/lines = green; fewer = neutral (not actively bad)
    return delta > 0 ? "text-[var(--color-success)]" : "text-[var(--color-text-dim)]";
  }
  // Neutral fields (total_cells, markdown_cells)
  return "text-[var(--color-text-muted)]";
}

function formatDelta(delta: number): string {
  return delta > 0 ? `+${delta}` : String(delta);
}

// ── Sub-components ───────────────────────────────────────────────────────────

interface VersionRowProps {
  item: NotebookVersionInfo;
  prev: NotebookVersionInfo | undefined;
}

function VersionRow({ item, prev }: VersionRowProps) {
  return (
    <tr className="border-b border-[var(--color-border)] hover:bg-[var(--color-bg-card)] transition-colors">
      {/* Version number */}
      <td className="py-2.5 px-3 text-[12px] font-mono text-[var(--color-text)] whitespace-nowrap">
        v{item.version_number}
      </td>
      {/* Analyzed timestamp */}
      <td className="py-2.5 px-3 text-[11px] text-[var(--color-text-dim)] tracking-wider whitespace-nowrap">
        <TimeAgo timestamp={item.analyzed_at} />
      </td>
      {/* Metric columns */}
      {METRIC_FIELDS.map(({ key }) => {
        const value = item[key] as number;
        const delta = computeDelta(item, prev, key);
        return (
          <td key={key} className="py-2.5 px-3 text-right">
            <span className="text-[12px] font-mono text-[var(--color-text-muted)]">
              {value}
            </span>
            {delta !== null && delta !== 0 && (
              <span
                className={`ml-1.5 text-[10px] font-mono tracking-wider ${deltaColor(key, delta)}`}
              >
                {formatDelta(delta)}
              </span>
            )}
          </td>
        );
      })}
    </tr>
  );
}

// ── Loading skeleton ─────────────────────────────────────────────────────────

function VersionSkeleton() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-[var(--color-border)]">
            <th className="py-2 px-3 text-left">
              <Skeleton className="h-3 w-8" />
            </th>
            <th className="py-2 px-3 text-left">
              <Skeleton className="h-3 w-16" />
            </th>
            {METRIC_FIELDS.map(({ key }) => (
              <th key={key} className="py-2 px-3 text-right">
                <Skeleton className="h-3 w-12 ml-auto" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: 3 }).map((_, i) => (
            <tr key={i} className="border-b border-[var(--color-border)]">
              <td className="py-2.5 px-3">
                <Skeleton className="h-4 w-8" />
              </td>
              <td className="py-2.5 px-3">
                <Skeleton className="h-3 w-20" />
              </td>
              {METRIC_FIELDS.map(({ key }) => (
                <td key={key} className="py-2.5 px-3 text-right">
                  <Skeleton className="h-3 w-10 ml-auto" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface NotebookVersionHistoryProps {
  notebookId: string;
}

export function NotebookVersionHistory({ notebookId }: NotebookVersionHistoryProps) {
  const [offset, setOffset] = useState(0);
  const [allItems, setAllItems] = useState<NotebookVersionInfo[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);

  const { data, isLoading, error } = useNotebookVersions(notebookId);

  const baseItems = data?.items ?? [];
  const total = data?.total ?? 0;

  // Items to display: base page merged with any additional pages
  const displayItems = offset === 0 ? baseItems : allItems;
  const hasMore = displayItems.length < total;

  const handleLoadMore = useCallback(async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const nextOffset = displayItems.length;
      const result = await getNotebookVersions(notebookId, PAGE_SIZE, nextOffset);
      setAllItems((prev) => {
        const base = offset === 0 ? baseItems : prev;
        return [...base, ...result.items];
      });
      setOffset(nextOffset);
    } catch (err) {
      setLoadMoreError(err instanceof Error ? err.message : "failed to load more");
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, displayItems.length, notebookId, offset, baseItems]);

  if (isLoading) {
    return <VersionSkeleton />;
  }

  if (error) {
    return (
      <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-4">
        <p className="text-[12px] text-[var(--color-error)] tracking-wider">
          {error instanceof Error ? error.message : "failed to load version history"}
        </p>
      </div>
    );
  }

  if (baseItems.length === 0) {
    return (
      <EmptyState
        icon={EmptyList}
        title="no versions recorded yet"
        description="Each time this notebook is analyzed, a version snapshot will be saved here."
      />
    );
  }

  return (
    <div>
      <div className="overflow-x-auto border border-[var(--color-border)]">
        <table
          className="w-full border-collapse"
          aria-label="Notebook version history"
        >
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg-card)]">
              <th
                scope="col"
                className="py-2 px-3 text-left text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] font-medium whitespace-nowrap"
              >
                version
              </th>
              <th
                scope="col"
                className="py-2 px-3 text-left text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] font-medium whitespace-nowrap"
              >
                analyzed
              </th>
              {METRIC_FIELDS.map(({ key, label }) => (
                <th
                  key={key}
                  scope="col"
                  className="py-2 px-3 text-right text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] font-medium whitespace-nowrap"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayItems.map((item, idx) => (
              <VersionRow
                key={item.id}
                item={item}
                // displayItems is ordered newest-first; prev version is idx+1
                prev={displayItems[idx + 1]}
              />
            ))}
          </tbody>
        </table>
      </div>

      {loadMoreError && (
        <p className="text-[11px] text-[var(--color-error)] tracking-wider mt-2">
          {loadMoreError}
        </p>
      )}

      {hasMore && (
        <button
          type="button"
          onClick={() => void handleLoadMore()}
          disabled={loadingMore}
          className="mt-2 text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
        >
          {loadingMore ? "loading..." : `load more (${total - displayItems.length} remaining)`}
        </button>
      )}

      <p className="mt-4 text-[10px] text-[var(--color-text-dim)] tracking-wider opacity-60">
        {total} total {total === 1 ? "version" : "versions"}
      </p>
    </div>
  );
}
