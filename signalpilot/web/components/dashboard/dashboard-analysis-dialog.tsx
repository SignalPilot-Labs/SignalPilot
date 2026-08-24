"use client";

import Link from "next/link";
import { useState } from "react";
import { createPortal } from "react-dom";

import { StandaloneDataChatLoader } from "~/components/chat/standalone-data-chat-loader";
import { DashboardRenderer } from "~/components/dashboard/dashboard-renderer";
import { request } from "~/lib/api";
import type {
  ChartDefinition,
  DashboardDrillStep,
  DashboardQueryResult,
  DashboardRuntimeFilter,
} from "~/lib/dashboard/contracts";

import styles from "./dashboard-runtime.module.css";

export function DashboardAnalysisDialog({
  dashboardId,
  versionId,
  tileUuid,
  chart,
  result,
  dashboardResultId,
  filters,
  drillPath,
  selectedMark,
  onClose,
}: {
  dashboardId: string;
  versionId: string;
  tileUuid: string;
  chart: ChartDefinition;
  result: DashboardQueryResult;
  dashboardResultId: string;
  filters: DashboardRuntimeFilter[];
  drillPath: DashboardDrillStep[];
  selectedMark: Record<string, unknown>;
  onClose: () => void;
}) {
  const [message, setMessage] = useState(
    "What changed here, and what are the most likely drivers?",
  );
  const [conversationId, setConversationId] = useState<string>();
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  return createPortal(
    <div
      className={styles.analysisDialog}
      role="dialog"
      aria-modal="true"
      aria-label={`Analyze ${chart.title}`}
    >
      <section className={styles.analysisDialogPanel}>
        <header>
          <div>
            <span>Frozen chart reference</span>
            <h2>Analyze this change · {chart.title}</h2>
          </div>
          <div>
            {conversationId ? (
              <Link href={`/chats/${conversationId}`}>Open in Data Chat</Link>
            ) : null}
            <button type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </header>
        <div className={styles.frozenChart} aria-label="Frozen selected chart">
          <DashboardRenderer chart={chart} result={result} />
        </div>
        <div className={styles.analysisChat}>
          {conversationId ? (
            <StandaloneDataChatLoader
              conversationId={conversationId}
              embedded
            />
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const trimmed = message.trim();
                if (!trimmed || submitting) return;
                setSubmitting(true);
                setError(undefined);
                void request<{ conversation_id: string }>(
                  `/api/dashboards/${dashboardId}/charts/${chart.id}/analyze`,
                  {
                    method: "POST",
                    body: JSON.stringify({
                      version_id: versionId,
                      tile_uuid: tileUuid,
                      dashboard_result_id: dashboardResultId,
                      dashboard_filters: filters,
                      drill_path: drillPath.map((step) => ({
                        field_id: step.fieldId,
                        value: step.value,
                      })),
                      selected_mark: selectedMark,
                      message: trimmed,
                    }),
                  },
                )
                  .then((created) => setConversationId(created.conversation_id))
                  .catch((cause) =>
                    setError(
                      cause instanceof Error
                        ? cause.message
                        : "Analysis could not start",
                    ),
                  )
                  .finally(() => setSubmitting(false));
              }}
            >
              <p>
                The exact result, receipt, filters, drill path, selected mark,
                dbt commit, and semantic slice will be attached server-side.
              </p>
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={4}
              />
              {error ? <p className={styles.errorState}>{error}</p> : null}
              <button type="submit" disabled={submitting}>
                {submitting ? "Starting private analysis…" : "Start analysis"}
              </button>
            </form>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}
