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
  LayoutDashboard,
  NotebookPen,
  Play,
  ShieldCheck,
  SquareTerminal,
  Table2,
  Waypoints,
} from "lucide-react";
import { Bot, Brain } from "lucide-react";
import { memo, useEffect, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { format as formatSql } from "sql-formatter";
import { ChatCode, CopyButton, type ChatCodeLanguage } from "~/components/chat/chat-code";
import { AgentThinkingIndicator } from "~/components/chat/agent-thinking-indicator";
import {
  describeSubagentWork,
  formatStepDuration,
  shouldShowAgentThinking,
  summarizeRunSteps,
  type RunBlock,
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
  dashboard: LayoutDashboard,
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

function DashboardPreviewDetails({ step }: { step: RunStep }) {
  const request =
    typeof step.input?.request === "string" ? step.input.request.trim() : "";
  const timezone =
    typeof step.input?.timezone === "string" ? step.input.timezone : "UTC";
  return (
    <div className="px-3.5 py-3">
      <p className="line-clamp-3 text-[12px] leading-5 text-[var(--color-text)]">
        {request || "Create a governed dashboard preview"}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-[var(--color-text-dim)]">
        <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-input)] px-1.5 py-0.5">
          Private draft
        </span>
        <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-input)] px-1.5 py-0.5">
          {timezone}
        </span>
        <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-input)] px-1.5 py-0.5">
          Apply required
        </span>
      </div>
    </div>
  );
}

