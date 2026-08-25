"use client";

import {
  AlertCircle,
  Check,
  ChevronRight,
  Database,
  FileCode2,
  FileDiff,
  FilePen,
  FileSearch,
  Globe,
  ListTodo,
  NotebookPen,
  Play,
  ShieldCheck,
  SquareTerminal,
  Table2,
  Waypoints,
} from "lucide-react";
import { memo, useEffect, useState, type ReactNode } from "react";
import { format as formatSql } from "sql-formatter";
import { ChatCode, CopyButton, type ChatCodeLanguage } from "~/components/chat/chat-code";
import {
  formatStepDuration,
  summarizeRunSteps,
  type RunStep,
  type RunStepCategory,
} from "~/lib/chat-run-steps";

const CATEGORY_ICONS: Partial<Record<RunStepCategory, typeof Database>> = {
  sql: Database,
  python: FileCode2,
  notebook: NotebookPen,
  terminal: SquareTerminal,
  "file-write": FilePen,
  "file-edit": FileDiff,
  "file-read": FileSearch,
  todo: ListTodo,
  web: Globe,
  source: Waypoints,
  artifact: Table2,
  dbt: Waypoints,
  plan: Waypoints,
  approval: ShieldCheck,
  error: AlertCircle,
};

function languageForFile(file: string | null): ChatCodeLanguage {
  if (!file) return "text";
  if (/\.py$/i.test(file)) return "python";
  if (/\.sql$/i.test(file)) return "sql";
  if (/\.(sh|bash|zsh)$/i.test(file)) return "bash";
  return "text";
}

function prettySql(sql: string): string {
  try {
    return formatSql(sql, { language: "postgresql", keywordCase: "upper" });
  } catch {
    return sql;
  }
}

function CardShell({
  label,
  file,
  copyText,
  children,
  accent,
}: {
  label: string;
  file?: string | null;
  copyText?: string | null;
  children: ReactNode;
  accent?: "success" | "error";
}) {
  return (
    <div
      className={`overflow-hidden rounded-lg border bg-[var(--color-bg-input)] ${
        accent === "error"
          ? "border-[var(--color-error)]/30"
          : "border-[var(--color-border)]"
      }`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
            {label}
          </span>
          {file && (
            <span className="truncate font-mono text-[11px] text-[var(--color-text-muted)]">
              {file}
            </span>
          )}
        </div>
        {copyText && <CopyButton text={copyText} />}
      </div>
      {children}
    </div>
  );
}

function ExecutingLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 border-t border-[var(--color-border)] px-3.5 py-2 text-[11px] text-[var(--color-text-muted)]">
      <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
      <span className="chat-live-label">{label}</span>
    </div>
  );
}

function DiffBlock({ step }: { step: RunStep }) {
  const oldText =
    typeof step.input?.old_string === "string" ? step.input.old_string : "";
  const newText =
    typeof step.input?.new_string === "string" ? step.input.new_string : "";
  const language = languageForFile(step.file);
  return (
    <CardShell label="Edit" file={step.file} copyText={newText || null}>
      {oldText && (
        <div className="border-b border-[var(--color-border)] bg-[rgba(255,68,68,0.05)]">
          <div className="px-3.5 pt-2 text-[10px] uppercase tracking-[0.14em] text-[var(--color-error)]/80">
            Removed
          </div>
          <ChatCode code={oldText} language={language} maxHeightClass="max-h-40" />
        </div>
      )}
      {newText && (
        <div className="bg-[rgba(0,255,136,0.04)]">
          <div className="px-3.5 pt-2 text-[10px] uppercase tracking-[0.14em] text-[var(--color-success)]/80">
            Added
          </div>
          <ChatCode code={newText} language={language} maxHeightClass="max-h-40" />
        </div>
      )}
    </CardShell>
  );
}

function TodoCard({ step }: { step: RunStep }) {
  const todos = Array.isArray(step.input?.todos) ? step.input.todos : [];
  const items = todos
    .map((todo) =>
      typeof todo === "object" && todo !== null
        ? {
            content: String(
              (todo as Record<string, unknown>).content ??
                (todo as Record<string, unknown>).activeForm ??
                "",
            ),
            status: String((todo as Record<string, unknown>).status ?? ""),
          }
        : null,
    )
    .filter((item): item is { content: string; status: string } =>
      Boolean(item?.content),
    );
  if (!items.length) return null;
  return (
    <CardShell label="Plan">
      <ul className="space-y-1.5 px-3.5 py-3">
        {items.map((item, index) => (
          <li
            key={index}
            className="flex items-start gap-2 text-[12px] leading-5"
          >
            {item.status === "completed" ? (
              <Check className="mt-0.5 h-3.5 w-3.5 flex-none text-[var(--color-success)]" />
            ) : item.status === "in_progress" ? (
              <span className="chat-dot-live mt-1 h-2 w-2 flex-none rounded-full bg-[var(--color-success)]" />
            ) : (
              <span className="mt-1 h-2 w-2 flex-none rounded-full border border-[var(--color-border-active)]" />
            )}
            <span
              className={
                item.status === "completed"
                  ? "text-[var(--color-text-dim)] line-through decoration-[var(--color-border-active)]"
                  : item.status === "in_progress"
                    ? "text-[var(--color-text)]"
                    : "text-[var(--color-text-muted)]"
              }
            >
              {item.content}
            </span>
          </li>
        ))}
      </ul>
    </CardShell>
  );
}

