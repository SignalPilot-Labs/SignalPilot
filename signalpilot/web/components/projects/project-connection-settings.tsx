"use client";

import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Database,
  ExternalLink,
  Loader2,
  Save,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PageHeader, TerminalBar } from "~/components/ui/page-header";
import { StatusDot } from "~/components/ui/data-viz";
import { useToast } from "~/components/ui/toast";
import {
  getConnections,
  getStandaloneChatProjectReadiness,
  getWorkspaceProject,
  testConnection,
  updateWorkspaceProject,
} from "~/lib/api";
import type { ConnectionInfo, WorkspaceProjectInfo } from "~/lib/types";

type ProjectReadiness = Awaited<
  ReturnType<typeof getStandaloneChatProjectReadiness>
>;

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function ProjectConnectionSettings({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { toast } = useToast();
  const [project, setProject] = useState<WorkspaceProjectInfo | null>(null);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [selectedConnection, setSelectedConnection] = useState("");
  const [readiness, setReadiness] = useState<ProjectReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");

    void Promise.all([getWorkspaceProject(projectId), getConnections()])
      .then(async ([nextProject, nextConnections]) => {
        if (!active) return;
        setProject(nextProject);
        setConnections(nextConnections);
        setSelectedConnection(nextProject.connection_name ?? "");
        try {
          const nextReadiness =
            await getStandaloneChatProjectReadiness(projectId);
          if (active) setReadiness(nextReadiness);
        } catch {
          // Project connection configuration remains available when Data Chat
          // is disabled or its readiness endpoint is unavailable.
        }
      })
      .catch((error) => {
        if (active) setLoadError(errorMessage(error));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [projectId]);

  const saveConnection = async () => {
    if (!selectedConnection || saving) return;
    setSaving(true);
    setValidationError("");

    try {
      const validation = await testConnection(selectedConnection);
      if (validation.status !== "healthy") {
        setValidationError(
          validation.message || "This connection is not ready for production use.",
        );
        return;
      }

      const updated = await updateWorkspaceProject(projectId, {
        connection_name: selectedConnection,
      });
      setProject(updated);

      try {
        const nextReadiness =
          await getStandaloneChatProjectReadiness(projectId);
        setReadiness(nextReadiness);
      } catch {
        setReadiness(null);
      }

      toast("Production connection assigned", "success");
    } catch (error) {
      setValidationError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  if (loadError || !project) {
    return (
      <div className="max-w-3xl p-8">
        <button
          type="button"
          onClick={() => router.push("/projects")}
          className="mb-6 inline-flex items-center gap-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Projects
        </button>
        <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-5 text-sm text-[var(--color-error)]">
          {loadError || "Project not found"}
        </div>
      </div>
    );
  }

  const connectionChanged = selectedConnection !== (project.connection_name ?? "");

  return (
    <div className="max-w-3xl animate-fade-in p-8">
      <button
        type="button"
        onClick={() => router.push("/projects")}
        className="mb-6 inline-flex items-center gap-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Projects
      </button>

      <PageHeader
        title={project.display_name || project.name}
        subtitle="project settings"
        description="Assign the production data connection used by Data Chat and project runtimes."
      />

      <TerminalBar
        path={`projects/${project.name}/settings`}
        status={
          <StatusDot
            status={readiness?.ready ? "healthy" : "warning"}
            size={4}
          />
        }
      >
        <span className="text-xs text-[var(--color-text-dim)]">
          Data Chat: {readiness?.ready ? "ready" : "setup required"}
        </span>
      </TerminalBar>

      <section className="mt-8 overflow-hidden rounded-[14px] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <div className="border-b border-[var(--color-border)] p-6">
          <div className="flex items-start gap-3">
            <Database className="mt-0.5 h-4 w-4 text-[var(--color-success)]" />
            <div>
              <h2 className="text-sm font-medium text-[var(--color-text)]">
                Production data connection
              </h2>
              <p className="mt-1 text-xs leading-5 text-[var(--color-text-dim)]">
                SignalPilot validates the connection before assigning it to this
                project. Data Chat only runs when the complete project readiness
                check passes.
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-4 p-6">
          <div>
            <label
              htmlFor="project-production-connection"
              className="mb-1.5 block text-xs text-[var(--color-text-dim)]"
            >
              Connection
            </label>
            <select
              id="project-production-connection"
              value={selectedConnection}
              onChange={(event) => {
                setSelectedConnection(event.target.value);
                setValidationError("");
              }}
              disabled={saving}
              className="w-full rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 text-sm text-[var(--color-text)] focus:border-[var(--color-text-dim)] focus:outline-none disabled:opacity-60"
            >
              <option value="" disabled>
                Select a production connection
              </option>
              {connections.map((connection) => (
                <option key={connection.id} value={connection.name}>
                  {connection.name} · {connection.db_type}
                </option>
              ))}
            </select>
          </div>

          {connections.length === 0 && (
            <div className="rounded-lg border border-[var(--color-warning)]/25 p-3 text-xs text-[var(--color-warning)]">
              No data connections are available. Create and test one before
              assigning it to this project.
            </div>
          )}

          {validationError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-[var(--color-error)]/25 p-3 text-xs text-[var(--color-error)]"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{validationError}</span>
            </div>
          )}

          {readiness && !connectionChanged && (
            <div
              className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${
                readiness.ready
                  ? "border-[var(--color-success)]/25 text-[var(--color-success)]"
                  : "border-[var(--color-warning)]/25 text-[var(--color-warning)]"
              }`}
            >
              {readiness.ready ? (
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              ) : (
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              )}
              <span>{readiness.message}</span>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <a
              href="/connections"
              className="inline-flex items-center gap-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
            >
              Manage connections <ExternalLink className="h-3 w-3" />
            </a>
            <button
              type="button"
              onClick={() => void saveConnection()}
              disabled={!selectedConnection || saving}
              className="inline-flex items-center gap-2 rounded-[10px] bg-[var(--color-text)] px-4 py-2 text-xs font-medium text-[var(--color-bg)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              {saving ? "Validating…" : "Validate and save"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
