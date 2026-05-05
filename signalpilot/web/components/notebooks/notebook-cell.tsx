"use client";

import type { NotebookCell } from "@/lib/types";

const CELL_TYPE_COLORS: Record<string, string> = {
  code: "var(--color-success)",
  markdown: "var(--color-text-dim)",
  raw: "var(--color-text-dim)",
};

function resolveSource(source: string | string[]): string {
  if (Array.isArray(source)) return source.join("");
  return source;
}

interface CellOutput {
  output_type?: string;
  text?: string | string[];
  data?: Record<string, string | string[]>;
  traceback?: string[];
  name?: string;
}

function renderOutput(output: unknown, idx: number) {
  if (!output || typeof output !== "object") return null;
  const o = output as CellOutput;
  const outputType = o.output_type ?? "";

  // Error output — red traceback
  if (outputType === "error") {
    const lines = Array.isArray(o.traceback) ? o.traceback.join("\n") : "";
    return (
      <pre
        key={idx}
        className="mt-1 px-3 py-2 text-[11px] font-mono leading-relaxed text-[var(--color-error)] bg-[var(--color-bg)] border border-[var(--color-error)]/20 overflow-x-auto whitespace-pre-wrap"
      >
        {lines || "Error"}
      </pre>
    );
  }

  // Stream output (stdout/stderr)
  if (outputType === "stream") {
    const text = Array.isArray(o.text) ? o.text.join("") : (o.text ?? "");
    return (
      <pre
        key={idx}
        className="mt-1 px-3 py-2 text-[11px] font-mono leading-relaxed text-[var(--color-text-muted)] bg-[var(--color-bg)] border border-[var(--color-border)] overflow-x-auto whitespace-pre-wrap"
      >
        {text}
      </pre>
    );
  }

  // execute_result / display_data
  if (outputType === "execute_result" || outputType === "display_data") {
    const data = o.data ?? {};
    const plain = data["text/plain"];
    const text = Array.isArray(plain) ? plain.join("") : (plain ?? "");
    if (!text) return null;
    return (
      <pre
        key={idx}
        className="mt-1 px-3 py-2 text-[11px] font-mono leading-relaxed text-[var(--color-text-muted)] bg-[var(--color-bg)] border border-[var(--color-border)] overflow-x-auto whitespace-pre-wrap"
      >
        {text}
      </pre>
    );
  }

  return null;
}

export function NotebookCellRenderer({ cell, outputsOnly = false }: { cell: NotebookCell; outputsOnly?: boolean }) {
  const source = resolveSource(cell.source);
  const typeColor = CELL_TYPE_COLORS[cell.cell_type] ?? "var(--color-text-dim)";
  const outputs = Array.isArray(cell.outputs) ? cell.outputs : [];

  if (outputsOnly) {
    if (outputs.length === 0) return null;
    return (
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <div className="px-3 py-1.5 border-b border-[var(--color-border)] flex items-center gap-2">
          <span className="text-[10px] font-mono text-[var(--color-text-dim)] tracking-wider">
            [{cell.execution_count ?? " "}]
          </span>
          <span className="text-[10px] uppercase tracking-[0.15em]" style={{ color: typeColor }}>
            {cell.cell_type}
          </span>
        </div>
        <div className="px-3 py-2">
          {outputs.map((o, i) => renderOutput(o, i))}
        </div>
      </div>
    );
  }

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      {/* Cell header */}
      <div className="px-3 py-1.5 border-b border-[var(--color-border)] flex items-center gap-2 bg-[var(--color-bg)]">
        {cell.cell_type === "code" && (
          <span className="text-[10px] font-mono text-[var(--color-text-dim)] tracking-wider min-w-[2rem]">
            [{cell.execution_count ?? " "}]
          </span>
        )}
        <span className="text-[10px] uppercase tracking-[0.15em]" style={{ color: typeColor }}>
          {cell.cell_type}
        </span>
        <span className="ml-auto text-[10px] text-[var(--color-text-dim)] font-mono tracking-wider">
          #{cell.index}
        </span>
      </div>

      {/* Cell source */}
      <div className="px-3 py-2">
        {cell.cell_type === "code" && (
          <pre className="text-[12px] font-mono leading-relaxed text-[var(--color-text-muted)] overflow-x-auto whitespace-pre">
            <code>{source}</code>
          </pre>
        )}
        {cell.cell_type === "markdown" && (
          <div className="text-[12px] leading-relaxed text-[var(--color-text-muted)] whitespace-pre-wrap font-sans">
            {source}
          </div>
        )}
        {cell.cell_type === "raw" && (
          <pre className="text-[12px] font-mono leading-relaxed text-[var(--color-text-dim)] overflow-x-auto whitespace-pre-wrap opacity-70">
            {source}
          </pre>
        )}
        {!["code", "markdown", "raw"].includes(cell.cell_type) && (
          <pre className="text-[12px] font-mono leading-relaxed text-[var(--color-text-dim)] overflow-x-auto whitespace-pre-wrap">
            {source}
          </pre>
        )}
      </div>

      {/* Outputs */}
      {outputs.length > 0 && (
        <div className="px-3 pb-2 border-t border-[var(--color-border)]">
          <div className="pt-2">
            {outputs.map((o, i) => renderOutput(o, i))}
          </div>
        </div>
      )}
    </div>
  );
}
