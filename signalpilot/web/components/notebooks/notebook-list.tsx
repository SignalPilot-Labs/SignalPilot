"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import type { NotebookInfo } from "@/lib/types";
import { NotebookUploadModal } from "./notebook-upload";
import { BatchActionBar } from "./batch-action-bar";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyTerminal, EmptyState } from "@/components/ui/empty-states";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { getNotebooks, searchNotebooks, batchAnalyzeNotebooks, batchDeleteNotebooks } from "@/lib/api";
import { invalidateNotebooks } from "@/lib/hooks/use-gateway-data";
import { useToast } from "@/components/ui/toast";
import { NotebookListToolbar } from "./notebook-list-toolbar";

interface NotebookListProps {
  notebooks: NotebookInfo[];
  total: number;
}

const DEFAULT_SORT_BY = "updated_at";
const DEFAULT_SORT_DIR = "desc";
const DEFAULT_STATUS_FILTER = "all";

export function NotebookList({ notebooks, total }: NotebookListProps) {
  const { toast } = useToast();

  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<NotebookInfo[] | null>(null);
  const [searchTotal, setSearchTotal] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [loadingMoreSearch, setLoadingMoreSearch] = useState(false);
  const [extra, setExtra] = useState<NotebookInfo[]>([]);
  const [page, setPage] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  // Sort/filter state
  const [sortBy, setSortBy] = useState(DEFAULT_SORT_BY);
  const [sortDir, setSortDir] = useState(DEFAULT_SORT_DIR);
  const [statusFilter, setStatusFilter] = useState(DEFAULT_STATUS_FILTER);

  // Client-fetched list override (used when sort/filter differ from defaults after search is cleared)
  const [fetchedItems, setFetchedItems] = useState<NotebookInfo[] | null>(null);
  const [fetchedTotal, setFetchedTotal] = useState(0);

  // Multi-select state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchAnalyzing, setBatchAnalyzing] = useState(false);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Use a ref to detect stale responses: compare the query that triggered the
  // request against the current query when the response arrives.
  const latestQueryRef = useRef("");

  useEffect(() => {
    const trimmed = query.trim();
    latestQueryRef.current = trimmed;

    if (!trimmed) {
      setSearchResults(null);
      setSearchTotal(0);
      setIsSearching(false);
      // Reset pagination when search is cleared
      setExtra([]);
      setPage(0);
      // Clear selection when search query changes (prevents stale counts)
      setSelectedIds(new Set());

      // Search-clear edge case: if sort/filter differ from defaults, the SSR
      // prop reflects the server's default ordering — we need a fresh fetch.
      const nonDefault =
        sortBy !== DEFAULT_SORT_BY ||
        sortDir !== DEFAULT_SORT_DIR ||
        statusFilter !== DEFAULT_STATUS_FILTER;

      if (nonDefault) {
        let cancelled = false;
        (async () => {
          try {
            const response = await getNotebooks(50, 0, sortBy, sortDir, statusFilter);
            if (!cancelled) {
              setFetchedItems(response.items);
              setFetchedTotal(response.total);
            }
          } catch {
            if (!cancelled) {
              setFetchedItems(null);
            }
          }
        })();
        return () => { cancelled = true; };
      } else {
        // Back to defaults — fall through to SSR prop
        setFetchedItems(null);
        setFetchedTotal(0);
      }
      return;
    }

    setIsSearching(true);
    // Reset search state when query changes (avoid stale "X of Y")
    setSearchResults(null);
    setSearchTotal(0);
    setExtra([]);
    setPage(0);
    // Clear selection when search query changes
    setSelectedIds(new Set());

    // Only debounce the search text; sort/filter changes run immediately (no timer wrapping)
    const timer = setTimeout(async () => {
      const q = latestQueryRef.current;
      try {
        const response = await searchNotebooks(q, 50, 0, sortBy, sortDir, statusFilter);
        if (latestQueryRef.current === q) {
          setSearchResults(response.items);
          setSearchTotal(response.total);
        }
      } catch {
        if (latestQueryRef.current === q) {
          setSearchResults(null);
          setSearchTotal(0);
        }
      } finally {
        if (latestQueryRef.current === q) {
          setIsSearching(false);
        }
      }
    }, 300);

    return () => {
      clearTimeout(timer);
    };
  }, [query, sortBy, sortDir, statusFilter]);

  // resetList: clears pagination/selection state; called on sort/filter change
  function resetList() {
    setExtra([]);
    setPage(0);
    setSelectedIds(new Set());
  }

  function handleSortByChange(value: string) {
    setSortBy(value);
    resetList();
    // useEffect [query, sortBy, sortDir, statusFilter] handles re-fetch automatically
  }

  function handleSortDirChange(value: string) {
    setSortDir(value);
    resetList();
  }

  function handleStatusFilterChange(value: string) {
    setStatusFilter(value);
    resetList();
  }

  // Base list: fetchedItems overrides SSR prop when sort/filter are non-default
  const baseItems = fetchedItems !== null ? fetchedItems : notebooks;
  const baseTotal = fetchedItems !== null ? fetchedTotal : total;
  const allItems = [...baseItems, ...extra];

  // When server search is active, use its results; otherwise use accumulated items
  const isServerSearch = searchResults !== null;
  const isSearching_ = isServerSearch || query.trim().length > 0;
  const filtered = isServerSearch
    ? searchResults
    : query.trim()
      ? allItems.filter((nb) => {
          const q = query.toLowerCase();
          return (
            nb.name.toLowerCase().includes(q) ||
            nb.tags.some((t) => t.toLowerCase().includes(q))
          );
        })
      : allItems;

  // Counter copy: show result count during server search; "X of Y" otherwise
  const counterText = isServerSearch
    ? `${filtered.length} result${filtered.length !== 1 ? "s" : ""}`
    : `${filtered.length} of ${baseTotal} notebook${baseTotal !== 1 ? "s" : ""}`;

  // Selection helpers
  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function selectAll() {
    setSelectedIds(new Set(filtered.map((nb) => nb.id)));
  }

  function deselectAll() {
    setSelectedIds(new Set());
  }

  const allSelected = filtered.length > 0 && filtered.every((nb) => selectedIds.has(nb.id));

  async function handleBatchAnalyze() {
    if (selectedIds.size === 0) return;
    setBatchAnalyzing(true);
    try {
      const result = await batchAnalyzeNotebooks([...selectedIds]);
      await invalidateNotebooks();
      setSelectedIds(new Set());
      const msg = result.failed > 0
        ? `Analyzed: ${result.succeeded} succeeded, ${result.failed} failed`
        : `Analyzed ${result.succeeded} notebook${result.succeeded !== 1 ? "s" : ""}`;
      toast(msg, result.failed > 0 ? "error" : "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Batch analyze failed", "error");
    } finally {
      setBatchAnalyzing(false);
    }
  }

  function handleBatchDeleteRequest() {
    setDeleteConfirmOpen(true);
  }

  async function handleBatchDeleteConfirm() {
    setDeleteConfirmOpen(false);
    if (selectedIds.size === 0) return;
    setBatchDeleting(true);
    try {
      const result = await batchDeleteNotebooks([...selectedIds]);
      await invalidateNotebooks();
      setSelectedIds(new Set());
      const msg = result.failed > 0
        ? `Deleted: ${result.succeeded} succeeded, ${result.failed} failed`
        : `Deleted ${result.succeeded} notebook${result.succeeded !== 1 ? "s" : ""}`;
      toast(msg, result.failed > 0 ? "error" : "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Batch delete failed", "error");
    } finally {
      setBatchDeleting(false);
    }
  }

  async function handleLoadMore() {
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const response = await getNotebooks(50, nextPage * 50, sortBy, sortDir, statusFilter);
      setExtra((prev) => [...prev, ...response.items]);
      setPage(nextPage);
    } catch {
      // Load more failing silently is acceptable — user can retry
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleSearchLoadMore() {
    if (!searchResults) return;
    setLoadingMoreSearch(true);
    try {
      const trimmed = query.trim();
      const nextOffset = searchResults.length;
      const response = await searchNotebooks(trimmed, 50, nextOffset, sortBy, sortDir, statusFilter);
      if (latestQueryRef.current === trimmed) {
        setSearchResults((prev) => [...(prev ?? []), ...response.items]);
        setSearchTotal(response.total);
      }
    } catch {
      // Load more failing silently is acceptable — user can retry
    } finally {
      setLoadingMoreSearch(false);
    }
  }

  const showLoadMore = !isSearching_ && allItems.length < baseTotal;
  const showSearchLoadMore = isServerSearch && searchResults !== null && searchResults.length < searchTotal;

  return (
    <>
      <div className="flex items-center justify-between mb-4 gap-4 flex-wrap">
        {/* Search */}
        <div className="flex items-center gap-2 flex-1 max-w-xs">
          {isSearching ? (
            // Minimal inline spinner during search
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              className="flex-shrink-0 text-[var(--color-text-dim)] animate-spin"
              fill="none"
            >
              <circle
                cx="6"
                cy="6"
                r="4.5"
                stroke="currentColor"
                strokeWidth="1"
                strokeDasharray="14 8"
              />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0 text-[var(--color-text-dim)]">
              <circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1" />
              <path d="M8 8L10.5 10.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
            </svg>
          )}
          <input
            type="text"
            aria-label="Search notebooks"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search notebooks..."
            className="flex-1 bg-transparent text-[12px] text-[var(--color-text-muted)] placeholder:text-[var(--color-text-dim)] outline-none border-b border-[var(--color-border)] focus:border-[var(--color-border-hover)] pb-0.5 transition-colors tracking-wider"
          />
        </div>

        {/* Sort/filter toolbar */}
        <NotebookListToolbar
          sortBy={sortBy}
          sortDir={sortDir}
          statusFilter={statusFilter}
          onSortByChange={handleSortByChange}
          onSortDirChange={handleSortDirChange}
          onStatusFilterChange={handleStatusFilterChange}
        />

        <div className="flex items-center gap-3">
          <p className="text-[12px] text-[var(--color-text-muted)] tracking-wider">
            {counterText}
          </p>
          <button
            onClick={() => setModalOpen(true)}
            className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity"
          >
            + upload
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={EmptyTerminal}
          title={query ? "no matching notebooks" : "no notebooks yet"}
          description={
            query
              ? "No notebooks match your search. Try a different term."
              : "Upload a Jupyter notebook or use the MCP tools to add notebooks via an agent."
          }
          action={
            !query ? (
              <button
                onClick={() => setModalOpen(true)}
                className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity"
              >
                upload notebook
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((nb) => {
            const isSelected = selectedIds.has(nb.id);
            return (
              <div key={nb.id} className="relative">
                {/* Checkbox overlay — top-right, does not trigger card navigation */}
                <div
                  className="absolute top-2 right-2 z-10"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    toggleSelect(nb.id);
                  }}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ${nb.name}`}
                    checked={isSelected}
                    onChange={() => toggleSelect(nb.id)}
                    className="w-4 h-4 cursor-pointer accent-[var(--color-text)] bg-[var(--color-bg-card)] border border-[var(--color-border)]"
                  />
                </div>

                <Link
                  href={`/notebooks/${nb.id}`}
                  className={`block bg-[var(--color-bg-card)] border p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top group ${
                    isSelected
                      ? "border-[var(--color-border-active)]"
                      : "border-[var(--color-border)]"
                  }`}
                >
                  <h3 className="text-[12px] font-medium tracking-[0.15em] uppercase text-[var(--color-text)] group-hover:text-[var(--color-text)] mb-1 truncate pr-6">
                    {nb.name}
                  </h3>
                  {nb.description && (
                    <p className="text-[12px] text-[var(--color-text-muted)] mb-3 line-clamp-2">
                      {nb.description}
                    </p>
                  )}

                  {/* Tags */}
                  {nb.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-3">
                      {nb.tags.slice(0, 4).map((tag) => (
                        <span
                          key={tag}
                          className="px-1.5 py-0.5 text-[10px] font-mono tracking-wider bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text-dim)]"
                        >
                          {tag}
                        </span>
                      ))}
                      {nb.tags.length > 4 && (
                        <span className="px-1.5 py-0.5 text-[10px] text-[var(--color-text-dim)]">
                          +{nb.tags.length - 4}
                        </span>
                      )}
                    </div>
                  )}

                  <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-dim)] tracking-wider">
                    <span>{nb.cell_count} cell{nb.cell_count !== 1 ? "s" : ""}</span>
                    {nb.code_cell_count > 0 && (
                      <>
                        <span>&middot;</span>
                        <span>{nb.code_cell_count} code</span>
                      </>
                    )}
                    {nb.kernel_name && (
                      <>
                        <span>&middot;</span>
                        <span className="font-mono">{nb.kernel_name}</span>
                      </>
                    )}
                    <span>&middot;</span>
                    <TimeAgo timestamp={nb.updated_at} />
                    {nb.analyzed_at && (
                      <>
                        <span>&middot;</span>
                        <span className="text-[var(--color-success)] opacity-70">
                          analyzed <TimeAgo timestamp={nb.analyzed_at} />
                        </span>
                      </>
                    )}
                  </div>
                </Link>
              </div>
            );
          })}
        </div>
      )}

      {showLoadMore && (
        <div className="flex justify-center mt-8">
          <button
            onClick={handleLoadMore}
            disabled={loadingMore}
            className="px-6 py-2 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-50"
          >
            {loadingMore
              ? `loading... (${allItems.length} of ${baseTotal})`
              : `load more (${allItems.length} of ${baseTotal})`}
          </button>
        </div>
      )}

      {showSearchLoadMore && (
        <div className="flex justify-center mt-8">
          <button
            onClick={handleSearchLoadMore}
            disabled={loadingMoreSearch}
            className="px-6 py-2 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-50"
          >
            {loadingMoreSearch
              ? `loading... (${searchResults!.length} of ${searchTotal})`
              : `load more (${searchResults!.length} of ${searchTotal})`}
          </button>
        </div>
      )}

      <NotebookUploadModal open={modalOpen} onClose={() => setModalOpen(false)} />

      <BatchActionBar
        selectedCount={selectedIds.size}
        allSelected={allSelected}
        onSelectAll={selectAll}
        onDeselectAll={deselectAll}
        onAnalyze={handleBatchAnalyze}
        onDelete={handleBatchDeleteRequest}
        analyzing={batchAnalyzing}
        deleting={batchDeleting}
      />

      <ConfirmDialog
        open={deleteConfirmOpen}
        title="delete notebooks"
        message={`This will permanently delete ${selectedIds.size} notebook${selectedIds.size !== 1 ? "s" : ""} and their files. This cannot be undone.`}
        confirmLabel="delete"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleBatchDeleteConfirm}
        onCancel={() => setDeleteConfirmOpen(false)}
      />
    </>
  );
}
