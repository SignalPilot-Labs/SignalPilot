"use client";

import type { DashboardScreenshotResult, RunStep } from "~/lib/chat-run-steps";
import { InputPills, ProgressRail, SkeletonRows } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Dashboard render card: `dashboard_screenshot`. The PNG stays in the
 * sandbox (it is not projected onto the event), so the card reports which
 * tiles rendered, which failed and why, and the canvas size.
 */

const INPUT_KEYS = ["path", "chart_ids", "width", "theme"] as const;

function screenshotResult(step: RunStep): DashboardScreenshotResult | null {
  return step.result?.kind === "dashboard_screenshot" ? step.result : null;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export function summarizeDashboardScreenshot(step: RunStep): ToolCardSummary {
  const result = screenshotResult(step);
  const failed = step.status === "failed";
  const title = "Dashboard render";
  if (!result) return { title, stat: null, ok: !failed };
  if (result.error) return { title, stat: result.error, ok: false };
  if (!result.dashboardValid) return { title, stat: "invalid dashboard spec", ok: false };
  const stat =
    result.failed.length > 0
      ? `Rendered ${plural(result.rendered.length, "chart")}, ${result.failed.length} failed`
      : `Rendered ${plural(result.rendered.length, "chart")}`;
  return { title, stat, ok: !failed };
}

export function DashboardScreenshotRunning({ step }: ToolCardContext) {
  return (
    <div data-testid="chat-dashboard-screenshot-card">
      <div className="px-3.5 pt-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
      <SkeletonRows columns={2} rows={2} />
      <ProgressRail label="Rendering dashboard…" />
    </div>
  );
}

function IdChip({ id }: { id: string }) {
  return (
    <span
      data-testid="chat-dashboard-screenshot-rendered"
      className="inline-flex items-center rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-px font-mono text-[10px] text-[var(--color-text-muted)]"
    >
      {id}
    </span>
  );
}

export function DashboardScreenshotExpanded({ step }: ToolCardContext) {
  const result = screenshotResult(step);
  if (!result) {
    return (
      <div data-testid="chat-dashboard-screenshot-card" className="px-3.5 py-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
    );
  }
  const size =
    result.width !== null && result.height !== null
      ? `${result.width} × ${result.height}`
      : null;
  return (
    <div data-testid="chat-dashboard-screenshot-card" className="space-y-2.5 px-3.5 py-3">
      {(result.error || !result.dashboardValid) && (
        <div
          data-testid="chat-dashboard-screenshot-error"
          className="text-[11.5px] leading-5 text-[var(--color-error)]"
        >
          <p className="font-medium">
            {result.error === "renderer_unavailable"
              ? "The dashboard renderer is not available in this sandbox."
              : result.error
                ? result.error
                : "The dashboard spec is not valid."}
          </p>
          {result.errors.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-[10.5px]">
              {result.errors.map((error, index) => (
                <li key={index}>{error}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {result.rendered.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-medium uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
            Rendered
          </p>
          <div className="flex flex-wrap gap-1">
            {result.rendered.map((id) => (
              <IdChip key={id} id={id} />
            ))}
          </div>
        </div>
      )}
      {result.failed.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-medium uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
            Failed
          </p>
          <ul className="space-y-1">
            {result.failed.map((entry, index) => (
              <li
                key={`${entry.id}-${index}`}
                data-testid="chat-dashboard-screenshot-failed"
                className="text-[11px] leading-4 text-[var(--color-warning)]"
              >
                <span className="mr-1.5 font-mono text-[var(--color-text)]">{entry.id}</span>
                <span className="mr-1.5 font-mono text-[10px]">{entry.code}</span>
                {entry.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(size || result.previewPath) && (
        <p className="font-mono text-[10px] text-[var(--color-text-dim)]">
          {[size, result.previewPath].filter(Boolean).join(" · ")}
        </p>
      )}
    </div>
  );
}

registerToolCard({
  kind: "dashboard_screenshot",
  Icon: iconForKind("dashboard_screenshot"),
  accent: "artifact",
  summarize: summarizeDashboardScreenshot,
  Running: DashboardScreenshotRunning,
  Expanded: DashboardScreenshotExpanded,
});
