"use client";

import { Check, ChevronRight, X } from "lucide-react";
import { useState } from "react";
import { ChatCode } from "~/components/chat/chat-code";
import {
  formatCount,
  type RunStep,
  type ValidationResult,
} from "~/lib/chat-run-steps";
import { prettySql } from "~/lib/pretty-sql";
import { InputPills, ProgressRail } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Validation card: `validate_sql`, `check_model_schema`, `analyze_grain`,
 * `validate_model_output`, `verify_model_values`, `explain_query`. A big
 * check or cross, the message, the suggested fix and the checks that ran,
 * with the SQL that was validated folded underneath.
 */

/** Fallback titles when a step carries no humanized `title` of its own. */
const TITLE_BY_TOOL: Record<string, string> = {
  validate_sql: "SQL check",
  check_model_schema: "Schema check",
  analyze_grain: "Grain analysis",
  validate_model_output: "Model output",
  verify_model_values: "Value check",
  explain_query: "Query plan",
};

const MODEL_INPUT_KEYS = ["model", "model_name", "models", "table", "connection"] as const;

/** Lines shown before the SQL block folds. */
const SQL_COLLAPSED_LINES = 4;

const SQL_START = /^\s*(select|with|insert|update|delete|create|alter|drop|join|from|left|inner|where|merge)\b/i;

export function looksLikeSql(text: string): boolean {
  return SQL_START.test(text);
}

function validationResult(step: RunStep): ValidationResult | null {
  return step.result?.kind === "validation" ? step.result : null;
}

function inputSql(step: RunStep): string | null {
  if (step.sql) return step.sql;
  const raw = step.input?.sql ?? step.input?.query;
  return typeof raw === "string" && raw.trim() ? raw : null;
}

export function summarizeValidation(step: RunStep): ToolCardSummary {
  const title = step.title || (TITLE_BY_TOOL[step.tool ?? ""] ?? "Validation");
  const failed = step.status === "failed";
  const result = validationResult(step);
  if (!result) return { title, stat: null, ok: !failed };
  const parts = [result.valid ? "valid" : "invalid"];
  if (result.estimatedRows != null) parts.push(`~${formatCount(result.estimatedRows)} rows`);
  if (result.expensive) parts.push("expensive");
  return { title, stat: parts.join(" · "), ok: result.valid && !failed };
}

/** A SQL block folded to its first lines with a toggle to reveal the rest. */
function CollapsedSql({ sql, defaultOpen = false }: { sql: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const pretty = prettySql(sql);
  const lines = pretty.split("\n");
  const folded = lines.length > SQL_COLLAPSED_LINES;
  const shown = open || !folded ? pretty : lines.slice(0, SQL_COLLAPSED_LINES).join("\n");
  return (
    <div data-testid="chat-validation-sql">
      <ChatCode code={shown} language="sql" maxHeightClass="max-h-72" />
      {folded && (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-center gap-1 px-3.5 pb-2 text-left text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)]"
        >
          <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
          {open ? "Fewer lines" : `${lines.length - SQL_COLLAPSED_LINES} more lines`}
        </button>
      )}
    </div>
  );
}

function InputEcho({ step, sqlOpen }: { step: RunStep; sqlOpen: boolean }) {
  const sql = inputSql(step);
  if (sql) return <CollapsedSql sql={sql} defaultOpen={sqlOpen} />;
  return (
    <div className="px-3.5 py-3">
      <InputPills step={step} keys={MODEL_INPUT_KEYS} />
    </div>
  );
}

export function ValidationRunning({ step }: ToolCardContext) {
  return (
    <div data-testid="chat-validation-card">
      <InputEcho step={step} sqlOpen={false} />
      <ProgressRail label="Validating…" />
    </div>
  );
}

/**
 * The message is skipped when `ToolCard` already shows it in the error
 * banner (same text as `errorMessage`, or any failed step with one).
 */
function showMessage(result: ValidationResult, failed: boolean): boolean {
  if (!result.message) return false;
  if (result.message === result.errorMessage) return false;
  return !(failed && result.errorMessage != null);
}

