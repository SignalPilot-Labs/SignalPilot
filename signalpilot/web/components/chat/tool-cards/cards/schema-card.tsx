"use client";

import { ArrowRight, ShieldAlert } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import {
  formatCount,
  type RunStep,
  type SchemaColumn,
  type SchemaResult,
} from "~/lib/chat-run-steps";
import { ProgressRail, SkeletonRows, typeDot } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";
import { GenericExpanded } from "./generic-card";

/**
 * The `schema` card (describe_table / explore_table / get_table_schema):
 * compact "analytics.fct_orders · 18 columns · 2.1M rows"; running shows
 * the table headline over ghost column rows; expanded lists every column
 * with its type dot, key chips, nullability, PII flag, comment and sample
 * values, then the outgoing and incoming foreign-key sections.
 */

const CASCADE_CAP = 24;
const TABLE_INPUT_KEYS = ["table", "table_name", "model", "relation"] as const;

/** "2143882" → "2.1M", "48210" → "48K", "812" → "812". */
export function formatCompactCount(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1e3)}K`;
  if (n >= 1_000) return `${(n / 1e3).toFixed(1)}K`;
  return formatCount(n);
}

function schemaResult(step: RunStep): SchemaResult | null {
  return step.result?.kind === "schema" ? step.result : null;
}

/** The table named in the input, for the running headline and legacy title. */
export function tableFromInput(step: RunStep): string | null {
  for (const key of TABLE_INPUT_KEYS) {
    const value = step.input?.[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

export function summarizeSchema(step: RunStep): ToolCardSummary {
  const ok = step.status !== "failed";
  const result = schemaResult(step);
  const table = result?.table ?? tableFromInput(step);
  const title = step.title || "Schema";
  if (!result) return { title, stat: table ?? null, ok };
  const count = result.columns.length;
  const parts = [`${formatCount(count)} column${count === 1 ? "" : "s"}${result.columnsTruncated ? "+" : ""}`];
  if (table) parts.unshift(table);
  if (result.rowCount != null) parts.push(`${formatCompactCount(result.rowCount)} rows`);
  return { title, stat: parts.join(" · "), ok };
}

export function SchemaRunning({ step }: ToolCardContext) {
  const table = tableFromInput(step);
  return (
    <>
      {table && (
        <div className="px-3.5 pt-3 font-mono text-[12px] text-[var(--color-text)]">{table}</div>
      )}
      <SkeletonRows columns={3} rows={6} />
      <ProgressRail label="Reading the catalog…" />
    </>
  );
}

/** "analytics.dim_customers.customer_id" → "dim_customers.customer_id". */
function shortRef(reference: string): string {
  const parts = reference.split(".");
  return parts.length > 2 ? parts.slice(-2).join(".") : reference;
}

function Chip({
  children,
  tone,
  title,
}: {
  children: ReactNode;
  tone: "accent" | "dim" | "warning";
  title?: string;
}) {
  const toneClass =
    tone === "accent"
      ? "chat-tool-accent-text border-[var(--chat-tool-accent)]/40"
      : tone === "warning"
        ? "border-[var(--color-warning)]/40 text-[var(--color-warning)]"
        : "border-[var(--color-border)] text-[var(--color-text-dim)]";
  return (
    <span
      title={title}
      className={`inline-flex flex-none items-center gap-0.5 rounded border px-1 font-mono text-[9px] leading-4 ${toneClass}`}
    >
      {children}
    </span>
  );
}

function ColumnRow({
  column,
  index,
  samples,
}: {
  column: SchemaColumn;
  index: number;
  samples: string[] | undefined;
}) {
  return (
    <div
      data-testid="chat-schema-card-row"
      className="chat-tool-cascade-in px-3.5 py-[3px] text-[11px] hover:bg-[var(--color-bg-hover)]/60"
      style={{ "--i": Math.min(index, CASCADE_CAP) } as CSSProperties}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className={`h-1.5 w-1.5 flex-none rounded-full ${typeDot(column.type)}`} aria-hidden />
        <span className="truncate font-mono text-[var(--color-text)]">{column.name}</span>
        <span className="flex-none font-mono text-[10px] text-[var(--color-text-dim)]">
          {column.type}
        </span>
        {column.primaryKey && <Chip tone="accent">PK</Chip>}
        {column.foreignKey && (
          <Chip tone="dim" title={column.foreignKey}>
            FK
            <ArrowRight className="h-2.5 w-2.5" />
            {shortRef(column.foreignKey)}
          </Chip>
        )}
        {column.nullable === true && (
          <span className="flex-none text-[10px] text-[var(--color-text-dim)]">nullable</span>
        )}
        {column.pii && (
          <Chip tone="warning" title={`PII: ${column.pii}`}>
            <ShieldAlert className="h-2.5 w-2.5" />
            PII
          </Chip>
        )}
        {column.comment && (
          <span
            className="ml-auto min-w-0 truncate text-right text-[10px] text-[var(--color-text-muted)]"
            title={column.comment}
          >
            {column.comment}
          </span>
        )}
      </div>
      {samples && samples.length > 0 && (
        <div
          data-testid="chat-schema-card-samples"
          className="truncate pl-3.5 font-mono text-[10px] text-[var(--color-text-dim)]"
          title={samples.join(", ")}
        >
          {samples.join(" · ")}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-t border-[var(--color-border)] px-3.5 py-2">
      <div className="text-[9px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
        {title}
      </div>
      <div className="mt-1 space-y-0.5 font-mono text-[10.5px] text-[var(--color-text-muted)]">
        {children}
      </div>
    </div>
  );
}

export function SchemaExpanded(context: ToolCardContext) {
  const result = schemaResult(context.step);
  if (!result) return <GenericExpanded {...context} />;
  const meta = [
    result.owner && `owner ${result.owner}`,
    result.engine,
    result.rowCount != null && `${formatCount(result.rowCount)} rows`,
  ].filter((part): part is string => Boolean(part));
  return (
    <>
      {(result.description || meta.length > 0) && (
        <div className="border-b border-[var(--color-border)] px-3.5 py-2 text-[11px]">
          {result.description && (
            <p className="text-[var(--color-text-muted)]">{result.description}</p>
          )}
          {meta.length > 0 && (
            <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
              {meta.map((part) => (
                <span key={part}>{part}</span>
              ))}
            </div>
          )}
        </div>
      )}
      <div data-testid="chat-schema-card-columns" className="max-h-80 overflow-auto py-1">
        {result.columns.map((column, index) => (
          <ColumnRow
            key={column.name}
            column={column}
            index={index}
            samples={result.sampleValues[column.name]}
          />
        ))}
        {result.columnsTruncated && (
          <div className="px-3.5 py-1 font-mono text-[10px] text-[var(--color-text-dim)]">
            + more columns not shown
          </div>
        )}
      </div>
      {result.foreignKeys.length > 0 && (
        <Section title="Outgoing FKs">
          {result.foreignKeys.map((fk) => (
            <div key={`${fk.column}>${fk.references}`} className="flex items-center gap-1.5">
              <span className="text-[var(--color-text)]">{fk.column}</span>
              <ArrowRight className="h-2.5 w-2.5 text-[var(--color-text-dim)]" />
              <span className="truncate">{fk.references}</span>
            </div>
          ))}
        </Section>
      )}
      {result.referencedBy.length > 0 && (
        <Section title="Referenced by">
          {result.referencedBy.map((ref) => (
            <div key={`${ref.table}.${ref.column}`} className="flex items-center gap-1.5">
              <span className="truncate text-[var(--color-text)]">
                {ref.table}.{ref.column}
              </span>
              <ArrowRight className="h-2.5 w-2.5 text-[var(--color-text-dim)]" />
              <span>{ref.referencesColumn}</span>
            </div>
          ))}
        </Section>
      )}
    </>
  );
}

registerToolCard({
  kind: "schema",
  Icon: iconForKind("schema"),
  accent: "schema",
  summarize: summarizeSchema,
  Running: SchemaRunning,
  Expanded: SchemaExpanded,
});