function GenericInput({ step }: { step: RunStep }) {
  const entries = Object.entries(step.input ?? {}).filter(
    ([, value]) => value != null && value !== "",
  );
  if (!entries.length) return null;
  return (
    <CardShell label={step.tool ?? "Tool"}>
      <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 px-3.5 py-3 text-[11px]">
        {entries.slice(0, 8).map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="text-[var(--color-text-dim)]">{key}</dt>
            <dd className="min-w-0 truncate font-mono text-[var(--color-text-muted)]">
              {typeof value === "string" ? value : JSON.stringify(value)}
            </dd>
          </div>
        ))}
      </dl>
    </CardShell>
  );
}

function StepBody({ step }: { step: RunStep }) {
  const running = step.status === "running";
  if (step.category === "sql" && step.sql) {
    return (
      <CardShell label="SQL" copyText={step.sql}>
        <ChatCode code={prettySql(step.sql)} language="sql" />
        {running && <ExecutingLine label="Running against the warehouse…" />}
      </CardShell>
    );
  }
  if (
    (step.category === "python" || step.category === "notebook") &&
    step.code
  ) {
    return (
      <CardShell
        label="Python"
        file={step.file}
        copyText={step.code}
        accent={step.status === "failed" ? "error" : undefined}
      >
        <ChatCode code={step.code} language="python" />
        {running && <ExecutingLine label="Executing…" />}
      </CardShell>
    );
  }
  if (step.category === "terminal" && step.code) {
    return (
      <CardShell label="Shell" copyText={step.code}>
        <div className="px-3.5 py-3">
          <pre className="chat-code overflow-auto text-[12px] leading-[1.7] text-[var(--color-text-muted)]">
            <code>
              <span className="select-none text-[var(--color-success)]">
                ${" "}
              </span>
              {step.code}
            </code>
          </pre>
        </div>
        {running && <ExecutingLine label="Running…" />}
      </CardShell>
    );
  }
  if (step.category === "file-write" && step.code) {
    return (
      <CardShell
        label={running ? "Writing file" : "File"}
        file={step.file}
        copyText={step.code}
      >
        <ChatCode code={step.code} language={languageForFile(step.file)} />
        {running && <ExecutingLine label="Generating…" />}
      </CardShell>
    );
  }
  if (step.category === "file-edit") return <DiffBlock step={step} />;
  if (step.category === "todo") return <TodoCard step={step} />;
  if (step.sql) {
    return (
      <CardShell label="SQL" copyText={step.sql}>
        <ChatCode code={prettySql(step.sql)} language="sql" />
      </CardShell>
    );
  }
  return <GenericInput step={step} />;
}

function stepHasBody(step: RunStep): boolean {
  if (step.sql || step.code) return true;
  if (step.category === "file-edit") {
    return Boolean(step.input?.old_string || step.input?.new_string);
  }
  if (step.category === "todo") {
    return Array.isArray(step.input?.todos) && step.input.todos.length > 0;
  }
  return Boolean(
    step.input && Object.keys(step.input).length > 0 && step.category !== "approval",
  );
}

function stepPreview(step: RunStep): string | null {
  if (step.file) return step.file;
  if (step.sql) {
    const flat = step.sql.replace(/\s+/g, " ").trim();
    return flat.length > 72 ? `${flat.slice(0, 72)}…` : flat;
  }
  if (step.code) {
    const first = step.code.split("\n").find((line) => line.trim());
    return first ? (first.length > 72 ? `${first.slice(0, 72)}…` : first) : null;
  }
  return step.detail;
}

function StatusDot({ status }: { status: RunStep["status"] }) {
  if (status === "running") {
    return (
      <span className="relative z-10 flex h-[19px] w-[19px] flex-none items-center justify-center rounded-full border border-[var(--color-success)]/40 bg-[var(--color-bg)]">
        <span className="chat-dot-live h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="relative z-10 flex h-[19px] w-[19px] flex-none items-center justify-center rounded-full border border-[var(--color-error)]/40 bg-[var(--color-bg)]">
        <AlertCircle className="h-3 w-3 text-[var(--color-error)]" />
      </span>
    );
  }
  if (status === "succeeded") {
    return (
      <span className="relative z-10 flex h-[19px] w-[19px] flex-none items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg)]">
        <Check className="h-3 w-3 text-[var(--color-success)]/80" />
      </span>
    );
  }
  return (
    <span className="relative z-10 flex h-[19px] w-[19px] flex-none items-center justify-center rounded-full bg-[var(--color-bg)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-border-active)]" />
    </span>
  );
}

