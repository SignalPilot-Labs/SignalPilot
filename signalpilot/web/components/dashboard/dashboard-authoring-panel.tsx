"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Wrench } from "lucide-react";

import { request } from "~/lib/api";
import type { DashboardDefinition } from "~/lib/dashboard/contracts";
import { useToast } from "~/components/ui/toast";

import styles from "./dashboard-runtime.module.css";

export type DashboardAuthoringEvent = {
  id: string;
  sequence: number;
  kind:
    | "user"
    | "assistant"
    | "progress"
    | "validation"
    | "confirmation"
    | "system";
  status: "info" | "success" | "error" | "pending";
  message: string;
  metadata: Record<string, unknown>;
};

export type DashboardAuthoringSession = {
  id: string;
  thread_id: string;
  conversation_id: string | null;
  dashboard_id: string | null;
  base_version_id: string | null;
  applied_version_id: string | null;
  definition: DashboardDefinition | null;
  plan?: {
    name: string;
    description?: string | null;
    timezone: string;
    intents: Array<{
      chart_id: string;
      tile_id: string;
      label: string;
      section: string;
      order: number;
      layout: { x: number; y: number; w: number; h: number };
      visualization: "kpi" | "table" | "bar" | "line" | "area";
      required?: boolean;
    }>;
  } | null;
  expected_chart_count?: number;
  chart_drafts?: Array<{
    chart_id: string;
    ordinal: number;
    status: "pending" | "running" | "ready" | "failed";
    attempt_count: number;
    safe_error: string | null;
  }>;
  operations: Array<Record<string, unknown>>;
  summary: string;
  status: string;
  requires_custom_sql_confirmation: boolean;
  custom_sql_confirmed: boolean;
  custom_sql_chart_ids: string[];
  draft_revision: number;
  events: DashboardAuthoringEvent[];
};

export type DashboardRepairIssue = {
  chartTitle: string;
  message: string;
};

const AUTHORING_ERROR_FALLBACK =
  "The dashboard draft could not be updated. Please try again.";

export function dashboardAuthoringErrorMessage(cause: unknown): string {
  if (!(cause instanceof Error)) return AUTHORING_ERROR_FALLBACK;
  const response = /^\d{3}:\s*([\s\S]*)$/.exec(cause.message);
  if (!response) return cause.message || AUTHORING_ERROR_FALLBACK;
  try {
    const payload = JSON.parse(response[1]) as {
      detail?: string | { message?: string };
    };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
    if (
      payload.detail &&
      typeof payload.detail === "object" &&
      typeof payload.detail.message === "string" &&
      payload.detail.message.trim()
    ) {
      return payload.detail.message;
    }
  } catch {
    // Never show a raw provider or server response in dashboard authoring.
  }
  return AUTHORING_ERROR_FALLBACK;
}

export function dashboardRepairPrompt(issues: DashboardRepairIssue[]): string {
  const errorList = issues
    .map((issue) => `- ${issue.chartTitle}: ${issue.message}`)
    .join("\n");
  return [
    "Repair only the failing charts in this dashboard:",
    errorList,
    "Preserve every healthy chart, the dashboard layout, filters, names, and descriptions unless a listed repair requires a binding change.",
    "Use approved semantic fields and return a governed preview for review before Apply.",
  ].join("\n\n");
}

export function DashboardAuthoringPanel({
  dashboardId,
  intent = "edit",
  repairIssues = [],
}: {
  dashboardId: string;
  intent?: "edit" | "repair";
  repairIssues?: DashboardRepairIssue[];
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [opening, setOpening] = useState(false);
  return (
    <button
      className={`${styles.authoringLauncher} ${
        intent === "repair" ? styles.repairLauncher : ""
      }`}
      type="button"
      disabled={opening}
      onClick={() => {
        setOpening(true);
        void request<{
          conversation_id: string;
          authoring_session_id: string;
        }>(`/api/dashboards/${dashboardId}/authoring-chat`, { method: "POST" })
          .then((target) => {
            const params = new URLSearchParams({
              dashboard: target.authoring_session_id,
            });
            if (intent === "repair") {
              params.set("prompt", dashboardRepairPrompt(repairIssues));
            }
            router.push(
              `/chats/${target.conversation_id}?${params.toString()}`,
            );
          })
          .catch((cause) =>
            toast(
              cause instanceof Error
                ? dashboardAuthoringErrorMessage(cause)
                : "Could not open dashboard editing in Data Chat",
              "error",
            ),
          )
          .finally(() => setOpening(false));
      }}
      aria-label={
        intent === "repair"
          ? `Repair ${repairIssues.length} failing chart${repairIssues.length === 1 ? "" : "s"} with AI`
          : undefined
      }
    >
      {intent === "repair" ? (
        <>
          <Wrench size={15} aria-hidden="true" /> Repair
        </>
      ) : (
        <>
          <Sparkles size={16} aria-hidden="true" /> Edit with AI
        </>
      )}
    </button>
  );
}
