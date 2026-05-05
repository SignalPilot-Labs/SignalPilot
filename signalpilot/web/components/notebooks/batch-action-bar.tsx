"use client";

export interface BatchActionBarProps {
  selectedCount: number;
  allSelected: boolean;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onAnalyze: () => void;
  onDelete: () => void;
  analyzing: boolean;
  deleting: boolean;
}

export function BatchActionBar({
  selectedCount,
  allSelected,
  onSelectAll,
  onDeselectAll,
  onAnalyze,
  onDelete,
  analyzing,
  deleting,
}: BatchActionBarProps) {
  if (selectedCount === 0) return null;

  const busy = analyzing || deleting;

  return (
    <div
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-3 bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-2xl"
      role="toolbar"
      aria-label="Batch actions"
    >
      <span className="text-[12px] text-[var(--color-text-muted)] tracking-wider whitespace-nowrap">
        {selectedCount} selected
      </span>

      <div className="w-px h-4 bg-[var(--color-border)]" aria-hidden="true" />

      <button
        onClick={allSelected ? onDeselectAll : onSelectAll}
        disabled={busy}
        className="text-[11px] uppercase tracking-[0.12em] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-border-hover)]"
      >
        {allSelected ? "deselect all" : "select all"}
      </button>

      <div className="w-px h-4 bg-[var(--color-border)]" aria-hidden="true" />

      <button
        onClick={onAnalyze}
        disabled={busy}
        className="px-3 py-1.5 text-[11px] uppercase tracking-[0.12em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-border-hover)]"
      >
        {analyzing ? "analyzing..." : "analyze selected"}
      </button>

      <button
        onClick={onDelete}
        disabled={busy}
        className="px-3 py-1.5 text-[11px] uppercase tracking-[0.12em] border border-[var(--color-error)]/40 text-[var(--color-error)]/80 hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-error)]"
      >
        {deleting ? "deleting..." : "delete selected"}
      </button>
    </div>
  );
}
