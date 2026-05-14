"use client";

import { useState, useRef, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { Skeleton } from "@/components/ui/skeleton";
import { TerminalBar } from "@/components/ui/page-header";
import { getNotebookComparison, getNotebooks, searchNotebooks } from "@/lib/api";
import type { NotebookComparison, CellDiff, NotebookInfo } from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────────

// Single constant for both summary bar and cell-diff badge styling (they share the same values).
const DIFF_STATUS_STYLES: Record<CellDiff["status"], string> = {
  added: "bg-green-950/30 border-green-900 text-[var(--color-success)]",
  removed: "bg-red-950/30 border-red-900 text-[var(--color-error)]",
  modified: "bg-amber-950/30 border-amber-900 text-[var(--color-warning)]",
  unchanged: "bg-[var(--color-bg)] text-[var(--color-text-dim)] border border-[var(--color-border)]",
};

// Left-border row coloring for cell diff list items (background only, no text).
const STATUS_ROW_STYLES: Record<CellDiff["status"], string> = {
  added: "bg-green-950/30 border-green-900",
  removed: "bg-red-950/30 border-red-900",
  modified: "bg-amber-950/30 border-amber-900",
  unchanged: "bg-transparent border-[var(--color-border)]",
};

const SEARCH_DEBOUNCE_MS = 300;

// ── Loading skeleton ─────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="p-8 max-w-[1400px] animate-fade-in space-y-4">
      <Skeleton className="h-8 w-96" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

// ── Notebook selector (when only left param is provided) ─────────────────────

interface NotebookSelectorProps {
  leftId: string;
  leftName: string | null;
}

function NotebookSelector({ leftId, leftName }: NotebookSelectorProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data: searchResults, isLoading: searchLoading } = useSWR(
    debouncedQuery.trim() ? `notebooks-search-${debouncedQuery}` : "notebooks-list-selector",
    () =>
      debouncedQuery.trim()
        ? searchNotebooks(debouncedQuery.trim(), 20, 0)
        : getNotebooks(20, 0),
    { dedupingInterval: 10_000 },
  );

  const handleQueryChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      setQuery(val);
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => setDebouncedQuery(val), SEARCH_DEBOUNCE_MS);
    },
    [],
  );

  const handleSelect = useCallback(
    (rightId: string) => {
      router.push(`/notebooks/compare?left=${encodeURIComponent(leftId)}&right=${encodeURIComponent(rightId)}`);
    },
    [leftId, router],
  );

  const notebooks = searchResults?.items ?? [];

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-xl font-light tracking-wide text-[var(--color-text)]">
            compare notebook
          </h1>
        </div>
        <p className="text-sm text-[var(--color-text-muted)] tracking-wider mt-1">
          {leftName ? (
            <>
              Comparing <span className="text-[var(--color-text)]">{leftName}</span> — select a notebook to compare against.
            </>
          ) : (
            "Select a second notebook to compare."
          )}
        </p>
        <div className="mt-4 h-px bg-gradient-to-r from-transparent via-[var(--color-border-hover)] to-transparent" />
      </div>

      <TerminalBar path={`notebooks/compare?left=${leftId}`} />

      <div className="mt-6 max-w-xl">
        <label
          htmlFor="notebook-search"
          className="block text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-2"
        >
          search notebooks
        </label>
        <input
          id="notebook-search"
          type="text"
          value={query}
          onChange={handleQueryChange}
          placeholder="Filter by name..."
          className="w-full px-3 py-2 text-sm bg-[var(--color-bg-card)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-border-hover)] focus:border-[var(--color-border-hover)] transition-colors"
          aria-label="Search notebooks"
          aria-controls="notebook-selector-list"
        />
      </div>

      <div
        id="notebook-selector-list"
        role="list"
        className="mt-3 max-w-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] divide-y divide-[var(--color-border)]"
        aria-label="Available notebooks"
      >
        {searchLoading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : notebooks.length === 0 ? (
          <div className="p-4 text-sm text-[var(--color-text-dim)] tracking-wider">
            No notebooks found.
          </div>
        ) : (
          notebooks
            .filter((nb) => nb.id !== leftId)
            .map((nb) => (
              <NotebookSelectorRow
                key={nb.id}
                notebook={nb}
                onSelect={handleSelect}
              />
            ))
        )}
      </div>

      <div className="mt-6">
        <Link
          href="/notebooks"
          className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
        >
          &larr; all notebooks
        </Link>
      </div>
    </div>
  );
}

