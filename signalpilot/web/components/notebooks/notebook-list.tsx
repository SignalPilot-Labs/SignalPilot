"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import type { NotebookInfo } from "@/lib/types";
import { NotebookUploadModal } from "./notebook-upload";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyTerminal, EmptyState } from "@/components/ui/empty-states";
import { searchNotebooks } from "@/lib/api";

interface NotebookListProps {
  notebooks: NotebookInfo[];
}

export function NotebookList({ notebooks }: NotebookListProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<NotebookInfo[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  // Use a ref to detect stale responses: compare the query that triggered the
  // request against the current query when the response arrives.
  const latestQueryRef = useRef("");

  useEffect(() => {
    const trimmed = query.trim();
    latestQueryRef.current = trimmed;

    if (!trimmed) {
      setSearchResults(null);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);

    const timer = setTimeout(async () => {
      try {
        const results = await searchNotebooks(trimmed, 50, 0);
        if (latestQueryRef.current === trimmed) {
          setSearchResults(results);
        }
      } catch {
        if (latestQueryRef.current === trimmed) {
          setSearchResults(null);
        }
      } finally {
        if (latestQueryRef.current === trimmed) {
          setIsSearching(false);
        }
      }
    }, 300);

    return () => {
      clearTimeout(timer);
    };
  }, [query]);

  // When server search is active, use its results; otherwise use client-side filter
  const isServerSearch = searchResults !== null;
  const filtered = isServerSearch
    ? searchResults
    : query.trim()
      ? notebooks.filter((nb) => {
          const q = query.toLowerCase();
          return (
            nb.name.toLowerCase().includes(q) ||
            nb.tags.some((t) => t.toLowerCase().includes(q))
          );
        })
      : notebooks;

  // Counter copy: show result count during server search; "X of Y" otherwise
  const counterText = isServerSearch
    ? `${filtered.length} result${filtered.length !== 1 ? "s" : ""}`
    : `${filtered.length} of ${notebooks.length} notebook${notebooks.length !== 1 ? "s" : ""}`;

  return (
    <>
      <div className="flex items-center justify-between mb-6 gap-4">
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
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search notebooks..."
            className="flex-1 bg-transparent text-[12px] text-[var(--color-text-muted)] placeholder:text-[var(--color-text-dim)] outline-none border-b border-[var(--color-border)] focus:border-[var(--color-border-hover)] pb-0.5 transition-colors tracking-wider"
          />
        </div>

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
          {filtered.map((nb) => (
            <Link
              key={nb.id}
              href={`/notebooks/${nb.id}`}
              className="block bg-[var(--color-bg-card)] border border-[var(--color-border)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top group"
            >
              <h3 className="text-[12px] font-medium tracking-[0.15em] uppercase text-[var(--color-text)] group-hover:text-[var(--color-text)] mb-1 truncate">
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
                    <span className="text-[var(--color-success)] opacity-70">analyzed</span>
                  </>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}

      <NotebookUploadModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
