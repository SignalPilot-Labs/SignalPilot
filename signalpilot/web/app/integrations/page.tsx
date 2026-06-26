"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BookOpen,
  Database,
  ExternalLink,
  Link,
  Loader2,
  MessageSquare,
  Trash2,
  X,
} from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import {
  deleteNotionOAuthInstallation,
  deleteSlackOAuthInstallation,
  getWorkspaceProjects,
  getNotionOAuthInstallations,
  getSlackOAuthInstallations,
  provisionNotionOAuthInstallation,
  provisionSlackOAuthInstallation,
  startNotionOAuth,
  startSlackOAuth,
  type NotionOAuthInstallation,
  type SlackOAuthInstallation,
} from "~/lib/api";
import type { WorkspaceProjectInfo } from "~/lib/types";
import { PageHeader, TerminalBar } from "~/components/ui/page-header";
import { StatusDot } from "~/components/ui/data-viz";
import { SectionHeader } from "~/components/ui/section-header";
import { useToast } from "~/components/ui/toast";
import { ApiKeysSkeleton } from "~/components/ui/skeleton";
import { NotebooksProjectsPaywall } from "~/components/billing/notebooks-projects-paywall";
import { NotionIcon } from "~/components/branding/notion-icon";
import { useSubscription } from "~/lib/subscription-context";

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
const PAID_TIERS = ["pro", "team", "enterprise", "unlimited"];

function oauthStatus(installation: NotionOAuthInstallation): { label: string; tone: "healthy" | "warning" | "error" | "unknown" } {
  if (installation.status === "disconnected") return { label: "disconnected", tone: "error" };
  if (installation.config?.enabled && installation.config?.default_project_id) return { label: "active", tone: "healthy" };
  if (installation.config?.enabled && !installation.config?.default_project_id) return { label: "needs setup", tone: "warning" };
  if (installation.status === "connected") return { label: "needs setup", tone: "warning" };
  return { label: installation.status || "unknown", tone: "unknown" };
}

function slackStatus(installation: SlackOAuthInstallation): { label: string; tone: "healthy" | "warning" | "error" | "unknown" } {
  if (installation.status === "disconnected") return { label: "disconnected", tone: "error" };
  if (installation.config?.enabled && installation.config?.default_project_id) return { label: "active", tone: "healthy" };
  if (installation.status === "connected") return { label: "needs setup", tone: "warning" };
  return { label: installation.status || "unknown", tone: "unknown" };
}

function shortenedId(id: string | null | undefined): string {
  return id ? `${id.slice(0, 12)}...` : "-";
}

function notionPageUrl(id: string | null | undefined): string | null {
  if (!id) return null;
  return `https://www.notion.so/${id.replace(/-/g, "")}`;
}

function projectLabel(project: WorkspaceProjectInfo): string {
  return project.display_name || project.name || project.id;
}

export default function IntegrationsPage() {
  const { isLoaded } = useAppAuth();
  const { planTier, isLoaded: subLoaded } = useSubscription();

  const isPaid = PAID_TIERS.includes(planTier);
  const gated = IS_CLOUD_MODE && subLoaded && !isPaid;

  if (!isLoaded || (IS_CLOUD_MODE && !subLoaded)) return <ApiKeysSkeleton />;
  if (gated) return <NotebooksProjectsPaywall />;
  return <IntegrationsContent />;
}

