"use client";

/**
 * The inspector's SQL tab: a model's raw SQL (compiled on toggle) through
 * the chat code highlighter, with copy, the file path as caption, a "Show
 * more" fold above COLLAPSE_LINES, a skeleton while loading, and a quiet
 * "not available" state for sources and unknown nodes.
 */

import React, { useMemo, useState } from "react";

import { ChatCode, CopyButton } from "~/components/chat/chat-code";
import { Skeleton } from "~/components/ui/skeleton";
import type { ModelSqlState } from "./use-dbt-map";

/** Bodies longer than this start folded. */
export const COLLAPSE_LINES = 120;

type Variant = "raw" | "compiled";

const foldable = (body: string) => body.split("\n").length > COLLAPSE_LINES;

/** Split a body at the fold: the visible head and the hidden line count. */
export function foldSql(body: string, expanded: boolean, limit = COLLAPSE_LINES) {
  const lines = body.split("\n");
  if (expanded || lines.length <= limit) return { shown: body, hidden: 0 };
  return { shown: lines.slice(0, limit).join("\n"), hidden: lines.length - limit };
}

export function InspectorSql({ state, modelName }: { state: ModelSqlState; modelName: string }) {
  const [variant, setVariant] = useState<Variant>("raw");
  const [expanded, setExpanded] = useState(false);

  const sql = state.state === "ready" ? state.sql : null;
  const hasCompiled = Boolean(sql?.compiled_sql);
  // Fall back to raw when the toggle points at a variant this model lacks.
  const active: Variant = variant === "compiled" && hasCompiled ? "compiled" : "raw";
  const body = sql ? (active === "compiled" ? sql.compiled_sql : sql.raw_sql) ?? "" : "";
  const fold = useMemo(() => foldSql(body, expanded), [body, expanded]);

  if (state.state === "loading" || state.state === "idle") {
    return (
      <div className="space-y-2 p-3" aria-busy="true" data-testid="inspector-sql-loading">
        <Skeleton className="h-2.5 w-40" />
        <div className="space-y-1.5 rounded-[8px] border border-[var(--color-border)] p-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className={`h-2.5 ${i % 3 === 0 ? "w-3/4" : i % 3 === 1 ? "w-1/2" : "w-2/3"}`} />
          ))}
        </div>
      </div>
    );
  }

  if (state.state === "error") {
    return (
      <p className="p-3 text-[11px] leading-5 text-[var(--color-error)]" data-testid="inspector-sql-error">
        The SQL for {modelName} could not be loaded.
      </p>
    );
  }

  if (!sql || !sql.raw_sql) {
    return (
      <p className="p-3 text-[11px] leading-5 text-[var(--color-text-dim)]" data-testid="inspector-sql-unavailable">
        SQL not available for this node.
      </p>
    );
  }

  const path = sql.original_file_path ?? sql.path;
  const language = sql.language === "python" ? "python" : "sql";

  return (
    <div className="flex min-h-0 flex-col p-3" data-testid="inspector-sql" data-variant={active}>
      <div className="mb-2 flex items-center gap-1">
        {hasCompiled && (
          <div role="group" aria-label="SQL variant" className="flex items-center gap-0.5 rounded-[7px] border border-[var(--color-border)] p-0.5">
            {(["raw", "compiled"] as Variant[]).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={active === v}
                onClick={() => setVariant(v)}
                className={`rounded-[5px] px-2 py-0.5 text-[9px] uppercase tracking-[0.1em] transition-colors ${
                  active === v
                    ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                    : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        )}
        <span className="ml-auto">
          <CopyButton text={body} label="Copy" />
        </span>
      </div>
      {path && (
        <div className="mb-1.5 truncate font-mono text-[9px] text-[var(--color-text-dim)]" title={path} data-testid="inspector-sql-path">
          {path}
          {sql.truncated && <span className="ml-1 text-[var(--color-warning)]">(truncated)</span>}
        </div>
      )}
      <div className="min-h-0 overflow-hidden rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)]">
        <ChatCode code={fold.shown} language={language} maxHeightClass="max-h-[60vh]" />
      </div>
      {(fold.hidden > 0 || (expanded && foldable(body))) && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1.5 self-start text-[10px] text-[var(--color-text-muted)] underline-offset-2 hover:text-[var(--color-text)] hover:underline"
          data-testid="inspector-sql-fold"
        >
          {expanded ? "Show less" : `Show more (${fold.hidden} more lines)`}
        </button>
      )}
    </div>
  );
}
