"use client";

import type { NotebookAnalysis } from "@/lib/types";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyState, EmptyTerminal } from "@/components/ui/empty-states";

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  highlight?: boolean;
}

function MetricCard({ label, value, highlight = false }: MetricCardProps) {
  return (
    <div
      className={`bg-[var(--color-bg-card)] border p-4 ${
        highlight
          ? "border-[var(--color-error)]/40"
          : "border-[var(--color-border)]"
      }`}
    >
      <p className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-2">
        {label}
      </p>
      <div className="text-[var(--color-text-muted)]">{value}</div>
    </div>
  );
}

function ChipList({ items, emptyText }: { items: string[]; emptyText?: string }) {
  if (items.length === 0) {
    return (
      <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
        {emptyText ?? "none"}
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.slice(0, 40).map((item) => (
        <span
          key={item}
          className="px-2 py-0.5 text-[10px] font-mono tracking-wider bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text-muted)]"
        >
          {item}
        </span>
      ))}
      {items.length > 40 && (
        <span className="px-2 py-0.5 text-[10px] tracking-wider text-[var(--color-text-dim)]">
          +{items.length - 40} more
        </span>
      )}
    </div>
  );
}

interface NotebookAnalysisDisplayProps {
  analysis: NotebookAnalysis | null;
  loading: boolean;
  onAnalyze: () => void;
}

export function NotebookAnalysisDisplay({ analysis, loading, onAnalyze }: NotebookAnalysisDisplayProps) {
  if (!analysis) {
    return (
      <EmptyState
        icon={EmptyTerminal}
        title="not yet analyzed"
        description="Run analysis to extract imports, function definitions, execution order, and output summary."
        action={
          <button
            onClick={onAnalyze}
            disabled={loading}
            className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {loading ? "analyzing..." : "analyze notebook"}
          </button>
        }
      />
    );
  }

  const errorCellCount = analysis.error_cells.length;
  const gapCount = analysis.execution_order_gaps.length;

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
          analyzed <TimeAgo timestamp={analysis.analyzed_at} />
        </p>
        <button
          onClick={onAnalyze}
          disabled={loading}
          className="px-3 py-1.5 text-[11px] uppercase tracking-[0.15em] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-50"
        >
          {loading ? "re-analyzing..." : "re-analyze"}
        </button>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-px bg-[var(--color-border)]">
        {/* Cell counts */}
        <MetricCard
          label="code cells"
          value={
            <span className="text-xl font-light tabular-nums text-[var(--color-text)]">
              {analysis.cell_counts["code"] ?? 0}
            </span>
          }
        />
        <MetricCard
          label="markdown cells"
          value={
            <span className="text-xl font-light tabular-nums text-[var(--color-text)]">
              {analysis.cell_counts["markdown"] ?? 0}
            </span>
          }
        />
        <MetricCard
          label="raw cells"
          value={
            <span className="text-xl font-light tabular-nums text-[var(--color-text)]">
              {analysis.cell_counts["raw"] ?? 0}
            </span>
          }
        />
        <MetricCard
          label="total code lines"
          value={
            <span className="text-xl font-light tabular-nums text-[var(--color-text)]">
              {analysis.total_code_lines}
            </span>
          }
        />
        <MetricCard
          label="error cells"
          highlight={errorCellCount > 0}
          value={
            <span
              className={`text-xl font-light tabular-nums ${
                errorCellCount > 0 ? "text-[var(--color-error)]" : "text-[var(--color-text)]"
              }`}
            >
              {errorCellCount}
            </span>
          }
        />
        <MetricCard
          label="exec order gaps"
          highlight={gapCount > 0}
          value={
            <span
              className={`text-xl font-light tabular-nums ${
                gapCount > 0 ? "text-[var(--color-warning,orange)]" : "text-[var(--color-text)]"
              }`}
            >
              {gapCount}
            </span>
          }
        />
        {/* Kernel info */}
        <MetricCard
          label="kernel"
          value={
            <span className="text-[12px] font-mono text-[var(--color-text-muted)]">
              {analysis.kernel_info
                ? ((analysis.kernel_info["display_name"] as string) ??
                    (analysis.kernel_info["name"] as string) ??
                    "unknown")
                : "—"}
            </span>
          }
        />
        {/* Output summary */}
        <MetricCard
          label="outputs"
          value={
            <div className="space-y-0.5">
              {Object.entries(analysis.output_summary).length === 0 ? (
                <span className="text-[11px] text-[var(--color-text-dim)]">none</span>
              ) : (
                Object.entries(analysis.output_summary).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2 text-[11px]">
                    <span className="text-[var(--color-text-dim)] tracking-wider">{k}</span>
                    <span className="tabular-nums text-[var(--color-text-muted)]">{v}</span>
                  </div>
                ))
              )}
            </div>
          }
        />
      </div>

      {/* Imports */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
        <p className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-3">
          imports ({analysis.imports.length})
        </p>
        <ChipList items={analysis.imports} emptyText="no imports detected" />
      </div>

      {/* Functions defined */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
        <p className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-3">
          functions defined ({analysis.functions_defined.length})
        </p>
        <ChipList items={analysis.functions_defined} emptyText="no functions defined" />
      </div>

      {/* Execution order gaps detail */}
      {gapCount > 0 && (
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
          <p className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-3">
            execution order gaps — cells not run in sequence
          </p>
          <div className="flex flex-wrap gap-1.5">
            {analysis.execution_order_gaps.map((g) => (
              <span
                key={g}
                className="px-2 py-0.5 text-[10px] font-mono tracking-wider bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text-muted)]"
              >
                #{g}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Error cells detail */}
      {errorCellCount > 0 && (
        <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-4">
          <p className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-error)] mb-3">
            cells with errors
          </p>
          <div className="flex flex-wrap gap-1.5">
            {analysis.error_cells.map((idx) => (
              <span
                key={idx}
                className="px-2 py-0.5 text-[10px] font-mono tracking-wider bg-[var(--color-bg)] border border-[var(--color-error)]/30 text-[var(--color-error)]"
              >
                #{idx}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
