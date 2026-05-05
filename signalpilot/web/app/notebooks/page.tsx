"use client";

import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { NotebookList } from "@/components/notebooks/notebook-list";
import { TopImportsChart } from "@/components/notebooks/top-imports-chart";
import { useNotebooks, useNotebooksSummary } from "@/lib/hooks/use-gateway-data";
import { Skeleton } from "@/components/ui/skeleton";

export default function NotebooksPage() {
  const { data, isLoading, error } = useNotebooks();
  const { data: summary, isLoading: summaryLoading } = useNotebooksSummary();

  // Only show summary cards when there are notebooks to summarize
  const showSummary = summaryLoading || (summary !== undefined && summary.total_notebooks > 0);

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="notebooks"
        subtitle="jupyter"
        description="Upload and analyze Jupyter notebooks. View cells, outputs, and analysis results."
      />
      <TerminalBar path="notebooks --list" />

      {/* Summary stat cards */}
      {showSummary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {summaryLoading ? (
            <>
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </>
          ) : summary !== undefined ? (
            <>
              <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
                <p className="text-[11px] uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
                  notebooks
                </p>
                <p className="text-2xl font-light text-[var(--color-text)]">
                  {summary.total_notebooks.toLocaleString()}
                </p>
              </div>
              <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
                <p className="text-[11px] uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
                  cells analyzed
                </p>
                <p className="text-2xl font-light text-[var(--color-text)]">
                  {summary.total_cells.toLocaleString()}
                </p>
                <p className="text-[11px] text-[var(--color-text-dim)] mt-1">
                  {summary.analyzed_count} / {summary.total_notebooks} analyzed
                </p>
              </div>
              <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
                <p className="text-[11px] uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
                  error cells
                </p>
                <p className="text-2xl font-light text-[var(--color-text)]">
                  {summary.total_error_cells.toLocaleString()}
                </p>
                <p className="text-[11px] text-[var(--color-text-dim)] mt-1">
                  {summary.notebooks_with_errors} notebooks affected
                </p>
              </div>
              <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
                <p className="text-[11px] uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
                  code lines
                </p>
                <p className="text-2xl font-light text-[var(--color-text)]">
                  {summary.total_code_lines.toLocaleString()}
                </p>
              </div>
            </>
          ) : null}
        </div>
      )}

      {summary?.top_imports && summary.top_imports.length > 0 && (
        <TopImportsChart imports={summary.top_imports} />
      )}

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}

      {error && (
        <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-6">
          <p className="text-[12px] text-[var(--color-error)] tracking-wider">
            failed to load notebooks: {error instanceof Error ? error.message : "unknown error"}
          </p>
        </div>
      )}

      {!isLoading && !error && (
        <NotebookList notebooks={data?.items ?? []} total={data?.total ?? 0} />
      )}
    </div>
  );
}
