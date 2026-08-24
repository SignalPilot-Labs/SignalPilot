"use client";

import { useEffect, useState } from "react";

import type { DashboardAuthoringSession } from "~/components/dashboard/dashboard-authoring-panel";
import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import { getWorkspaceProjects, request } from "~/lib/api";
import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
import type { WorkspaceProjectInfo } from "~/lib/types";

export default function NewDashboardPage() {
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [projectId, setProjectId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const [preview, setPreview] = useState<DashboardAuthoringSession>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});

  useEffect(() => {
    void getWorkspaceProjects("active")
      .then(({ projects: available }) => {
        setProjects(available);
        setProjectId(available[0]?.id ?? "");
      })
      .catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "Projects could not load",
        ),
      );
  }, []);
  const selected = projects.find((project) => project.id === projectId);

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: 32 }}>
      <span style={{ color: "var(--color-text-dim)", fontSize: 12 }}>
        Private governed dashboard
      </span>
      <h1>Create with AI</h1>
      <p>
        One prompt produces a validated unsaved definition. Nothing becomes
        durable until you select Apply.
      </p>
      {preview ? (
        <section
          style={{
            border: "1px solid var(--color-border-active)",
            borderRadius: 12,
            padding: 18,
            marginTop: 24,
          }}
        >
          <span>Unsaved preview</span>
          <h2>{preview.definition.name}</h2>
          <p>{preview.summary}</p>
          <div style={{ margin: "18px -18px" }}>
            <DashboardRuntimeProvider
              key={`${preview.id}:${preview.custom_sql_confirmed}`}
              dashboardId={`draft:${preview.id}`}
              versionId={`draft:${preview.id}`}
              definition={preview.definition}
              authoringSessionId={preview.id}
              onVisibleReceiptsChange={setReceipts}
              analysisEnabled={false}
            />
          </div>
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
                  visible_complete_result_ids: Object.values(receipts)
                    .filter((receipt) => receipt.completeness === "complete")
                    .map((receipt) => receipt.dashboard_result_id),
                }),
              })
                .then((detail) =>
                  window.location.assign(
                    `/dashboards/${detail.dashboard.id}?version=${detail.version.id}`,
                  ),
                )
                .catch((cause) =>
                  setError(
                    cause instanceof Error
                      ? cause.message
                      : "Dashboard could not be applied",
                  ),
                )
                .finally(() => setBusy(false));
            }}
          >
            {busy ? "Applying…" : "Apply private dashboard"}
          </button>
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
                  .then(setPreview)
                  .catch((cause) =>
                    setError(
                      cause instanceof Error
                        ? cause.message
                        : "Custom SQL could not be confirmed",
                    ),
                  )
                  .finally(() => setBusy(false));
              }}
              style={{ marginLeft: 8 }}
            >
              Confirm low-confidence custom SQL
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={() => setPreview(undefined)}
            style={{ marginLeft: 8 }}
          >
            Discard
          </button>
        </section>
      ) : (
        <form
          style={{ display: "grid", gap: 14, marginTop: 24 }}
          onSubmit={(event) => {
            event.preventDefault();
            if (!projectId || !prompt.trim() || busy) return;
            setBusy(true);
            setError(undefined);
            void request<DashboardAuthoringSession>(
              "/api/dashboard-authoring/sessions",
              {
                method: "POST",
                body: JSON.stringify({
                  project_id: projectId,
                  branch: selected?.default_branch ?? "main",
                  timezone,
                  prompt: prompt.trim(),
                }),
              },
            )
              .then(setPreview)
              .catch((cause) =>
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Dashboard draft was rejected",
                ),
              )
              .finally(() => setBusy(false));
          }}
        >
          <label>
            Project
            <select
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              style={{
                display: "block",
                width: "100%",
                marginTop: 6,
                padding: 10,
              }}
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Dashboard timezone
            <input
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
              style={{
                display: "block",
                width: "100%",
                marginTop: 6,
                padding: 10,
              }}
            />
          </label>
          <label>
            What should this dashboard explain?
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={8}
              style={{
                display: "block",
                width: "100%",
                marginTop: 6,
                padding: 10,
              }}
              placeholder="Create an executive dashboard across the approved profitability and customer models…"
            />
          </label>
          <button
            type="submit"
            disabled={busy || !projectId || !prompt.trim()}
            style={{ padding: 10 }}
          >
            {busy ? "Generating and validating…" : "Generate governed preview"}
          </button>
        </form>
      )}
      {error ? <p style={{ color: "var(--color-error)" }}>{error}</p> : null}
    </main>
  );
}