function IntegrationsContent() {
  const { toast } = useToast();

  const [oauthInstallations, setOauthInstallations] = useState<NotionOAuthInstallation[]>([]);
  const [slackInstallations, setSlackInstallations] = useState<SlackOAuthInstallation[]>([]);
  const [workspaceProjects, setWorkspaceProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [projectSelections, setProjectSelections] = useState<Record<string, string>>({});
  const [slackProjectSelections, setSlackProjectSelections] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectingSlack, setConnectingSlack] = useState(false);
  const [provisioningId, setProvisioningId] = useState<string | null>(null);
  const [provisioningSlackId, setProvisioningSlackId] = useState<string | null>(null);
  const [deletingOauthId, setDeletingOauthId] = useState<string | null>(null);
  const [deletingSlackId, setDeletingSlackId] = useState<string | null>(null);

  const fetchIntegrations = useCallback(async () => {
    try {
      const [installations, slackInstalls, projectResult] = await Promise.all([
        getNotionOAuthInstallations(),
        getSlackOAuthInstallations(),
        getWorkspaceProjects("active"),
      ]);
      setOauthInstallations(installations);
      setSlackInstallations(slackInstalls);
      setWorkspaceProjects(projectResult.projects);
      setProjectSelections((prev) => {
        const next = { ...prev };
        const activeInstallationIds = new Set(installations.map((installation) => installation.id));
        for (const id of Object.keys(next)) {
          if (!activeInstallationIds.has(id)) delete next[id];
        }
        for (const installation of installations) {
          const configuredProjectId = installation.config?.default_project_id || "";
          if (configuredProjectId || next[installation.id] === undefined) {
            next[installation.id] = configuredProjectId;
          }
        }
        return next;
      });
      setSlackProjectSelections((prev) => {
        const next = { ...prev };
        const activeInstallationIds = new Set(slackInstalls.map((installation) => installation.id));
        for (const id of Object.keys(next)) {
          if (!activeInstallationIds.has(id)) delete next[id];
        }
        for (const installation of slackInstalls) {
          const configuredProjectId = installation.config?.default_project_id || "";
          if (configuredProjectId || next[installation.id] === undefined) {
            next[installation.id] = configuredProjectId;
          }
        }
        return next;
      });
      setLoadError(false);
      return { notionInstallations: installations, slackInstallations: slackInstalls };
    } catch {
      setLoadError(true);
      toast("failed to load integrations", "error");
      return null;
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { fetchIntegrations(); }, [fetchIntegrations]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const notion = params.get("notion");
    const installationId = params.get("installation_id");
    const slack = params.get("slack");
    const slackInstallationId = params.get("slack_installation_id");
    if (!notion && !slack) return;
    params.delete("notion");
    params.delete("installation_id");
    params.delete("slack");
    params.delete("slack_installation_id");
    const next = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${next ? `?${next}` : ""}`);

    if (slack) {
      if (slack !== "connected" || !slackInstallationId) {
        toast(slack === "connected" ? "slack connected" : `slack ${slack}`, slack === "connected" ? "success" : "error");
        return;
      }

      const oauthInstallationId = slackInstallationId;
      let active = true;
      async function refreshSlackInstall() {
        setLoading(true);
        try {
          const result = await fetchIntegrations();

          if (!result) return;

          const installation = result.slackInstallations.find((candidate) => candidate.id === oauthInstallationId);
          if (installation?.config?.enabled) {
            if (active) toast("slack connected", "success");
            return;
          }
          if (!installation) {
            if (active) toast("slack connected, but installation was not found", "error");
            return;
          }

          if (active) toast("slack connected; select a project", "success");
        } catch (e) {
          if (active) {
            setLoading(false);
            toast(`failed to load slack install: ${e}`, "error", 6000);
          }
        }
      }

      refreshSlackInstall();
      return () => {
        active = false;
      };
    }

    if (!notion) return;
    if (notion !== "connected" || !installationId) {
      toast(notion === "connected" ? "notion connected" : `notion ${notion}`, notion === "connected" ? "success" : "error");
      return;
    }

    const oauthInstallationId = installationId;
    let active = true;
    async function refreshOAuthInstall() {
      setLoading(true);
      try {
        const result = await fetchIntegrations();

        if (!result) return;

        const installation = result.notionInstallations.find((candidate) => candidate.id === oauthInstallationId);
        if (installation?.config?.enabled) {
          if (active) toast("notion connected", "success");
          return;
        }
        if (!installation) {
          if (active) toast("notion connected, but installation was not found", "error");
          return;
        }

        if (active) toast("notion connected; select a project", "success");
      } catch (e) {
        if (active) {
          setLoading(false);
          toast(`failed to load notion install: ${e}`, "error", 6000);
        }
      }
    }

    refreshOAuthInstall();
    return () => {
      active = false;
    };
  }, [fetchIntegrations, toast]);

  async function handleConnectNotion() {
    setConnecting(true);
    try {
      const response = await startNotionOAuth(window.location.origin + "/integrations");
      window.location.href = response.authorize_url;
    } catch (e) {
      toast(`failed to start oauth: ${e}`, "error");
      setConnecting(false);
    }
  }

  async function handleConnectSlack() {
    setConnectingSlack(true);
    try {
      const response = await startSlackOAuth(window.location.origin + "/integrations");
      window.location.href = response.authorize_url;
    } catch (e) {
      toast(`failed to start slack oauth: ${e}`, "error");
      setConnectingSlack(false);
    }
  }

  async function handleProvision(installationId: string) {
    const selectedProjectId = projectSelections[installationId] || "";
    const selectedProject = workspaceProjects.find((project) => project.id === selectedProjectId);
    if (!selectedProject) {
      toast("select a project", "error");
      return;
    }

    const installation = oauthInstallations.find((candidate) => candidate.id === installationId);
    const alreadyProvisioned = Boolean(installation?.config?.enabled);

    setProvisioningId(installationId);
    try {
      await provisionNotionOAuthInstallation(installationId, {
        default_project_id: selectedProject.id,
        default_branch: selectedProject.default_branch || "main",
        analysis_branch_mode: "per_request",
      });
      toast(alreadyProvisioned ? "default project saved" : "notion workspace provisioned", "success");
      await fetchIntegrations();
    } catch (e) {
      toast(`provision failed: ${e}`, "error");
    } finally {
      setProvisioningId(null);
    }
  }

  async function handleProvisionSlack(installationId: string) {
    const selectedProjectId = slackProjectSelections[installationId] || "";
    const selectedProject = workspaceProjects.find((project) => project.id === selectedProjectId);
    if (!selectedProject) {
      toast("select a project", "error");
      return;
    }

    const installation = slackInstallations.find((candidate) => candidate.id === installationId);
    const alreadyProvisioned = Boolean(installation?.config?.enabled);

    setProvisioningSlackId(installationId);
    try {
      await provisionSlackOAuthInstallation(installationId, {
        default_project_id: selectedProject.id,
        default_branch: selectedProject.default_branch || "main",
        analysis_branch_mode: "per_request",
        allowed_channel_ids: installation?.config?.allowed_channel_ids || [],
      });
      toast(alreadyProvisioned ? "slack default project saved" : "slack workspace enabled", "success");
      await fetchIntegrations();
    } catch (e) {
      toast(`slack setup failed: ${e}`, "error");
    } finally {
      setProvisioningSlackId(null);
    }
  }

  async function handleDeleteOAuth(installationId: string) {
    try {
      await deleteNotionOAuthInstallation(installationId);
      setDeletingOauthId(null);
      toast("oauth install disconnected", "success");
      await fetchIntegrations();
    } catch (e) {
      toast(`failed: ${e}`, "error");
    }
  }

  async function handleDeleteSlackOAuth(installationId: string) {
    try {
      await deleteSlackOAuthInstallation(installationId);
      setDeletingSlackId(null);
      toast("slack install disconnected", "success");
      await fetchIntegrations();
    } catch (e) {
      toast(`failed: ${e}`, "error");
    }
  }

  if (loading) return <ApiKeysSkeleton />;

  const visibleInstallations = oauthInstallations.filter((installation) => installation.status !== "disconnected");
  const visibleSlackInstallations = slackInstallations.filter((installation) => installation.status !== "disconnected");
  const hasConnectedInstall = visibleInstallations.length > 0;
  const hasConnectedSlackInstall = visibleSlackInstallations.length > 0;
  const activeOauthCount = visibleInstallations.filter(
    (installation) => installation.config?.enabled && installation.config?.default_project_id,
  ).length;
  const activeSlackCount = visibleSlackInstallations.filter(
    (installation) => installation.config?.enabled && installation.config?.default_project_id,
  ).length;
  const projectsById = new Map(workspaceProjects.map((project) => [project.id, project]));

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="integrations"
        subtitle="notion + slack"
        description="connect external services to signalpilot"
      />

      <TerminalBar
        path="integrations --list"
        status={<StatusDot status={activeOauthCount + activeSlackCount > 0 ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            active: <code className="text-[12px] text-[var(--color-text)]">{activeOauthCount + activeSlackCount}</code>
          </span>
        </div>
      </TerminalBar>

      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <SectionHeader icon={Link} title="notion oauth" />
          {!hasConnectedInstall && (
            <button
              onClick={handleConnectNotion}
              disabled={connecting}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-bg)] bg-[var(--color-text)] hover:opacity-90 transition-all tracking-wider uppercase disabled:opacity-30"
            >
              {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <NotionIcon className="w-3 h-3" />}
              connect notion
            </button>
          )}
        </div>

        {loadError && (
          <div className="border border-[var(--color-error)]/20 bg-[var(--color-bg-card)] p-8 text-center">
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mb-3">
              failed to load integrations
            </p>
            <button
              disabled={loading}
              onClick={() => { setLoading(true); fetchIntegrations(); }}
              className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase disabled:opacity-30"
            >
              retry
            </button>
          </div>
        )}

        {!loadError && visibleInstallations.length === 0 && (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8 text-center">
            <Link className="w-6 h-6 text-[var(--color-text-dim)] mx-auto mb-3" strokeWidth={1} />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mb-3">
              no oauth installs connected
            </p>
            <button
              onClick={handleConnectNotion}
              disabled={connecting}
              className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
            >
              {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <NotionIcon className="w-3 h-3" />}
              connect notion
            </button>
          </div>
        )}

        {visibleInstallations.map((installation) => {
          const status = oauthStatus(installation);
          const triggerUrl = notionPageUrl(installation.config?.trigger_page_id);
          const requestsUrl = notionPageUrl(installation.config?.requests_database_page_id);
          return (
            <div key={installation.id} className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-3">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2">
                    <BookOpen className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
                    <span className="text-[13px] text-[var(--color-text)] tracking-wider font-medium">
                      {installation.workspace_name || installation.workspace_id}
                    </span>
                    <StatusDot status={status.tone} size={4} />
                    <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider uppercase">{status.label}</span>
                  </div>
                  <div className="space-y-1 text-[11px] text-[var(--color-text-dim)] tracking-wider">
                    <p className="flex items-center gap-1.5">
                      <span>trigger page:</span>
                      <span className="text-[var(--color-text-muted)] font-mono">{shortenedId(installation.config?.trigger_page_id)}</span>
                      {triggerUrl && (
                        <a href={triggerUrl} target="_blank" rel="noopener noreferrer" title="open trigger page in Notion" aria-label="open trigger page in Notion" className="inline-flex h-4 w-4 items-center justify-center text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </p>
                    <p className="flex items-center gap-1.5">
                      <span>requests database:</span>
                      <span className="text-[var(--color-text-muted)] font-mono">{shortenedId(installation.config?.requests_database_page_id)}</span>
                      {requestsUrl && (
                        <a href={requestsUrl} target="_blank" rel="noopener noreferrer" title="open requests database in Notion" aria-label="open requests database in Notion" className="inline-flex h-4 w-4 items-center justify-center text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </p>
                    <p className="flex items-center gap-1.5">
                      <span>
                        default project:
                        {!installation.config?.default_project_id && (
                          <span className="ml-1 text-[var(--color-error)]">*</span>
                        )}
                      </span>
                      <span className="text-[var(--color-text-muted)] font-mono truncate">
                        {(() => {
                          const project = installation.config?.default_project_id
                            ? projectsById.get(installation.config.default_project_id)
                            : null;
                          return project
                            ? projectLabel(project)
                            : shortenedId(installation.config?.default_project_id);
                        })()}
                      </span>
                    </p>
                  </div>
                </div>

                {deletingOauthId === installation.id ? (
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => handleDeleteOAuth(installation.id)} className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/30 hover:border-[var(--color-error)] transition-all tracking-wider uppercase">confirm</button>
                    <button onClick={() => setDeletingOauthId(null)} className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"><X className="w-3 h-3" /></button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDeletingOauthId(installation.id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)]/50 hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
                  >
                    <Trash2 className="w-3 h-3" />
                    disconnect
                  </button>
                )}
              </div>

              {(() => {
                const configuredProjectId = installation.config?.default_project_id || "";
                const selectedProjectId = projectSelections[installation.id] ?? configuredProjectId;
                const selectedProject = selectedProjectId ? projectsById.get(selectedProjectId) : null;
                const projectChanged = selectedProjectId !== configuredProjectId;
                const canSubmitProject =
                  Boolean(selectedProject) &&
                  provisioningId !== installation.id &&
                  (!installation.config?.enabled || projectChanged);

                return (
                  <div className="border-t border-[var(--color-border)] pt-4">
                    <label htmlFor={`notion-project-${installation.id}`} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">
                      default project
                      <span className="ml-1 text-[var(--color-error)]">*</span>
                    </label>
                    <div className="flex flex-col sm:flex-row gap-2">
                      <select
                        id={`notion-project-${installation.id}`}
                        value={selectedProjectId}
                        onChange={(event) => {
                          setProjectSelections((prev) => ({
                            ...prev,
                            [installation.id]: event.target.value,
                          }));
                        }}
                        disabled={workspaceProjects.length === 0 || provisioningId === installation.id}
                        className="min-w-0 flex-1 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none disabled:opacity-40"
                      >
                        <option value="">
                          {workspaceProjects.length === 0 && !selectedProjectId ? "no active projects" : "select a project..."}
                        </option>
                        {selectedProjectId && !selectedProject && (
                          <option value={selectedProjectId}>configured project unavailable</option>
                        )}
                        {workspaceProjects.map((project) => (
                          <option key={project.id} value={project.id}>
                            {projectLabel(project)}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => handleProvision(installation.id)}
                        disabled={!canSubmitProject}
                        className="flex items-center justify-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
                      >
                        {provisioningId === installation.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Database className="w-3 h-3" />}
                        {installation.config?.enabled ? "save project" : "provision workspace"}
                      </button>
                    </div>
                  </div>
                );
              })()}
            </div>
          );
        })}
      </section>

      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <SectionHeader icon={MessageSquare} title="slack oauth" />
          {!hasConnectedSlackInstall && (
            <button
              onClick={handleConnectSlack}
              disabled={connectingSlack}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-bg)] bg-[var(--color-text)] hover:opacity-90 transition-all tracking-wider uppercase disabled:opacity-30"
            >
              {connectingSlack ? <Loader2 className="w-3 h-3 animate-spin" /> : <MessageSquare className="w-3 h-3" />}
              connect slack
            </button>
          )}
        </div>

        {!loadError && visibleSlackInstallations.length === 0 && (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8 text-center">
            <MessageSquare className="w-6 h-6 text-[var(--color-text-dim)] mx-auto mb-3" strokeWidth={1} />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mb-3">
              no slack workspaces connected
            </p>
            <button
              onClick={handleConnectSlack}
              disabled={connectingSlack}
              className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
            >
              {connectingSlack ? <Loader2 className="w-3 h-3 animate-spin" /> : <MessageSquare className="w-3 h-3" />}
              connect slack
            </button>
          </div>
        )}

        {visibleSlackInstallations.map((installation) => {
          const status = slackStatus(installation);
          return (
            <div key={installation.id} className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-3">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2">
                    <MessageSquare className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
                    <span className="text-[13px] text-[var(--color-text)] tracking-wider font-medium">
                      {installation.team_name || installation.team_id}
                    </span>
                    <StatusDot status={status.tone} size={4} />
                    <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider uppercase">{status.label}</span>
                  </div>
                  <div className="space-y-1 text-[11px] text-[var(--color-text-dim)] tracking-wider">
                    <p className="flex items-center gap-1.5">
                      <span>team:</span>
                      <span className="text-[var(--color-text-muted)] font-mono">{installation.team_id}</span>
                    </p>
                    <p className="flex items-center gap-1.5">
                      <span>bot user:</span>
                      <span className="text-[var(--color-text-muted)] font-mono">{installation.bot_user_id}</span>
                    </p>
                    <p className="flex items-center gap-1.5">
                      <span>
                        default project:
                        {!installation.config?.default_project_id && (
                          <span className="ml-1 text-[var(--color-error)]">*</span>
                        )}
                      </span>
                      <span className="text-[var(--color-text-muted)] font-mono truncate">
                        {(() => {
                          const project = installation.config?.default_project_id
                            ? projectsById.get(installation.config.default_project_id)
                            : null;
                          return project
                            ? projectLabel(project)
                            : shortenedId(installation.config?.default_project_id);
                        })()}
                      </span>
                    </p>
                  </div>
                </div>

                {deletingSlackId === installation.id ? (
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => handleDeleteSlackOAuth(installation.id)} className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/30 hover:border-[var(--color-error)] transition-all tracking-wider uppercase">confirm</button>
                    <button onClick={() => setDeletingSlackId(null)} className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"><X className="w-3 h-3" /></button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDeletingSlackId(installation.id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)]/50 hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
                  >
                    <Trash2 className="w-3 h-3" />
                    disconnect
                  </button>
                )}
              </div>

              {(() => {
                const configuredProjectId = installation.config?.default_project_id || "";
                const selectedProjectId = slackProjectSelections[installation.id] ?? configuredProjectId;
                const selectedProject = selectedProjectId ? projectsById.get(selectedProjectId) : null;
                const projectChanged = selectedProjectId !== configuredProjectId;
                const canSubmitProject =
                  Boolean(selectedProject) &&
                  provisioningSlackId !== installation.id &&
                  (!installation.config?.enabled || projectChanged);

                return (
                  <div className="border-t border-[var(--color-border)] pt-4">
                    <label htmlFor={`slack-project-${installation.id}`} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">
                      default project
                      <span className="ml-1 text-[var(--color-error)]">*</span>
                    </label>
                    <div className="flex flex-col sm:flex-row gap-2">
                      <select
                        id={`slack-project-${installation.id}`}
                        value={selectedProjectId}
                        onChange={(event) => {
                          setSlackProjectSelections((prev) => ({
                            ...prev,
                            [installation.id]: event.target.value,
                          }));
                        }}
                        disabled={workspaceProjects.length === 0 || provisioningSlackId === installation.id}
                        className="min-w-0 flex-1 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none disabled:opacity-40"
                      >
                        <option value="">
                          {workspaceProjects.length === 0 && !selectedProjectId ? "no active projects" : "select a project..."}
                        </option>
                        {selectedProjectId && !selectedProject && (
                          <option value={selectedProjectId}>configured project unavailable</option>
                        )}
                        {workspaceProjects.map((project) => (
                          <option key={project.id} value={project.id}>
                            {projectLabel(project)}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => handleProvisionSlack(installation.id)}
                        disabled={!canSubmitProject}
                        className="flex items-center justify-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
                      >
                        {provisioningSlackId === installation.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Database className="w-3 h-3" />}
                        {installation.config?.enabled ? "save project" : "enable workspace"}
                      </button>
                    </div>
                  </div>
                );
              })()}
            </div>
          );
        })}
      </section>
    </div>
  );
}
