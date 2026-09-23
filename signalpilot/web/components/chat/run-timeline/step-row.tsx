"use client";

import {
  AlertCircle,
  TriangleAlert,
  Check,
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
import { memo, useState } from "react";
import type { RunStep, RunStepCategory } from "~/lib/chat-run-steps";
import { FAILED_TONE_CLASS } from "~/components/chat/tool-cards/card-primitives";
import { resolveToolCard } from "~/components/chat/tool-cards/registry";
import { ToolCard } from "~/components/chat/tool-cards/tool-card";
import { StepBody, stepHasBody } from "./step-body";
import { failureLine, StepLine } from "./step-line";
import {
  formatTelemetryClock,
  formatTelemetryDuration,
} from "~/lib/chat-telemetry";
import { useChatTelemetryContext } from "~/components/chat/chat-telemetry-context";

export function ToolTelemetryTime({ step }: { step: RunStep }) {
  const telemetry = useChatTelemetryContext();
  if (!telemetry.enabled) return null;
  const startedAt = Date.parse(step.startedAt);
  const duration =
    step.durationMs ??
    (step.status === "running"
      ? Math.max(0, telemetry.nowMs - startedAt)
      : null);
  return (
    <span
      data-testid="chat-tool-timing"
      title={`${new Date(startedAt).toLocaleString()}${duration == null ? "" : ` · ${formatTelemetryDuration(duration)}`}`}
      className="font-mono text-[10px] tabular-nums text-cyan-300/60 transition-colors group-hover:text-cyan-300"
    >
      {formatTelemetryClock(startedAt)}
      {duration != null ? ` · ${formatTelemetryDuration(duration)}` : ""}
    </span>
  );
}

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
      <span className="chat-state-in relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full border border-[var(--color-success)]/40 bg-[var(--color-bg)]">
        <span className="chat-dot-live h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        data-testid="chat-step-status-failed"
        className="chat-state-in relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg)]"
      >
        <TriangleAlert className={`h-3 w-3 ${FAILED_TONE_CLASS}`} aria-label="Failed" />
      </span>
    );
  }
  if (status === "succeeded") {
    return (
      <span className="chat-state-in relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg)]">
        <Check className="h-3 w-3 text-[var(--color-success)]/80" />
      </span>
    );
  }
  return (
    <span className="chat-state-in relative z-10 flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full bg-[var(--color-bg)]">
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
  const [open, setOpen] = useState(false);
  const Icon = CATEGORY_ICONS[step.category] ?? Play;
  const preview = stepPreview(step);
  return (
    <li className="chat-step-in relative">
      <div className="flex items-start gap-2.5">
        <StatusDot key={step.status} status={step.status} />
        <StepLine
          step={step}
          Icon={Icon}
          title={step.title}
          stat={preview}
          failure={failureLine(step.detail) ?? "Failed"}
          open={open}
          onToggle={() => setOpen((value) => !value)}
          trailing={<ToolTelemetryTime step={step} />}
        >
          {stepHasBody(step) ? <StepBody step={step} /> : null}
        </StepLine>
      </div>
      {step.sources.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5 pl-[34px]">
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
    </li>
  );
});
