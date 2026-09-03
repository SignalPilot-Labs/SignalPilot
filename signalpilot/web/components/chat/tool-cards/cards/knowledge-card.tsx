"use client";

import type { CSSProperties } from "react";
import type { KnowledgeDoc, KnowledgeResult, RunStep } from "~/lib/chat-run-steps";
import { InputPills, ProgressRail, SkeletonRows } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Knowledge card: `search_knowledge` / `get_knowledge` / `read_knowledge`.
 * The query while running, then the matched docs with scope and category
 * chips and a two-line snippet each.
 */

const QUERY_INPUT_KEYS = ["query", "ids", "scope", "category", "ref"] as const;

/** Cascade stagger cap so a long list never waits on its tail. */
const CASCADE_CAP = 24;

function knowledgeResult(step: RunStep): KnowledgeResult | null {
  return step.result?.kind === "knowledge" ? step.result : null;
}

function inputQuery(step: RunStep): string | null {
  const raw = step.input?.query;
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
}

export function summarizeKnowledge(step: RunStep): ToolCardSummary {
  const result = knowledgeResult(step);
  const failed = step.status === "failed";
  const mode = result?.mode ?? (step.tool === "search_knowledge" ? "search" : null);
  const title = mode === "search" ? "Searched knowledge" : "Knowledge";
  if (!result) return { title, stat: null, ok: !failed };
  const count = result.total || result.docs.length;
  const parts = [`${count} ${count === 1 ? "doc" : "docs"}`];
  const query = result.query ?? inputQuery(step);
  if (query) parts.push(`for "${query}"`);
  return { title, stat: parts.join(" "), ok: !failed };
}

export function KnowledgeRunning({ step }: ToolCardContext) {
  return (
    <div data-testid="chat-knowledge-card">
      <div className="px-3.5 pt-3">
        <InputPills step={step} keys={QUERY_INPUT_KEYS} />
      </div>
      <SkeletonRows columns={1} rows={3} />
      <ProgressRail label="Searching knowledge…" />
    </div>
  );
}

function Chip({ children }: { children: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-px text-[10px] text-[var(--color-text-muted)]">
      {children}
    </span>
  );
}

function DocRow({ doc, index }: { doc: KnowledgeDoc; index: number }) {
  return (
    <li
      data-testid="chat-knowledge-doc"
      className="chat-tool-cascade-in px-3.5 py-2.5"
      style={{ "--i": Math.min(index, CASCADE_CAP) } as CSSProperties}
    >
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="min-w-0 truncate text-[12px] font-medium text-[var(--color-text)]">
          {doc.title}
        </span>
        <span className="flex flex-none gap-1">
          {doc.scope && <Chip>{doc.scope}</Chip>}
          {doc.category && <Chip>{doc.category}</Chip>}
        </span>
        {doc.id && (
          <span className="ml-auto flex-none font-mono text-[10px] text-[var(--color-text-dim)]">
            {doc.id}
          </span>
        )}
      </div>
      {doc.snippet && (
        <p className="mt-1 line-clamp-2 text-[11.5px] leading-5 text-[var(--color-text-muted)]">
          {doc.snippet}
        </p>
      )}
    </li>
  );
}

export function KnowledgeExpanded({ step }: ToolCardContext) {
  const result = knowledgeResult(step);
  if (!result) {
    // Legacy completion: only the query is known.
    return (
      <div data-testid="chat-knowledge-card" className="px-3.5 py-3">
        <InputPills step={step} keys={QUERY_INPUT_KEYS} />
      </div>
    );
  }
  const hidden = result.docsTruncated ? Math.max(0, result.total - result.docs.length) : 0;
  return (
    <div data-testid="chat-knowledge-card">
      {result.docs.length === 0 ? (
        <div className="px-3.5 py-3 text-[11.5px] text-[var(--color-text-dim)]">
          No matching knowledge.
        </div>
      ) : (
        <ul className="divide-y divide-[var(--color-border)]">
          {result.docs.map((doc, index) => (
            <DocRow key={doc.id ?? `${doc.title}-${index}`} doc={doc} index={index} />
          ))}
        </ul>
      )}
      {result.docsTruncated && (
        <div className="border-t border-[var(--color-border)] px-3.5 py-1.5 text-[10px] text-[var(--color-text-dim)]">
          +{hidden || "more"} more
        </div>
      )}
    </div>
  );
}

registerToolCard({
  kind: "knowledge",
  Icon: iconForKind("knowledge"),
  accent: "knowledge",
  summarize: summarizeKnowledge,
  Running: KnowledgeRunning,
  Expanded: KnowledgeExpanded,
});
