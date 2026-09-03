"use client";

import { Loader2 } from "lucide-react";
import type { ConnectorHealth, HealthTone } from "~/lib/mcp-connectors-state";

const TONE: Record<HealthTone, { dot: string; text: string; ring: string }> = {
  ok: {
    dot: "bg-[var(--color-success)]",
    text: "text-[var(--color-success)]",
    ring: "border-[var(--color-success)]/25 bg-[var(--color-success)]/[0.06]",
  },
  attention: {
    dot: "bg-[var(--color-warning)]",
    text: "text-[var(--color-warning)]",
    ring: "border-[var(--color-warning)]/30 bg-[var(--color-warning)]/[0.07]",
  },
  error: {
    dot: "bg-[var(--color-error)]",
    text: "text-[var(--color-error)]",
    ring: "border-[var(--color-error)]/30 bg-[var(--color-error)]/[0.07]",
  },
  muted: {
    dot: "bg-[var(--color-text-dim)]",
    text: "text-[var(--color-text-muted)]",
    ring: "border-[var(--color-border)] bg-transparent",
  },
  pending: {
    dot: "bg-[var(--color-text-muted)]",
    text: "text-[var(--color-text-muted)]",
    ring: "border-[var(--color-border)] bg-[var(--color-bg-card)]",
  },
};

/** One health value per row. The label says the state once; nothing repeats it. */
export function ConnectorStatusPill({
  health,
  size = "md",
  testId = "connector-status-pill",
}: {
  health: ConnectorHealth;
  size?: "sm" | "md";
  testId?: string;
}) {
  const tone = TONE[health.tone];
  return (
    <span
      data-testid={testId}
      data-tone={health.tone}
      className={`inline-flex flex-none items-center gap-1.5 rounded-full border font-medium leading-none ${tone.ring} ${tone.text} ${
        size === "sm" ? "h-[20px] px-2 text-[10.5px]" : "h-[22px] px-2.5 text-[11px]"
      }`}
    >
      {health.tone === "pending" ? (
        <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden="true" />
      ) : (
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 rounded-full ${tone.dot} ${health.tone === "ok" ? "pulse-dot" : ""}`}
        />
      )}
      {health.label}
    </span>
  );
}