const StepRow = memo(function StepRow({ step }: { step: RunStep }) {
  const expandable = stepHasBody(step);
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const open =
    userToggle ?? (step.status === "running" || step.status === "failed");
  const Icon = CATEGORY_ICONS[step.category] ?? Play;
  const duration = formatStepDuration(step.durationMs);
  const preview = stepPreview(step);
  return (
    <li className="chat-step-in relative">
      <div className="flex items-start gap-2.5">
        <StatusDot status={step.status} />
        <div className="min-w-0 flex-1 pb-1">
          <button
            type="button"
            disabled={!expandable}
            aria-expanded={expandable ? open : undefined}
            onClick={() => setUserToggle(!open)}
            className={`group flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left text-[12px] ${
              expandable
                ? "cursor-pointer hover:bg-[var(--color-bg-hover)]"
                : "cursor-default"
            }`}
          >
            <Icon className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" />
            <span
              className={`flex-none ${
                step.status === "running"
                  ? "chat-live-label font-medium"
                  : step.status === "failed"
                    ? "text-[var(--color-error)]"
                    : "text-[var(--color-text)]"
              }`}
            >
              {step.title}
            </span>
            {preview && (
              <span className="min-w-0 truncate font-mono text-[11px] text-[var(--color-text-dim)]">
                {preview}
              </span>
            )}
            <span className="ml-auto flex flex-none items-center gap-2">
              {duration && (
                <span className="text-[10px] tabular-nums text-[var(--color-text-dim)]">
                  {duration}
                </span>
              )}
              {expandable && (
                <ChevronRight
                  className={`h-3 w-3 text-[var(--color-text-dim)] transition-transform ${
                    open ? "rotate-90" : ""
                  }`}
                />
              )}
            </span>
          </button>
          {step.status === "failed" && step.detail && (
            <p className="mt-1 pl-6 text-[11px] leading-4 text-[var(--color-error)]/90">
              {step.detail}
            </p>
          )}
          {step.sources.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5 pl-6">
              {step.sources.map((source) => (
                <span
                  key={source}
                  className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text-muted)]"
                >
                  <Waypoints className="h-2.5 w-2.5 text-[var(--color-text-dim)]" />
                  {source}
                </span>
              ))}
            </div>
          )}
          {expandable && (
            <div className="chat-collapse" data-open={open}>
              <div>
                <div className="mt-2 pl-6 pr-1">
                  <StepBody step={step} />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </li>
  );
});

export function describeRunWork(steps: RunStep[]): string {
  const summary = summarizeRunSteps(steps);
  const parts: string[] = [];
  if (summary.queries) {
    parts.push(`${summary.queries} ${summary.queries === 1 ? "query" : "queries"}`);
  }
  if (summary.codeRuns) {
    parts.push(`${summary.codeRuns} code ${summary.codeRuns === 1 ? "run" : "runs"}`);
  }
  if (summary.files) {
    parts.push(`${summary.files} ${summary.files === 1 ? "file" : "files"}`);
  }
  if (summary.errors) {
    parts.push(`${summary.errors} ${summary.errors === 1 ? "error" : "errors"}`);
  }
  const detail = parts.length ? ` · ${parts.join(" · ")}` : "";
  return `${summary.total} ${summary.total === 1 ? "step" : "steps"}${detail}`;
}

export function RunTimeline({ steps }: { steps: RunStep[] }) {
  if (!steps.length) {
    return (
      <p className="px-1 py-1 text-xs text-[var(--color-text-dim)]">
        Work details will appear as the analysis progresses.
      </p>
    );
  }
  return (
    <ol className="chat-step-rail space-y-1.5" aria-label="Agent activity">
      {steps.map((step) => (
        <StepRow key={step.key} step={step} />
      ))}
    </ol>
  );
}

/**
 * Live activity block shown inside a streaming assistant message: expanded
 * while the run works, collapsing to a one-line summary once it completes.
 */
export function LiveRunActivity({
  steps,
  running,
}: {
  steps: RunStep[];
  running: boolean;
}) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  // Reopen automatically if a new run starts streaming in the same message.
  useEffect(() => {
    if (running) setUserToggle(null);
  }, [running]);
  const open = userToggle ?? running;
  const latest = steps[steps.length - 1] ?? null;
  if (!steps.length && !running) return null;
  return (
    <section
      data-testid="chat-live-activity"
      className="my-3 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]/60"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserToggle(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-[var(--color-bg-hover)]"
      >
        {running ? (
          <>
            <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
            <span className="chat-live-label font-medium">
              {latest && latest.status === "running"
                ? latest.title
                : "Working…"}
            </span>
          </>
        ) : (
          <>
            <Check className="h-3.5 w-3.5 flex-none text-[var(--color-success)]/80" />
            <span className="text-[var(--color-text-muted)]">
              Worked through {describeRunWork(steps)}
            </span>
          </>
        )}
        <ChevronRight
          className={`ml-auto h-3 w-3 flex-none text-[var(--color-text-dim)] transition-transform ${
            open ? "rotate-90" : ""
          }`}
        />
      </button>
      <div className="chat-collapse" data-open={open}>
        <div>
          <div className="border-t border-[var(--color-border)] px-3 py-3">
            <RunTimeline steps={steps} />
          </div>
        </div>
      </div>
    </section>
  );
}
