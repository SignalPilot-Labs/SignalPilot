"use client";

import { useState, useCallback } from "react";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyState, EmptyList } from "@/components/ui/empty-states";
import { Skeleton } from "@/components/ui/skeleton";
import { useNotebookActivities } from "@/lib/hooks/use-gateway-data";
import { getNotebookActivities } from "@/lib/api";
import type { NotebookActivity } from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20;

/**
 * Per-action color token for the badge.
 * Only uses CSS variables defined in globals.css:
 * --color-success, --color-warning, --color-error, --color-text-muted, --color-text-dim
 */
const ACTION_COLORS: Record<string, { bg: string; text: string }> = {
  upload: {
    bg: "rgba(0, 255, 136, 0.08)",
    text: "var(--color-success)",
  },
  analyze: {
    bg: "rgba(238, 238, 238, 0.06)",
    text: "var(--color-text-muted)",
  },
  delete: {
    bg: "rgba(255, 68, 68, 0.10)",
    text: "var(--color-error)",
  },
  update: {
    bg: "rgba(255, 170, 0, 0.10)",
    text: "var(--color-warning)",
  },
  download: {
    bg: "rgba(238, 238, 238, 0.05)",
    text: "var(--color-text-dim)",
  },
  compare: {
    bg: "rgba(238, 238, 238, 0.06)",
    text: "var(--color-text-muted)",
  },
  export_report: {
    bg: "rgba(238, 238, 238, 0.05)",
    text: "var(--color-text-dim)",
  },
};

const DEFAULT_ACTION_COLOR = {
  bg: "rgba(238, 238, 238, 0.05)",
  text: "var(--color-text-dim)",
};

function getActionColor(action: string) {
  return ACTION_COLORS[action] ?? DEFAULT_ACTION_COLOR;
}

// ── Sub-components ───────────────────────────────────────────────────────────

interface ActivityItemProps {
  item: NotebookActivity;
}

function ActivityItem({ item }: ActivityItemProps) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = item.details !== null && Object.keys(item.details).length > 0;
  const color = getActionColor(item.action);

  const handleToggle = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);


  return (
    <li className="flex gap-4 group">
      {/* Timeline spine */}
      <div className="flex flex-col items-center">
        {/* Dot */}
        <div
          className="w-2 h-2 mt-1.5 shrink-0 border"
          style={{
            backgroundColor: color.bg,
            borderColor: color.text,
          }}
          aria-hidden="true"
        />
        {/* Vertical line */}
        <div className="w-px flex-1 mt-1 bg-[var(--color-border)]" aria-hidden="true" />
      </div>

      {/* Content */}
      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Action badge */}
          <span
            className="inline-block px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider border"
            style={{
              backgroundColor: color.bg,
              color: color.text,
              borderColor: color.text,
            }}
          >
            {item.action.replace(/_/g, " ")}
          </span>

          {/* Timestamp */}
          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
            <TimeAgo timestamp={item.created_at} />
          </span>

          {/* User id (if present) */}
          {item.user_id && (
            <span className="text-[11px] text-[var(--color-text-dim)] font-mono tracking-wider">
              by {item.user_id}
            </span>
          )}

          {/* Details toggle */}
          {hasDetails && (
            <button
              type="button"
              onClick={handleToggle}
              aria-expanded={expanded}
              aria-label={expanded ? "hide details" : "show details"}
              className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
            >
              {expanded ? "▾ details" : "▸ details"}
            </button>
          )}
        </div>

        {/* Expanded details */}
        {hasDetails && expanded && (
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            {Object.entries(item.details!).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-[10px] font-mono text-[var(--color-text-dim)] tracking-wider whitespace-nowrap">
                  {key}
                </dt>
                <dd className="text-[10px] font-mono text-[var(--color-text-muted)] tracking-wider break-all">
                  {typeof value === "boolean"
                    ? value
                      ? "true"
                      : "false"
                    : value === null
                      ? "null"
                      : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </li>
  );
}

// ── Loading skeleton ─────────────────────────────────────────────────────────

function ActivitySkeleton() {
  return (
    <div className="space-y-0">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex gap-4 pb-5">
          <div className="flex flex-col items-center">
            <Skeleton className="w-2 h-2 mt-1.5 shrink-0" />
            <div className="w-px flex-1 mt-1 bg-[var(--color-border)]" />
          </div>
          <div className="flex-1 pt-0.5">
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-3 w-8" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface NotebookActivityTimelineProps {
  notebookId: string;
}

export function NotebookActivityTimeline({ notebookId }: NotebookActivityTimelineProps) {
  const [offset, setOffset] = useState(0);
  const [allItems, setAllItems] = useState<NotebookActivity[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);

  const { data, isLoading, error } = useNotebookActivities(notebookId);

  // Merge SWR data into local list (first page)
  // We track pages manually so "load more" can append without re-fetching
  const baseItems = data?.items ?? [];
  const total = data?.total ?? 0;

  // Items to display: base page merged with any additional pages
  const displayItems = offset === 0 ? baseItems : allItems;
  const hasMore = displayItems.length < total;

  async function handleLoadMore() {
    if (loadingMore) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const nextOffset = displayItems.length;
      const result = await getNotebookActivities(notebookId, PAGE_SIZE, nextOffset);
      setAllItems((prev) => {
        // On first load-more, seed with base items + new items
        const base = offset === 0 ? baseItems : prev;
        return [...base, ...result.items];
      });
      setOffset(nextOffset);
    } catch (err) {
      setLoadMoreError(err instanceof Error ? err.message : "failed to load more");
    } finally {
      setLoadingMore(false);
    }
  }

  if (isLoading) {
    return <ActivitySkeleton />;
  }

  if (error) {
    return (
      <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-4">
        <p className="text-[12px] text-[var(--color-error)] tracking-wider">
          {error instanceof Error ? error.message : "failed to load activity"}
        </p>
      </div>
    );
  }

  if (baseItems.length === 0) {
    return (
      <EmptyState
        icon={EmptyList}
        title="no activity recorded"
        description="Actions like upload, analyze, delete, and download will appear here."
      />
    );
  }

  return (
    <div>
      <ul className="list-none p-0 m-0" aria-label="Notebook activity timeline">
        {displayItems.map((item) => (
          <ActivityItem key={item.id} item={item} />
        ))}
      </ul>

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
        {total} total {total === 1 ? "event" : "events"}
      </p>
    </div>
  );
}
