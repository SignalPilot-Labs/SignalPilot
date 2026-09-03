"use client";

import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { ChatCode, CopyButton, type ChatCodeLanguage } from "~/components/chat/chat-code";
import { formatErrorSupportBundle, type RunStep } from "~/lib/chat-run-steps";
import { prettySql } from "~/lib/pretty-sql";

export function languageForFile(file: string | null): ChatCodeLanguage {
  if (!file) return "text";
  if (/\.py$/i.test(file)) return "python";
  if (/\.sql$/i.test(file)) return "sql";
  if (/\.(sh|bash|zsh)$/i.test(file)) return "bash";
  return "text";
}

export function CardShell({
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

export function ExecutingLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 border-t border-[var(--color-border)] px-3.5 py-2 text-[11px] text-[var(--color-text-muted)]">
      <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
      <span className="chat-live-label">{label}</span>
    </div>
  );
}

export function DiffBlock({ step }: { step: RunStep }) {
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

export function TodoCard({ step }: { step: RunStep }) {
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

export function GenericInput({ step }: { step: RunStep }) {
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

export function DashboardPreviewDetails({ step }: { step: RunStep }) {
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

export function StepBody({ step }: { step: RunStep }) {
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
    const supportBundle = formatErrorSupportBundle(step);
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

export function stepHasBody(step: RunStep): boolean {
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
