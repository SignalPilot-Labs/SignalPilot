"use client";

const SORT_OPTIONS: { label: string; value: string }[] = [
  { label: "Last Updated", value: "updated_at" },
  { label: "Date Created", value: "created_at" },
  { label: "Name", value: "name" },
  { label: "Cell Count", value: "cell_count" },
];

const STATUS_OPTIONS: { label: string; value: string }[] = [
  { label: "All", value: "all" },
  { label: "Analyzed", value: "analyzed" },
  { label: "Pending", value: "pending" },
];

export interface NotebookListToolbarProps {
  sortBy: string;
  sortDir: string;
  statusFilter: string;
  onSortByChange: (value: string) => void;
  onSortDirChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
}

export function NotebookListToolbar({
  sortBy,
  sortDir,
  statusFilter,
  onSortByChange,
  onSortDirChange,
  onStatusFilterChange,
}: NotebookListToolbarProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Sort dropdown */}
      <select
        value={sortBy}
        onChange={(e) => onSortByChange(e.target.value)}
        className="text-[12px] uppercase tracking-[0.15em] bg-transparent border border-[var(--color-border)] text-[var(--color-text-muted)] px-2 py-1 cursor-pointer hover:border-[var(--color-border-hover)] transition-colors outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
        aria-label="Sort by"
      >
        {SORT_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Sort direction toggle */}
      <button
        type="button"
        onClick={() => onSortDirChange(sortDir === "desc" ? "asc" : "desc")}
        className="text-[12px] uppercase tracking-[0.15em] bg-transparent border border-[var(--color-border)] text-[var(--color-text-muted)] px-2 py-1 hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
        aria-label={sortDir === "desc" ? "Sort descending — click to sort ascending" : "Sort ascending — click to sort descending"}
      >
        {sortDir === "desc" ? "↓" : "↑"}
      </button>

      {/* Status filter pills */}
      <div className="flex items-center gap-1.5" role="group" aria-label="Filter by status">
        {STATUS_OPTIONS.map((opt) => {
          const isActive = statusFilter === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onStatusFilterChange(opt.value)}
              className={[
                "text-[12px] uppercase tracking-[0.15em] px-2.5 py-1 transition-colors focus-visible:ring-1 focus-visible:ring-[var(--color-text)]",
                isActive
                  ? "bg-[var(--color-text)] text-[var(--color-bg)] border border-transparent"
                  : "border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] bg-transparent",
              ].join(" ")}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
