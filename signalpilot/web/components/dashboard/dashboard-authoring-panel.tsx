"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { request } from "~/lib/api";
import type { DashboardDefinition } from "~/lib/dashboard/contracts";
import { DashboardSpinner } from "~/components/dashboard/dashboard-loading-state";

import styles from "./dashboard-runtime.module.css";

export type DashboardAuthoringSession = {
  id: string;
  dashboard_id: string | null;
  base_version_id: string | null;
  definition: DashboardDefinition;
  operations: Array<Record<string, unknown>>;
  summary: string;
  status: string;
  requires_custom_sql_confirmation: boolean;
  custom_sql_confirmed: boolean;
};

export function DashboardAuthoringPanel({
  dashboardId,
  versionId,
  preview,
  visibleCompleteResultIds,
  onPreview,
  onDiscard,
}: {
  dashboardId: string;
  versionId: string;
  preview?: DashboardAuthoringSession;
  visibleCompleteResultIds: string[];
  onPreview: (preview: DashboardAuthoringSession) => void;
  onDiscard: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  if (!open) {
    return (
      <button
        className={styles.authoringLauncher}
        type="button"
        onClick={() => setOpen(true)}
      >
        <Sparkles size={16} aria-hidden="true" />
        Edit with AI
      </button>
    );
  }
  return (
    <aside
      className={styles.authoringPanel}
      aria-label="Dashboard AI authoring"
    >
      <header>
        <div>
          <span>Fresh authoring session per edit</span>
          <h2>Dashboard author</h2>
        </div>
        <button type="button" onClick={() => setOpen(false)}>
          Close
        </button>
      </header>
      {preview ? (
        <div className={styles.authoringPreview}>
          <strong>Unsaved governed preview</strong>
          <p>{preview.summary}</p>
          <small>
            {preview.operations.length} typed operation
            {preview.operations.length === 1 ? "" : "s"}
          </small>
          {preview.requires_custom_sql_confirmation ? (
            <p>
              Low confidence · custom SQL{" "}
              {preview.custom_sql_confirmed
                ? "explicitly confirmed"
                : "requires confirmation before execution"}
            </p>
          ) : null}
          <div>
            {preview.requires_custom_sql_confirmation &&
            !preview.custom_sql_confirmed ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setError(undefined);
                  void request<DashboardAuthoringSession>(
                    `/api/dashboard-authoring/sessions/${preview.id}/confirm-custom-sql`,
                    { method: "POST" },
                  )
                    .then(onPreview)
                    .catch((cause) =>
                      setError(
                        cause instanceof Error
                          ? cause.message
                          : "Custom SQL could not be confirmed",
                      ),
                    )
                    .finally(() => setBusy(false));
                }}
              >
                Confirm low-confidence custom SQL
              </button>
            ) : null}
            <button
              type="button"
              disabled={
                busy ||
                (preview.requires_custom_sql_confirmation &&
                  !preview.custom_sql_confirmed)
              }
              onClick={() => {
                setBusy(true);
                setError(undefined);
                void request<{
                  dashboard: { id: string };
                  version: { id: string };
                }>(`/api/dashboard-authoring/sessions/${preview.id}/apply`, {
                  method: "POST",
                  body: JSON.stringify({
                    expected_current_version_id: versionId,
                    visible_complete_result_ids: visibleCompleteResultIds,
                  }),
                })
                  .then((detail) => {
                    window.location.assign(
                      `/dashboards/${detail.dashboard.id}?version=${detail.version.id}`,
                    );
                  })
                  .catch((cause) =>
                    setError(
                      cause instanceof Error
                        ? cause.message
                        : "Preview could not be applied",
                    ),
                  )
                  .finally(() => setBusy(false));
              }}
            >
              {busy ? (
                <>
                  <DashboardSpinner size="small" /> Applying…
                </>
              ) : (
                "Apply exact preview"
              )}
            </button>
            <button type="button" disabled={busy} onClick={onDiscard}>
              Discard
            </button>
          </div>
        </div>
      ) : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = prompt.trim();
          if (!trimmed || busy) return;
          setBusy(true);
          setError(undefined);
          void request<DashboardAuthoringSession>(
            "/api/dashboard-authoring/sessions",
            {
              method: "POST",
              body: JSON.stringify({
                prompt: trimmed,
                dashboard_id: dashboardId,
                base_version_id: versionId,
              }),
            },
          )
            .then((created) => {
              onPreview(created);
              setPrompt("");
            })
            .catch((cause) =>
              setError(
                cause instanceof Error
                  ? cause.message
                  : "The authoring draft was rejected",
              ),
            )
            .finally(() => setBusy(false));
        }}
      >
        <label htmlFor="dashboard-authoring-prompt">Describe one change</label>
        <textarea
          id="dashboard-authoring-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={6}
          placeholder="Replace revenue with approved gross margin in the regional bar chart."
        />
        <p>
          The agent can draft typed changes. It cannot save, share, fork,
          export, or open analysis.
        </p>
        {error ? <p className={styles.errorState}>{error}</p> : null}
        <button type="submit" disabled={busy || !prompt.trim()}>
          {busy ? (
            <>
              <DashboardSpinner size="small" /> Validating draft…
            </>
          ) : (
            "Preview governed change"
          )}
        </button>
      </form>
    </aside>
  );
}