function Headline({ result, failed }: { result: ValidationResult; failed: boolean }) {
  const ok = result.valid;
  return (
    <div className="flex items-start gap-3 px-3.5 py-3">
      <span
        aria-hidden
        className={`flex h-8 w-8 flex-none items-center justify-center rounded-full border ${
          ok
            ? "border-[var(--color-success)]/35 bg-[rgba(0,255,136,0.08)] text-[var(--color-success)]"
            : "border-[var(--color-error)]/35 bg-[rgba(255,68,68,0.08)] text-[var(--color-error)]"
        }`}
      >
        {ok ? (
          <Check className="chat-boot-check h-4 w-4" strokeWidth={2.5} />
        ) : (
          <X className="h-4 w-4" strokeWidth={2.5} />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div
          data-testid="chat-validation-verdict"
          className={`text-[12px] font-medium ${
            ok ? "text-[var(--color-success)]" : "text-[var(--color-error)]"
          }`}
        >
          {ok ? "Valid" : "Invalid"}
          {result.estimatedRows != null && (
            <span className="ml-2 font-mono text-[11px] font-normal tabular-nums text-[var(--color-text-muted)]">
              ~{formatCount(result.estimatedRows)} rows
            </span>
          )}
          {result.expensive && (
            <span className="ml-2 rounded-md border border-[var(--color-warning)]/40 px-1.5 py-px text-[10px] font-normal text-[var(--color-warning)]">
              expensive
            </span>
          )}
        </div>
        {showMessage(result, failed) && (
          <p className="mt-1 break-words text-[11.5px] leading-5 text-[var(--color-text-muted)]">
            {result.message}
          </p>
        )}
      </div>
    </div>
  );
}

function SuggestedFix({ fix }: { fix: string }) {
  return (
    <div className="border-t border-[var(--color-border)]" data-testid="chat-validation-fix">
      <div className="px-3.5 pt-2 text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
        Suggested fix
      </div>
      {looksLikeSql(fix) ? (
        <ChatCode code={prettySql(fix)} language="sql" maxHeightClass="max-h-48" />
      ) : (
        <p className="px-3.5 pb-3 pt-1 text-[11.5px] leading-5 text-[var(--color-text)]">{fix}</p>
      )}
    </div>
  );
}

function Checks({ checks }: { checks: string[] }) {
  return (
    <ul
      data-testid="chat-validation-checks"
      className="flex flex-wrap gap-1.5 border-t border-[var(--color-border)] px-3.5 py-2.5"
    >
      {checks.map((check) => (
        <li
          key={check}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)]"
        >
          <Check className="h-2.5 w-2.5 text-[var(--color-text-dim)]" />
          {check}
        </li>
      ))}
    </ul>
  );
}

export function ValidationExpanded({ step }: ToolCardContext) {
  const result = validationResult(step);
  const sql = inputSql(step);
  if (!result) {
    // Legacy completion: only the input is known.
    return (
      <div data-testid="chat-validation-card">
        <InputEcho step={step} sqlOpen={false} />
      </div>
    );
  }
  return (
    <div data-testid="chat-validation-card">
      <Headline result={result} failed={step.status === "failed"} />
      {result.suggestedFix && <SuggestedFix fix={result.suggestedFix} />}
      {result.checks.length > 0 && <Checks checks={result.checks} />}
      {sql ? (
        <div className="border-t border-[var(--color-border)]">
          <CollapsedSql sql={sql} />
        </div>
      ) : (
        step.input && (
          <div className="border-t border-[var(--color-border)] px-3.5 py-2.5">
            <InputPills step={step} keys={MODEL_INPUT_KEYS} />
          </div>
        )
      )}
    </div>
  );
}

registerToolCard({
  kind: "validation",
  Icon: iconForKind("validation"),
  accent: "check",
  summarize: summarizeValidation,
  Running: ValidationRunning,
  Expanded: ValidationExpanded,
});