interface NotebookSelectorRowProps {
  notebook: NotebookInfo;
  onSelect: (id: string) => void;
}

function NotebookSelectorRow({ notebook, onSelect }: NotebookSelectorRowProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onSelect(notebook.id);
      }
    },
    [notebook.id, onSelect],
  );

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(notebook.id)}
      onKeyDown={handleKeyDown}
      className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-[var(--color-bg-hover)] focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-[var(--color-border-hover)] outline-none transition-colors"
      aria-label={`Compare with ${notebook.name}`}
    >
      <div>
        <p className="text-sm text-[var(--color-text)] tracking-wider">{notebook.name}</p>
        <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider mt-0.5">
          {notebook.cell_count} cells &middot; {notebook.code_cell_count} code
          {notebook.kernel_name && <> &middot; {notebook.kernel_name}</>}
        </p>
      </div>
      <svg
        className="w-4 h-4 text-[var(--color-text-dim)]"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.5}
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
      </svg>
    </div>
  );
}

// ── Same-notebook guard ──────────────────────────────────────────────────────

function SameNotebookError({ id }: { id: string }) {
  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-6">
        <p className="text-[12px] text-[var(--color-error)] tracking-wider mb-4">
          Cannot compare a notebook with itself. Select a different notebook for the right side.
        </p>
        <Link
          href={`/notebooks/compare?left=${encodeURIComponent(id)}`}
          className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
        >
          &larr; select a notebook
        </Link>
      </div>
    </div>
  );
}

// ── Comparison view ──────────────────────────────────────────────────────────

interface ComparisonViewProps {
  leftId: string;
  rightId: string;
}

