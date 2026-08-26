"use client";

import Link from "next/link";
import { useState } from "react";
import { createPortal } from "react-dom";

import { StandaloneChatComposer } from "~/components/chat/standalone-chat-composer";
import { StandaloneDataChatLoader } from "~/components/chat/standalone-data-chat-loader";
import { DashboardRenderer } from "~/components/dashboard/dashboard-renderer";
import { request } from "~/lib/api";
import type {
  ChartDefinition,
  DashboardDrillStep,
  DashboardQueryResult,
  DashboardRuntimeFilter,
} from "~/lib/dashboard/contracts";
import { formatDashboardTimestamp } from "~/lib/dashboard/semantic-formatter";

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
  const [draft, setDraft] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  const startAnalysis = (message: string) => {
    if (submitting) return;
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
          message,
        }),
      },
    )
      .then((created) => setConversationId(created.conversation_id))
      .catch((cause) => {
        setError(
          cause instanceof Error ? cause.message : "Analysis could not start",
        );
      })
      .finally(() => setSubmitting(false));
  };

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
        <div className={styles.analysisWorkspace}>
          <div
            className={styles.analysisChat}
            aria-label="Chart analysis conversation"
          >
            {conversationId ? (
              <StandaloneDataChatLoader
                conversationId={conversationId}
                embedded
              />
            ) : (
              <div className={styles.analysisChatDraft}>
                <div className={styles.analysisChatIntro}>
                  <h3>Ask about {chart.title}</h3>
                  <p>
                    Your first message will include this frozen result and its
                    governed context.
                  </p>
                  {submitting ? (
                    <span role="status">Opening chart analysis…</span>
                  ) : null}
                  {error ? <p role="alert">{error}</p> : null}
                </div>
                <StandaloneChatComposer
                  value={draft}
                  onValueChange={setDraft}
                  onSubmit={startAnalysis}
                  submitDisabled={submitting}
                  placeholder="Ask a question about this chart…"
                />
              </div>
            )}
          </div>
          <div
            className={styles.frozenChart}
            aria-label="Frozen selected chart"
          >
            <div className={styles.frozenChartVisual}>
              <DashboardRenderer chart={chart} result={result} />
            </div>
            <footer className={styles.frozenChartCaption}>
              {result.completeness === "complete"
                ? "Complete result"
                : "Result may be incomplete"}
              {" · "}Updated{" "}
              {formatDashboardTimestamp(result.freshnessAt, result)}
            </footer>
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}
