"use client";

import { useState, use, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { mutate as globalMutate } from "swr";
import { TerminalBar } from "@/components/ui/page-header";
import { NotebookCellRenderer } from "@/components/notebooks/notebook-cell";
import { NotebookAnalysisDisplay } from "@/components/notebooks/notebook-analysis";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyState, EmptyTerminal } from "@/components/ui/empty-states";
import { Skeleton } from "@/components/ui/skeleton";
import { EditableField } from "@/components/notebooks/editable-field";
import {
  useNotebook,
  useNotebookCells,
  useNotebookAnalysis,
  SWR_KEYS,
  invalidateNotebook,
  invalidateNotebooks,
} from "@/lib/hooks/use-gateway-data";
import { analyzeNotebook, deleteNotebook, updateNotebook, getNotebookDownloadUrl, getAuthHeaders } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import type { NotebookInfo } from "@/lib/types";

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

  // ── Tag editing ──────────────────────────────────────────────────────────────
  const [tagInput, setTagInput] = useState("");
  const [savingTag, setSavingTag] = useState(false);

  const handleTabKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>, currentIdx: number, tabs: { id: TabId }[]) => {
      if (e.key === "ArrowRight") {
        e.preventDefault();
        const targetIdx = (currentIdx + 1) % tabs.length;
        const targetId = tabs[targetIdx].id;
        setActiveTab(targetId);
        document.getElementById(`tab-${targetId}`)?.focus();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        const targetIdx = (currentIdx - 1 + tabs.length) % tabs.length;
        const targetId = tabs[targetIdx].id;
        setActiveTab(targetId);
        document.getElementById(`tab-${targetId}`)?.focus();
      }
    },
    []
  );

  // ── Optimistic update helper ─────────────────────────────────────────────────
  async function applyUpdate(
    patch: { name?: string; description?: string; tags?: string[] },
    optimisticNotebook: NotebookInfo,
  ) {
    await globalMutate(SWR_KEYS.notebook(id), optimisticNotebook, { revalidate: false });
    try {
      const updated = await updateNotebook(id, patch);
      await globalMutate(SWR_KEYS.notebook(id), updated, { revalidate: false });
    } catch (err) {
      console.error("Update failed:", err);
      await globalMutate(SWR_KEYS.notebook(id));
      toast("failed to update notebook", "error");
    }
  }

  // ── Tag operations ───────────────────────────────────────────────────────────
  async function addTag() {
    if (!notebook) return;
    const trimmed = tagInput.trim();
    if (!trimmed || notebook.tags.includes(trimmed)) {
      setTagInput("");
      return;
    }
    setSavingTag(true);
    setTagInput("");
    const newTags = [...notebook.tags, trimmed];
    const optimistic: NotebookInfo = { ...notebook, tags: newTags };
    await applyUpdate({ tags: newTags }, optimistic);
    setSavingTag(false);
  }

  async function removeTag(tag: string) {
    if (!notebook) return;
    const newTags = notebook.tags.filter((t) => t !== tag);
    const optimistic: NotebookInfo = { ...notebook, tags: newTags };
    await applyUpdate({ tags: newTags }, optimistic);
  }

  function handleTagInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      void addTag();
    } else if (e.key === "Escape") {
      setTagInput("");
    }
  }

  // ── Analyze / Delete ─────────────────────────────────────────────────────────
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
      {/* Inlined page header layout (PageHeader only accepts title: string, not ReactNode) */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            {/* Title row with editable name */}
            <div className="flex items-center gap-3 mb-1">
              <h1 className="leading-none text-[var(--color-text)]">
                <EditableField
                  value={notebook.name}
                  onSave={async (newName) => {
                    const trimmed = newName.trim();
                    if (!trimmed || trimmed === notebook.name) return;
                    const optimistic: NotebookInfo = { ...notebook, name: trimmed };
                    await applyUpdate({ name: trimmed }, optimistic);
                  }}
                  ariaLabel="Notebook name"
                  variant="input"
                  displayClassName="text-xl font-light tracking-wide"
                />
              </h1>
              <span className="text-[12px] leading-none tracking-[0.15em] uppercase text-[var(--color-text-muted)]">
                notebook
              </span>
            </div>

            {/* Editable description */}
            <div className="text-sm text-[var(--color-text-muted)] tracking-wider">
              <EditableField
                value={notebook.description ?? ""}
                onSave={async (newDesc) => {
                  const trimmed = newDesc.trim();
                  if (trimmed === (notebook.description ?? "")) return;
                  const optimistic: NotebookInfo = { ...notebook, description: trimmed };
                  await applyUpdate({ description: trimmed }, optimistic);
                }}
                ariaLabel="Notebook description"
                variant="textarea"
                placeholder="Add a description..."
              />
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={async () => {
                try {
                  const headers = await getAuthHeaders();
                  const res = await fetch(getNotebookDownloadUrl(id), { headers });
                  if (!res.ok) throw new Error("Download failed");
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `${notebook.name}.ipynb`;
                  a.click();
                  URL.revokeObjectURL(url);
                } catch {
                  toast("download failed", "error");
                }
              }}
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all"
            >
              download
            </button>
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
        </div>

        <div className="mt-4 h-px bg-gradient-to-r from-transparent via-[var(--color-border-hover)] to-transparent" />
      </div>

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

      {/* Tags section */}
      <div className="flex flex-wrap items-center gap-1.5 mt-2 mb-6">
        {notebook.tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-mono tracking-wider bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text-dim)]"
          >
            {tag}
            <button
              onClick={() => void removeTag(tag)}
              className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors leading-none"
              aria-label={`Remove tag ${tag}`}
            >
              ×
            </button>
          </span>
        ))}
        <input
          type="text"
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={handleTagInputKeyDown}
          onBlur={() => void addTag()}
          placeholder={savingTag ? "saving..." : "add tag..."}
          disabled={savingTag}
          className="px-1.5 py-0.5 text-[10px] font-mono tracking-wider bg-transparent border border-dashed border-[var(--color-border)] text-[var(--color-text-dim)] placeholder:text-[var(--color-text-dim)] outline-none focus:border-[var(--color-border-hover)] w-24 transition-colors disabled:opacity-50"
          aria-label="Add tag"
        />
      </div>

      {/* Tab bar */}
      <div role="tablist" className="flex items-center gap-0 border-b border-[var(--color-border)] mb-6">
        {TABS.map((tab, idx) => (
          <button
            key={tab.id}
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`tabpanel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => setActiveTab(tab.id)}
            onKeyDown={(e) => handleTabKeyDown(e, idx, TABS)}
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
        <div role="tabpanel" id="tabpanel-cells" aria-labelledby="tab-cells" className="space-y-3">
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
        <div role="tabpanel" id="tabpanel-analysis" aria-labelledby="tab-analysis">
          <NotebookAnalysisDisplay
            analysis={analysis ?? null}
            loading={analyzing || analysisLoading}
            onAnalyze={handleAnalyze}
          />
        </div>
      )}

      {/* Outputs tab */}
      {activeTab === "outputs" && (
        <div role="tabpanel" id="tabpanel-outputs" aria-labelledby="tab-outputs" className="space-y-3">
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
