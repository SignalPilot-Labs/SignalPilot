import type { AgentRunStatus } from "@/lib/agent-runs/types";

export type StatusTone = "success" | "warning" | "error" | "info" | "neutral";

export function statusToneFor(status: AgentRunStatus): StatusTone {
  switch (status) {
    case "succeeded":
      return "success";
    case "failed":
      return "error";
    case "running":
      return "info";
    case "approval_required":
      return "warning";
    case "cancelled":
      return "neutral";
    case "pending":
    default:
      return "neutral";
  }
}

const TONE_CLASSES: Record<StatusTone, string> = {
  success: "badge-success border",
  warning: "badge-warning border",
  error: "badge-error border",
  info: "badge-info border",
  neutral: "border border-[var(--color-border)] text-[var(--color-text-dim)]",
};

interface StatusPillProps {
  tone: StatusTone;
  children: React.ReactNode;
}

export function StatusPill({ tone, children }: StatusPillProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-[10px] uppercase tracking-[0.15em] font-mono ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
