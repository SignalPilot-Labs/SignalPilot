"use client";

import Link from "next/link";
import type { NotebookInfo } from "@/lib/types";
import { NotebookUploadModal } from "./notebook-upload";
import { BatchActionBar } from "./batch-action-bar";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyTerminal, EmptyState } from "@/components/ui/empty-states";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { NotebookListToolbar } from "./notebook-list-toolbar";
import { useNotebookList } from "./use-notebook-list";
import { QualityBadge } from "./quality-badge";

interface NotebookListProps {
  notebooks: NotebookInfo[];
  total: number;
}

export function NotebookList({ notebooks, total }: NotebookListProps) {
  const {
    modalOpen, setModalOpen,
    query, setQuery, isSearching,
    filtered, counterText,
    showLoadMore, loadingMore, allItemsCount, baseTotal, handleLoadMore,
    showSearchLoadMore, loadingMoreSearch, searchResultsCount, searchTotal, handleSearchLoadMore,
    sortBy, sortDir, statusFilter, handleSortByChange, handleSortDirChange, handleStatusFilterChange,
    selectedIds, allSelected, toggleSelect, selectAll, deselectAll,
    batchAnalyzing, batchDeleting, deleteConfirmOpen, setDeleteConfirmOpen,
    handleBatchAnalyze, handleBatchDeleteRequest, handleBatchDeleteConfirm,
  } = useNotebookList({ notebooks, total });

  return (
    <>
      <div className="flex items-center justify-between mb-4 gap-4 flex-wrap">
        <div className="flex items-center gap-2 flex-1 max-w-xs">
          {isSearching ? (
            <svg width="12" height="12" viewBox="0 0 12 12" className="flex-shrink-0 text-[var(--color-text-dim)] animate-spin" fill="none">
              <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1" strokeDasharray="14 8" />
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
        <NotebookListToolbar
          sortBy={sortBy} sortDir={sortDir} statusFilter={statusFilter}
          onSortByChange={handleSortByChange} onSortDirChange={handleSortDirChange} onStatusFilterChange={handleStatusFilterChange}
        />
        <div className="flex items-center gap-3">
          <p className="text-[12px] text-[var(--color-text-muted)] tracking-wider">{counterText}</p>
          <button onClick={() => setModalOpen(true)} className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity">
            + upload
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={EmptyTerminal}
          title={query ? "no matching notebooks" : "no notebooks yet"}
          description={query ? "No notebooks match your search. Try a different term." : "Upload a Jupyter notebook or use the MCP tools to add notebooks via an agent."}
          action={!query ? (
            <button onClick={() => setModalOpen(true)} className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity">
              upload notebook
            </button>
          ) : undefined}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((nb) => {
            const isSelected = selectedIds.has(nb.id);
            return (
              <div key={nb.id} className="relative">
                <div className="absolute top-2 right-2 z-10" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSelect(nb.id); }}>
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
                  className={`block bg-[var(--color-bg-card)] border p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top group ${isSelected ? "border-[var(--color-border-active)]" : "border-[var(--color-border)]"}`}
                >
                  <h3 className="text-[12px] font-medium tracking-[0.15em] uppercase text-[var(--color-text)] group-hover:text-[var(--color-text)] mb-1 truncate pr-6">
                    {nb.name}
                  </h3>
                  {nb.description && (
                    <p className="text-[12px] text-[var(--color-text-muted)] mb-3 line-clamp-2">{nb.description}</p>
                  )}
                  {nb.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-3">
                      {nb.tags.slice(0, 4).map((tag) => (
                        <span key={tag} className="px-1.5 py-0.5 text-[10px] font-mono tracking-wider bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text-dim)]">{tag}</span>
                      ))}
                      {nb.tags.length > 4 && <span className="px-1.5 py-0.5 text-[10px] text-[var(--color-text-dim)]">+{nb.tags.length - 4}</span>}
                    </div>
                  )}
                  <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-dim)] tracking-wider flex-wrap">
                    <span>{nb.cell_count} cell{nb.cell_count !== 1 ? "s" : ""}</span>
                    {nb.code_cell_count > 0 && (<><span>&middot;</span><span>{nb.code_cell_count} code</span></>)}
                    {nb.kernel_name && (<><span>&middot;</span><span className="font-mono">{nb.kernel_name}</span></>)}
                    <span>&middot;</span>
                    <TimeAgo timestamp={nb.updated_at} />
                    {nb.analyzed_at && (<><span>&middot;</span><span className="text-[var(--color-success)] opacity-70">analyzed <TimeAgo timestamp={nb.analyzed_at} /></span></>)}
                    {nb.quality_score !== null && nb.quality_score !== undefined && (
                      <><span>&middot;</span><QualityBadge score={nb.quality_score} size="sm" /></>
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
          <button onClick={handleLoadMore} disabled={loadingMore} className="px-6 py-2 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-50">
            {loadingMore ? `loading... (${allItemsCount} of ${baseTotal})` : `load more (${allItemsCount} of ${baseTotal})`}
          </button>
        </div>
      )}

      {showSearchLoadMore && (
        <div className="flex justify-center mt-8">
          <button onClick={handleSearchLoadMore} disabled={loadingMoreSearch} className="px-6 py-2 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-50">
            {loadingMoreSearch ? `loading... (${searchResultsCount} of ${searchTotal})` : `load more (${searchResultsCount} of ${searchTotal})`}
          </button>
        </div>
      )}

      <NotebookUploadModal open={modalOpen} onClose={() => setModalOpen(false)} />

      <BatchActionBar
        selectedCount={selectedIds.size} allSelected={allSelected}
        onSelectAll={selectAll} onDeselectAll={deselectAll}
        onAnalyze={handleBatchAnalyze} onDelete={handleBatchDeleteRequest}
        analyzing={batchAnalyzing} deleting={batchDeleting}
      />

      <ConfirmDialog
        open={deleteConfirmOpen}
        title="delete notebooks"
        message={`This will permanently delete ${selectedIds.size} notebook${selectedIds.size !== 1 ? "s" : ""} and their files. This cannot be undone.`}
        confirmLabel="delete" cancelLabel="cancel" variant="danger"
        onConfirm={handleBatchDeleteConfirm} onCancel={() => setDeleteConfirmOpen(false)}
      />
    </>
  );
}