function StepBody({ step }: { step: RunStep }) {
  const running = step.status === "running";
  if (step.category === "dashboard") {
    return <DashboardPreviewDetails step={step} />;
  }
  if (step.category === "error" && (step.fullTrace || step.diagnostics)) {
    const diagnostics = step.diagnostics
      ? Object.entries(step.diagnostics).map(([key, value]) =>
          `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
        )
      : [];
    const supportBundle = [
      step.detail ? `Root cause: ${step.detail}` : "",
      diagnostics.length ? `Diagnostics:\n${diagnostics.join("\n")}` : "",
      step.fullTrace ? `Full trace:\n${step.fullTrace}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
    return (
      <CardShell label="Full trace" copyText={supportBundle} accent="error">
        {diagnostics.length > 0 && (
          <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 border-b border-[var(--color-border)] px-3.5 py-3 text-[11px]">
            {diagnostics.map((line) => {
              const separator = line.indexOf(": ");
              return (
                <div key={line} className="contents">
                  <dt className="font-mono text-[var(--color-text-dim)]">
                    {line.slice(0, separator)}
                  </dt>
                  <dd className="break-all font-mono text-[var(--color-text-muted)]">
                    {line.slice(separator + 2)}
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
        {step.fullTrace && (
          <ChatCode code={step.fullTrace} language="text" maxHeightClass="max-h-80" />
        )}
      </CardShell>
    );
  }
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
  if (step.category === "error") {
    return Boolean(step.fullTrace || step.diagnostics);
  }
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
  // Planning steps carry their reasoning (purpose / route reason) in detail;
  // that reads far better inline than the raw SQL snippet.
  if (step.category === "plan" && step.detail) {
    return step.detail.length > 90 ? `${step.detail.slice(0, 90)}…` : step.detail;
  }
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
      <span className="relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full border border-[var(--color-success)]/40 bg-[var(--color-bg)]">
        <span className="chat-dot-live h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full border border-[var(--color-error)]/40 bg-[var(--color-bg)]">
        <AlertCircle className="h-3 w-3 text-[var(--color-error)]" />
      </span>
    );
  }
  if (status === "succeeded") {
    return (
      <span className="relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg)]">
        <Check className="h-3 w-3 text-[var(--color-success)]/80" />
      </span>
    );
  }
  return (
    <span className="relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full bg-[var(--color-bg)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-border-active)]" />
    </span>
  );
}

const StepRow = memo(function StepRow({ step }: { step: RunStep }) {
  const expandable = stepHasBody(step);
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const open = userToggle ?? step.status === "running";
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

/** Elapsed time for a live subagent from its OWN event clock (latest child
 * activity minus spawn start) — correct under replay and clock skew, where
 * wall-clock deltas are nonsense. */
function subagentElapsedMs(step: RunStep): number | null {
  const start = Date.parse(step.startedAt);
  if (!Number.isFinite(start)) return null;
  let latest = start;
  for (const child of step.children) {
    for (const stamp of [child.startedAt, child.endedAt]) {
      const parsed = stamp ? Date.parse(stamp) : Number.NaN;
      if (Number.isFinite(parsed) && parsed > latest) latest = parsed;
    }
  }
  return latest > start ? latest - start : null;
}

function lastNarrationLine(liveText: string): string | null {
  const lines = liveText
    .split("\n")
    // Strip markdown emphasis/heading markers but keep identifier
    // characters like the underscores in column names.
    .map((line) => line.replace(/[*`]/g, "").replace(/^[#>\s-]+/, "").trim())
    .filter(Boolean);
  const last = lines[lines.length - 1];
  if (!last) return null;
  return last.length > 110 ? `${last.slice(0, 110)}…` : last;
}

/**
 * One subagent spawn rendered as its own live card: an autonomous worker
 * with a mission, a heartbeat, and a report. While it runs the card shows
 * the exact tool it is on plus a running tally; expanded, the full child
 * timeline and the final report are inspectable.
 */
const SubagentRow = memo(function SubagentRow({ step }: { step: RunStep }) {
  const running = step.status === "running";
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  // Reopen if it starts working again; collapse once the report lands.
  useEffect(() => {
    if (running) setUserToggle(null);
  }, [running]);
  const open = userToggle ?? running;
  const currentChild = [...step.children]
    .reverse()
    .find((child) => child.status === "running");
  const narration = lastNarrationLine(step.liveText);
  const tally = describeSubagentWork(step);
  const elapsed = formatStepDuration(
    running ? subagentElapsedMs(step) : step.durationMs,
  );
  return (
    <li className="chat-step-in relative">
      <div className="flex items-start gap-2.5">
        <StatusDot status={step.status} />
        <div className="min-w-0 flex-1 pb-1">
          <section
            data-testid="chat-subagent-card"
            className={`overflow-hidden rounded-lg border bg-[var(--color-bg-card)]/70 ${
              running
                ? "border-[var(--color-success)]/25"
                : step.status === "failed"
                  ? "border-[var(--color-error)]/30"
                  : "border-[var(--color-border)]"
            }`}
          >
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setUserToggle(!open)}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-[var(--color-bg-hover)]"
            >
              <span className="relative h-7 w-7 flex-none" aria-hidden>
                <span className="absolute inset-0 rounded-lg border border-[var(--color-border)]" />
                {running && (
                  <span
                    className="chat-boot-orbit absolute inset-0"
                    style={{ borderRadius: "0.5rem" }}
                  />
                )}
                <span className="absolute inset-0 flex items-center justify-center">
                  <Bot
                    className={`h-3.5 w-3.5 ${
                      running
                        ? "text-[var(--color-success)]"
                        : "text-[var(--color-text-muted)]"
                    }`}
                  />
                </span>
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="text-[9px] font-medium uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
                    Subagent
                  </span>
                  {step.subagentType && (
                    <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-input)] px-1.5 py-px font-mono text-[9px] text-[var(--color-text-muted)]">
                      {step.subagentType}
                    </span>
                  )}
                </span>
                <span
                  className={`block truncate text-[12px] font-medium ${
                    running
                      ? "chat-live-label"
                      : step.status === "failed"
                        ? "text-[var(--color-error)]"
                        : "text-[var(--color-text)]"
                  }`}
                >
                  {step.title}
                </span>
              </span>
              <span className="ml-auto flex flex-none items-center gap-2 text-[10px] text-[var(--color-text-dim)]">
                <span className="hidden tabular-nums sm:inline">{tally}</span>
                {elapsed && <span className="tabular-nums">{elapsed}</span>}
                <ChevronRight
                  className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
                />
              </span>
            </button>
            {running && (currentChild || narration) && (
              <div className="flex items-center gap-2 border-t border-[var(--color-border)]/60 px-3 py-1.5 text-[11px] text-[var(--color-text-muted)]">
                <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
                {currentChild ? (
                  <span className="truncate">
                    {currentChild.title}
                    {currentChild.file && (
                      <span className="font-mono text-[var(--color-text-dim)]">
                        {" "}
                        {currentChild.file}
                      </span>
                    )}
                  </span>
                ) : (
                  <span className="truncate italic">{narration}</span>
                )}
              </div>
            )}
            <div className="chat-collapse" data-open={open}>
              <div>
                <div className="border-t border-[var(--color-border)]/60 px-3 py-2.5">
                  {step.children.length ? (
                    <RunTimeline steps={step.children} />
                  ) : (
                    <p className="px-1 text-[11px] text-[var(--color-text-dim)]">
                      The subagent is reading its instructions.
                    </p>
                  )}
                  {step.report && (
                    <div className="mt-2.5 border-t border-[var(--color-border)]/60 pt-2.5">
                      <p className="mb-1 text-[9px] font-medium uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
                        Report
                      </p>
                      <div className="chat-markdown text-[12px]">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {step.report}
                        </ReactMarkdown>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
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
      {steps.map((step) =>
        step.category === "subagent" ? (
          <SubagentRow key={step.key} step={step} />
        ) : (
          <StepRow key={step.key} step={step} />
        ),
      )}
    </ol>
  );
}

function DashboardPreviewActivityCard({
  step,
  live,
}: {
  step: RunStep;
  live: boolean;
}) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const active = live || step.status === "running";
  useEffect(() => {
    if (active) setUserToggle(null);
  }, [active]);
  const open = userToggle ?? active;
  const failed = step.status === "failed";
  const phase = active
    ? (step.detail ?? "Preparing governed dashboard preview…")
    : failed
      ? (step.detail ?? "Dashboard preview could not be created")
      : "Governed preview ready for review";

  return (
    <section
      data-testid="dashboard-preview-activity"
      className={`my-3 overflow-hidden rounded-xl border bg-[var(--color-bg-card)]/60 ${
        active
          ? "border-[var(--color-success)]/25"
          : failed
            ? "border-[var(--color-error)]/30"
            : "border-[var(--color-border)]"
      }`}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserToggle(!open)}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-[var(--color-bg-hover)]"
      >
        <span
          className={`flex h-8 w-8 flex-none items-center justify-center rounded-lg border bg-[var(--color-bg-input)] ${
            active
              ? "border-[var(--color-success)]/30"
              : failed
                ? "border-[var(--color-error)]/30"
                : "border-[var(--color-border)]"
          }`}
        >
          <LayoutDashboard
            className={`h-4 w-4 ${
              active
                ? "text-[var(--color-success)]"
                : failed
                  ? "text-[var(--color-error)]"
                  : "text-[var(--color-text-muted)]"
            }`}
          />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[9px] font-medium uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
            Dashboard preview
          </span>
          <span
            className={`block truncate text-[12px] font-medium ${
              active
                ? "chat-live-label"
                : failed
                  ? "text-[var(--color-error)]"
                  : "text-[var(--color-text)]"
            }`}
          >
            {phase}
          </span>
        </span>
        <span className="ml-auto flex flex-none items-center gap-1.5 text-[10px] text-[var(--color-text-dim)]">
          {active ? (
            <>
              <span className="chat-dot-live h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
              <span>Live</span>
            </>
          ) : failed ? (
            <>
              <AlertCircle className="h-3 w-3 text-[var(--color-error)]" />
              <span>Failed</span>
            </>
          ) : (
            <>
              <Check className="h-3 w-3 text-[var(--color-success)]/80" />
              <span>Ready</span>
            </>
          )}
          <ChevronRight
            className={`ml-0.5 h-3 w-3 transition-transform ${
              open ? "rotate-90" : ""
            }`}
          />
        </span>
      </button>
      <div className="chat-collapse" data-open={open}>
        <div>
          <div className="border-t border-[var(--color-border)]">
            <DashboardPreviewDetails step={step} />
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * One tool chain rendered as a collapsible group: expanded with a live
 * shimmer header while any of its steps run, collapsing to a one-line
 * summary once the chain completes and the agent moves on.
 */
function StandardActivityGroup({
  steps,
  live,
}: {
  steps: RunStep[];
  live: boolean;
}) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const active = live || steps.some((step) => step.status === "running");
  // Reopen automatically if this group starts working again (e.g. retry).
  useEffect(() => {
    if (active) setUserToggle(null);
  }, [active]);
  const open = userToggle ?? active;
  const latest = steps[steps.length - 1] ?? null;
  if (!steps.length && !active) return null;
  return (
    <section
      data-testid="chat-activity-group"
      className="my-3 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]/60"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserToggle(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-[var(--color-bg-hover)]"
      >
        {active ? (
          <>
            <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
            <span className="chat-live-label font-medium">
              {latest && latest.status === "running"
                ? (latest.detail ?? latest.title)
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

export function ActivityGroup({
  steps,
  live,
}: {
  steps: RunStep[];
  live: boolean;
}) {
  const dashboardStep =
    steps.length === 1 && steps[0]?.category === "dashboard" ? steps[0] : null;
  return dashboardStep ? (
    <DashboardPreviewActivityCard step={dashboardStep} live={live} />
  ) : (
    <StandardActivityGroup steps={steps} live={live} />
  );
}

/**
 * A stretch of the model's extended thinking. Streams open with a live
 * shimmer while tokens arrive, then folds down to a quiet one-line toggle
 * so reasoning is inspectable without crowding the answer.
 */
function ThinkingBlockView({ text, live }: { text: string; live: boolean }) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  // Streaming shows the thought as it forms; once done it folds closed.
  useEffect(() => {
    if (live) setUserToggle(null);
  }, [live]);
  const open = userToggle ?? live;
  return (
    <section
      data-testid="chat-thinking-block"
      className="my-3"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserToggle(!open)}
        className="flex items-center gap-2 rounded-md px-1 py-0.5 text-left text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-muted)]"
      >
        <Brain className="h-3.5 w-3.5 flex-none" />
        <span className={live ? "chat-live-label font-medium" : ""}>
          {live ? "Thinking…" : "Thought process"}
        </span>
        <ChevronRight
          className={`h-3 w-3 flex-none transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
      <div className="chat-collapse" data-open={open}>
        <div>
          <div className="mt-1.5 max-h-64 overflow-y-auto border-l-2 border-[var(--color-border)] py-0.5 pl-3 pr-1">
            <p className="chat-thinking-text text-[12px] leading-5 text-[var(--color-text-dim)] italic">
              {text}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * Full interleaved view of a run: markdown for streamed narration, an
 * ActivityGroup per tool chain, in the order they actually happened. Only
 * the trailing group is treated as live while the run streams.
 */
export function RunActivityBlocks({
  blocks,
  running,
}: {
  blocks: RunBlock[];
  running: boolean;
}) {
  const showThinking = shouldShowAgentThinking(blocks, running);
  if (!blocks.length) {
    return showThinking ? <AgentThinkingIndicator /> : null;
  }
  const lastStepsIndex = blocks.reduce(
    (latest, block, index) => (block.kind === "steps" ? index : latest),
    -1,
  );
  const trailingSteps =
    lastStepsIndex === blocks.length - 1 && lastStepsIndex >= 0;
  return (
    <>
      {blocks.map((block, index) =>
        block.kind === "text" ? (
          <div key={block.key} className="chat-markdown my-3">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {block.text}
            </ReactMarkdown>
          </div>
        ) : block.kind === "thinking" ? (
          <ThinkingBlockView
            key={block.key}
            text={block.text}
            live={running && index === blocks.length - 1}
          />
        ) : (
          <ActivityGroup
            key={block.key}
            steps={block.steps}
            live={
              running &&
              !showThinking &&
              trailingSteps &&
              index === lastStepsIndex
            }
          />
        ),
      )}
      {showThinking && <AgentThinkingIndicator />}
    </>
  );
}
