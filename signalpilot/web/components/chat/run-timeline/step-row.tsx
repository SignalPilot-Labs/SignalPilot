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
import { memo, useState } from "react";
import {
  formatStepDuration,
  type RunStep,
  type RunStepCategory,
} from "~/lib/chat-run-steps";
import { resolveToolCard } from "~/components/chat/tool-cards/registry";
import { ToolCard } from "~/components/chat/tool-cards/tool-card";
import { StepBody, stepHasBody } from "./step-body";

export const CATEGORY_ICONS: Partial<Record<RunStepCategory, typeof Database>> = {
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

export function stepPreview(step: RunStep): string | null {
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

export function StatusDot({ status }: { status: RunStep["status"] }) {
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

/**
 * One timeline row. Steps with a projectable tool result render the
 * density-aware `ToolCard`; everything else (claude-code file/todo tools,
 * approvals, plans) keeps the legacy expandable row below.
 */
export const StepRow = memo(function StepRow({
  step,
  isLastInGroup = false,
  groupLive = false,
  focusRequested,
}: {
  step: RunStep;
  isLastInGroup?: boolean;
  groupLive?: boolean;
  focusRequested?: boolean | number;
}) {
  if (resolveToolCard(step)) {
    return (
      <ToolCard
        step={step}
        isLastInGroup={isLastInGroup}
        groupLive={groupLive}
        focusRequested={focusRequested}
      />
    );
  }
  return <LegacyStepRow step={step} />;
});

const LegacyStepRow = memo(function LegacyStepRow({ step }: { step: RunStep }) {
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