function ComparisonView({ leftId, rightId }: ComparisonViewProps) {
  const swrKey = `notebooks-compare-${leftId}-${rightId}`;

  const { data: comparison, isLoading, error } = useSWR<NotebookComparison>(
    swrKey,
    () => getNotebookComparison(leftId, rightId),
    { dedupingInterval: 60_000, revalidateOnFocus: false },
  );

  if (isLoading) {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in space-y-4">
        <Skeleton className="h-8 w-96" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-40 w-full" />
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !comparison) {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-6">
          <p className="text-[12px] text-[var(--color-error)] tracking-wider mb-4">
            {error instanceof Error ? error.message : "Failed to load comparison."}
          </p>
          <Link
            href="/notebooks"
            className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            &larr; all notebooks
          </Link>
        </div>
      </div>
    );
  }

  const { left_notebook, right_notebook, analysis, cell_diffs, summary } = comparison;

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-light tracking-wide text-[var(--color-text)] truncate">
              <span className="text-[var(--color-text-dim)]">{left_notebook.name}</span>
              <span className="mx-3 text-[var(--color-text-muted)]">vs</span>
              <span className="text-[var(--color-text-dim)]">{right_notebook.name}</span>
            </h1>
            <p className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-muted)] mt-1">
              notebook comparison
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Link
              href={`/notebooks/${leftId}`}
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all"
            >
              left
            </Link>
            <Link
              href={`/notebooks/${rightId}`}
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all"
            >
              right
            </Link>
            <Link
              href="/notebooks"
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all"
            >
              &larr; all notebooks
            </Link>
          </div>
        </div>
        <div className="mt-4 h-px bg-gradient-to-r from-transparent via-[var(--color-border-hover)] to-transparent" />
      </div>

      <TerminalBar path={`notebooks/${leftId}/compare/${rightId}`} />

      {/* Summary bar */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mr-1">
          summary
        </span>
        <span className={`px-2.5 py-1 text-[11px] font-mono tracking-wider border ${DIFF_STATUS_STYLES.added}`}>
          {summary.added} added
        </span>
        <span className={`px-2.5 py-1 text-[11px] font-mono tracking-wider border ${DIFF_STATUS_STYLES.removed}`}>
          {summary.removed} removed
        </span>
        <span className={`px-2.5 py-1 text-[11px] font-mono tracking-wider border ${DIFF_STATUS_STYLES.modified}`}>
          {summary.modified} modified
        </span>
        <span className={`px-2.5 py-1 text-[11px] font-mono tracking-wider border ${DIFF_STATUS_STYLES.unchanged}`}>
          {summary.unchanged} unchanged
        </span>
      </div>

      {/* Metadata comparison */}
      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        <NotebookMetaCard notebook={left_notebook} side="left" />
        <NotebookMetaCard notebook={right_notebook} side="right" />
      </div>

      {/* Analysis comparison */}
      {analysis !== null && (
        <div className="mt-6 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="px-4 py-3 border-b border-[var(--color-border)]">
            <h2 className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
              analysis diff
            </h2>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Imports diff */}
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-2">
                imports
              </h3>
              <div className="space-y-1">
                {analysis.added_imports.length === 0 && analysis.removed_imports.length === 0 ? (
                  <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">no changes</p>
                ) : (
                  <>
                    {analysis.added_imports.map((imp) => (
                      <div
                        key={`add-imp-${imp}`}
                        className="flex items-center gap-1.5 font-mono text-[11px] text-[var(--color-success)]"
                      >
                        <span aria-hidden="true">+</span>
                        <span>{imp}</span>
                      </div>
                    ))}
                    {analysis.removed_imports.map((imp) => (
                      <div
                        key={`rem-imp-${imp}`}
                        className="flex items-center gap-1.5 font-mono text-[11px] text-[var(--color-error)]"
                      >
                        <span aria-hidden="true">-</span>
                        <span>{imp}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </div>

            {/* Functions diff */}
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-2">
                functions
              </h3>
              <div className="space-y-1">
                {analysis.added_functions.length === 0 && analysis.removed_functions.length === 0 ? (
                  <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">no changes</p>
                ) : (
                  <>
                    {analysis.added_functions.map((fn) => (
                      <div
                        key={`add-fn-${fn}`}
                        className="flex items-center gap-1.5 font-mono text-[11px] text-[var(--color-success)]"
                      >
                        <span aria-hidden="true">+</span>
                        <span>{fn}</span>
                      </div>
                    ))}
                    {analysis.removed_functions.map((fn) => (
                      <div
                        key={`rem-fn-${fn}`}
                        className="flex items-center gap-1.5 font-mono text-[11px] text-[var(--color-error)]"
                      >
                        <span aria-hidden="true">-</span>
                        <span>{fn}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </div>

            {/* Code lines */}
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-2">
                code lines
              </h3>
              <div className="flex items-center gap-4 text-sm">
                <span className="text-[var(--color-text-dim)] font-mono">
                  {analysis.left_code_lines.toLocaleString()}
                </span>
                <span className="text-[var(--color-text-muted)]">&rarr;</span>
                <span
                  className={
                    analysis.right_code_lines > analysis.left_code_lines
                      ? "text-[var(--color-success)] font-mono"
                      : analysis.right_code_lines < analysis.left_code_lines
                        ? "text-[var(--color-error)] font-mono"
                        : "text-[var(--color-text-dim)] font-mono"
                  }
                >
                  {analysis.right_code_lines.toLocaleString()}
                </span>
                {analysis.right_code_lines !== analysis.left_code_lines && (
                  <span className="text-[11px] text-[var(--color-text-dim)]">
                    ({analysis.right_code_lines > analysis.left_code_lines ? "+" : ""}
                    {(analysis.right_code_lines - analysis.left_code_lines).toLocaleString()})
                  </span>
                )}
              </div>
            </div>

            {/* Error cells */}
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-2">
                error cells
              </h3>
              <div className="flex items-start gap-6 text-[12px]">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">left</p>
                  {analysis.left_error_cells.length === 0 ? (
                    <span className="text-[var(--color-text-dim)]">none</span>
                  ) : (
                    <span className="font-mono text-[var(--color-error)]">
                      {analysis.left_error_cells.join(", ")}
                    </span>
                  )}
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">right</p>
                  {analysis.right_error_cells.length === 0 ? (
                    <span className="text-[var(--color-text-dim)]">none</span>
                  ) : (
                    <span className="font-mono text-[var(--color-error)]">
                      {analysis.right_error_cells.join(", ")}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cell diffs */}
      <div className="mt-6 border border-[var(--color-border)]">
        <div className="px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg-card)] flex items-center justify-between">
          <h2 className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
            cell diff
          </h2>
          <span className="text-[11px] text-[var(--color-text-dim)] font-mono">
            {cell_diffs.length} cells
          </span>
        </div>
        <div
          className="max-h-[600px] overflow-y-auto divide-y divide-[var(--color-border)]"
          role="list"
          aria-label="Cell differences"
        >
          {cell_diffs.length === 0 ? (
            <div className="px-4 py-6 text-sm text-[var(--color-text-dim)] tracking-wider text-center">
              No cells to compare.
            </div>
          ) : (
            cell_diffs.map((diff) => (
              <CellDiffRow key={diff.index} diff={diff} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// ── Notebook metadata card ───────────────────────────────────────────────────

interface NotebookMetaCardProps {
  notebook: NotebookInfo;
  side: "left" | "right";
}

function NotebookMetaCard({ notebook, side }: NotebookMetaCardProps) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
      <p className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-muted)] mb-2">
        {side} notebook
      </p>
      <p className="text-sm font-light text-[var(--color-text)] tracking-wider truncate mb-3" title={notebook.name}>
        {notebook.name}
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[11px]">
        <MetaRow label="cells" value={String(notebook.cell_count)} />
        <MetaRow label="code cells" value={String(notebook.code_cell_count)} />
        <MetaRow label="markdown cells" value={String(notebook.markdown_cell_count)} />
        <MetaRow label="kernel" value={notebook.kernel_name ?? "—"} />
      </div>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="text-[var(--color-text-dim)] tracking-wider">{label}</span>
      <span className="font-mono text-[var(--color-text)]">{value}</span>
    </>
  );
}

// ── Cell diff row ────────────────────────────────────────────────────────────

interface CellDiffRowProps {
  diff: CellDiff;
}

function CellDiffRow({ diff }: CellDiffRowProps) {
  const containerClass = `flex items-center gap-3 px-4 py-2.5 border-l-2 transition-colors ${STATUS_ROW_STYLES[diff.status]}`;
  const badgeClass = `px-1.5 py-0.5 text-[10px] font-mono tracking-wider border ${DIFF_STATUS_STYLES[diff.status]}`;

  return (
    <div role="listitem" className={containerClass}>
      <span className="font-mono text-[11px] text-[var(--color-text-dim)] w-8 shrink-0 text-right">
        {diff.index}
      </span>
      <span className={badgeClass}>{diff.status}</span>
      <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider shrink-0">
        {diff.left_type ?? diff.right_type ?? "—"}
      </span>
      <div className="flex items-center gap-3 ml-auto text-[11px] text-[var(--color-text-muted)] font-mono">
        {diff.left_source_lines !== null && (
          <span title="left source lines">{diff.left_source_lines}L</span>
        )}
        {diff.left_source_lines !== null && diff.right_source_lines !== null && (
          <span className="text-[var(--color-text-muted)]">&rarr;</span>
        )}
        {diff.right_source_lines !== null && (
          <span title="right source lines">{diff.right_source_lines}L</span>
        )}
      </div>
    </div>
  );
}

// ── Error state ──────────────────────────────────────────────────────────────

function NoParamsError() {
  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-6">
        <p className="text-[12px] text-[var(--color-error)] tracking-wider mb-4">
          Missing notebook IDs. Provide at least a <code className="font-mono">left</code> query parameter.
        </p>
        <Link
          href="/notebooks"
          className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
        >
          &larr; all notebooks
        </Link>
      </div>
    </div>
  );
}

// ── Inner page (uses useSearchParams — must be inside Suspense) ──────────────

function ComparePageInner() {
  const searchParams = useSearchParams();
  const leftId = searchParams.get("left");
  const rightId = searchParams.get("right");

  // (a) No params → error
  if (!leftId) {
    return <NoParamsError />;
  }

  // (b) Same ID on both sides → guard
  if (rightId && leftId === rightId) {
    return <SameNotebookError id={leftId} />;
  }

  // (c) Only left → notebook selector
  if (!rightId) {
    return <LeftSideLoader leftId={leftId} />;
  }

  // (d) Both params → comparison view
  return <ComparisonView leftId={leftId} rightId={rightId} />;
}

// ── Page root ────────────────────────────────────────────────────────────────

export default function NotebookComparePage() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <ComparePageInner />
    </Suspense>
  );
}

// Separate component so we can load left notebook name for the selector UI
function LeftSideLoader({ leftId }: { leftId: string }) {
  const { data: leftNotebook } = useSWR<import("@/lib/types").NotebookInfo>(
    `notebook-${leftId}`,
    () => import("@/lib/api").then((m) => m.getNotebook(leftId)),
    { dedupingInterval: 60_000 },
  );

  return (
    <NotebookSelector
      leftId={leftId}
      leftName={leftNotebook?.name ?? null}
    />
  );
}
