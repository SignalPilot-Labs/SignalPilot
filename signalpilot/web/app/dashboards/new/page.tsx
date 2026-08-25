"use client";

import { useEffect, useState } from "react";

import {
  DashboardAuthoringWorkspace,
  type DashboardAuthoringSession,
} from "~/components/dashboard/dashboard-authoring-panel";
import { DashboardLoadingState } from "~/components/dashboard/dashboard-loading-state";
import { getWorkspaceProjects, request } from "~/lib/api";
import type { WorkspaceProjectInfo } from "~/lib/types";

export default function NewDashboardPage() {
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [projectId, setProjectId] = useState("");
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const [session, setSession] = useState<DashboardAuthoringSession>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    void getWorkspaceProjects("active")
      .then(({ projects: available }) => {
        setProjects(available);
        setProjectId(available[0]?.id ?? "");
        const sessionId = new URLSearchParams(window.location.search).get(
          "authoring",
        );
        if (sessionId) {
          return request<DashboardAuthoringSession>(
            `/api/dashboard-authoring/sessions/${sessionId}`,
          ).then(setSession);
        }
      })
      .catch((cause) =>
        setError(
          cause instanceof Error
            ? cause.message
            : "Dashboard authoring could not load",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <DashboardLoadingState label="Restoring dashboard authoring…" page />
    );
  }
  if (error) return <main style={{ padding: 32 }}>{error}</main>;
  const selected = projects.find((project) => project.id === projectId);
  return (
    <main style={{ height: "100dvh", padding: 16 }}>
      <DashboardAuthoringWorkspace
        createContext={{
          project_id: projectId,
          branch: selected?.default_branch ?? "main",
          timezone,
        }}
        contextControls={
          <>
            <label>
              Project
              <select
                value={projectId}
                disabled={Boolean(session)}
                onChange={(event) => setProjectId(event.target.value)}
              >
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Timezone
              <input
                value={session?.definition.signalPilot.timezone ?? timezone}
                disabled={Boolean(session)}
                onChange={(event) => setTimezone(event.target.value)}
              />
            </label>
          </>
        }
        session={session}
        onSession={setSession}
        onApplied={(detail) =>
          window.location.assign(
            `/dashboards/${detail.dashboard.id}?version=${detail.version.id}`,
          )
        }
        onDiscard={() => {
          const url = new URL(window.location.href);
          url.searchParams.delete("authoring");
          window.history.replaceState({}, "", url);
        }}
      />
    </main>
  );
}
