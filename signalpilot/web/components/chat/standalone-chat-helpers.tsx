"use client";

// Small shared helpers for the standalone data chat UI.

import { Bot } from "lucide-react";
import type {
  StandaloneChatEvent,
  StandaloneChatRunStatus,
} from "~/lib/api";

export function statusLabel(
  status: StandaloneChatRunStatus | null,
): string | null {
  if (!status) return null;
  return {
    queued: "Queued",
    running: "Running",
    waiting_for_user: "Waiting for you",
    waiting_for_query_approval: "Waiting for query approval",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Stopped",
  }[status];
}

export function statusTone(status: StandaloneChatRunStatus | null): string {
  if (status === "running" || status === "queued")
    return "text-[var(--color-success)]";
  if (status === "waiting_for_user" || status === "waiting_for_query_approval")
    return "text-[var(--color-warning)]";
  if (status === "failed") return "text-[var(--color-error)]";
  return "text-[var(--color-text-dim)]";
}

export function isImprovementConversation(
  conversation: { origin?: string } | null | undefined,
): boolean {
  return conversation?.origin === "improvement";
}

/** Small pill marking a system-initiated (automated improvement) conversation. */
export function AutomatedBadge() {
  return (
    <span className="inline-flex flex-none items-center gap-1 rounded-full border border-[var(--color-warning)]/25 bg-[var(--color-warning)]/5 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.08em] text-[var(--color-warning)]">
      <Bot className="h-2.5 w-2.5" />
      Automated
    </span>
  );
}

export function isStreamingStatus(status: StandaloneChatRunStatus | undefined) {
  return status === "queued" || status === "running";
}

export function projectSetupSuffix(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes("ai runtime credentials")) {
    return " · AI setup needed";
  }
  if (normalized.includes("dbt metadata")) {
    return " · dbt metadata needed";
  }
  if (normalized.includes("connection")) {
    return " · connection setup needed";
  }
  if (normalized.includes("branch")) {
    return " · branch setup needed";
  }
  return " · setup needed";
}

export function eventText(
  event: StandaloneChatEvent | null | undefined,
  key: string,
): string {
  const value = event?.payload?.[key];
  return typeof value === "string" ? value : "";
}
