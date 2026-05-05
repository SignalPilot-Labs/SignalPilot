"use client";

import { useState, use } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { NotebookCellRenderer } from "@/components/notebooks/notebook-cell";
import { NotebookAnalysisDisplay } from "@/components/notebooks/notebook-analysis";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyState, EmptyTerminal } from "@/components/ui/empty-states";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useNotebook,
  useNotebookCells,
  useNotebookAnalysis,
  invalidateNotebook,
  invalidateNotebooks,
} from "@/lib/hooks/use-gateway-data";
import { analyzeNotebook, deleteNotebook } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

const MAX_CELLS = 200;

type TabId = "cells" | "analysis" | "outputs";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function NotebookDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();

  const { data: notebook, isLoading: nbLoading, error: nbError } = useNotebook(id);
  const { data: cells, isLoading: cellsLoading } = useNotebookCells(id);
  const { data: analysis, isLoading: analysisLoading, mutate: mutateAnalysis } = useNotebookAnalysis(id);

  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState<TabId>("cells");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleAnalyze() {
    setAnalyzing(true);
    try {
      const result = await analyzeNotebook(id);
      await mutateAnalysis(result, { revalidate: false });
      await invalidateNotebook(id);
      toast("analysis complete", "success");
    } catch (err) {
      console.error("Analyze failed:", err);
      toast("analysis failed", "error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteNotebook(id);
      await invalidateNotebooks();
      router.push("/notebooks");
    } catch (err) {
      console.error("Delete failed:", err);
      toast("failed to delete notebook", "error");
      setDeleting(false);
      // Keep the dialog open so the user sees it failed and can retry
    }
  }

  if (nbLoading) {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <Skeleton className="h-8 w-64 mb-4" />
        <Skeleton className="h-10 w-full mb-6" />
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      </div>
    );
  }

  if (nbError || !notebook) {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-6">
          <p className="text-[12px] text-[var(--color-error)] tracking-wider mb-4">
            {nbError instanceof Error ? nbError.message : "Notebook not found."}
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

  const displayedCells = (cells ?? []).slice(0, MAX_CELLS);
  const cellsTruncated = (cells?.length ?? 0) > MAX_CELLS;

  // Cells with outputs for the outputs tab
  const outputCells = displayedCells.filter(
    (c) => Array.isArray(c.outputs) && c.outputs.length > 0
  );

  const TABS: { id: TabId; label: string; count?: number }[] = [
    { id: "cells", label: "cells", count: cells?.length },
    { id: "analysis", label: "analysis" },
    { id: "outputs", label: "outputs", count: outputCells.length },
  ];

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title={notebook.name}
        subtitle="notebook"
        description={
          notebook.description ||
          `${notebook.cell_count} cell${notebook.cell_count !== 1 ? "s" : ""}${notebook.kernel_name ? ` · ${notebook.kernel_name}` : ""}`
        }
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={handleAnalyze}
              disabled={analyzing}
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-50"
            >
              {analyzing ? "analyzing..." : "analyze"}
            </button>
            <button
              onClick={() => setDeleteOpen(true)}
              disabled={deleting}
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-error)]/40 text-[var(--color-error)] hover:bg-[var(--color-error)]/10 transition-all disabled:opacity-50"
            >
              delete
            </button>
            <Link
              href="/notebooks"
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all"
            >
              &larr; all notebooks
            </Link>
          </div>
        }
      />

      <TerminalBar path={`notebooks/${id}`}>
        <div className="flex items-center gap-4 text-[11px] text-[var(--color-text-dim)] tracking-wider">
          <span>{notebook.cell_count} cells</span>
          <span>&middot;</span>
          <span>{notebook.code_cell_count} code</span>
          <span>&middot;</span>
          <span>{notebook.markdown_cell_count} markdown</span>
          {notebook.kernel_name && (
            <>
              <span>&middot;</span>
              <span className="font-mono">{notebook.kernel_name}</span>
            </>
          )}
          <span>&middot;</span>
          <span>updated <TimeAgo timestamp={notebook.updated_at} /></span>
          {notebook.analyzed_at && (
            <>
              <span>&middot;</span>
              <span className="text-[var(--color-success)]">
                analyzed <TimeAgo timestamp={notebook.analyzed_at} />
              </span>
            </>
          )}
        </div>
      </TerminalBar>

      {/* Tab bar */}
      <div className="flex items-center gap-0 border-b border-[var(--color-border)] mb-6">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-[12px] uppercase tracking-[0.15em] transition-all border-b-2 -mb-px ${
              activeTab === tab.id
                ? "border-[var(--color-text)] text-[var(--color-text)]"
                : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="ml-2 text-[10px] text-[var(--color-text-dim)]">
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Cells tab */}
      {activeTab === "cells" && (
        <div className="space-y-3">
          {cellsLoading && (
            <>
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </>
          )}
          {!cellsLoading && displayedCells.length === 0 && (
            <EmptyState
              icon={EmptyTerminal}
              title="no cells"
              description="This notebook has no cells."
            />
          )}
          {!cellsLoading && cellsTruncated && (
            <div className="px-4 py-2 border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[11px] text-[var(--color-text-dim)] tracking-wider">
              showing first {MAX_CELLS} of {cells!.length} cells
            </div>
          )}
          {!cellsLoading &&
            displayedCells.map((cell) => (
              <NotebookCellRenderer key={cell.index} cell={cell} />
            ))}
        </div>
      )}

      {/* Analysis tab */}
      {activeTab === "analysis" && (
        <NotebookAnalysisDisplay
          analysis={analysis ?? null}
          loading={analyzing || analysisLoading}
          onAnalyze={handleAnalyze}
        />
      )}

      {/* Outputs tab */}
      {activeTab === "outputs" && (
        <div className="space-y-3">
          {cellsLoading && (
            <>
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </>
          )}
          {!cellsLoading && outputCells.length === 0 && (
            <EmptyState
              icon={EmptyTerminal}
              title="no outputs"
              description="No cells in this notebook have outputs."
            />
          )}
          {!cellsLoading &&
            outputCells.map((cell) => (
              <NotebookCellRenderer key={cell.index} cell={cell} outputsOnly />
            ))}
        </div>
      )}

      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={deleteOpen}
        title="delete notebook"
        message={`Delete "${notebook.name}"? This action cannot be undone. The notebook file and all analysis results will be permanently removed.`}
        confirmLabel="delete"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}
