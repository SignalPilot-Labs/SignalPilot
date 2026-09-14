"use client";

import { useCallback, useEffect, useState } from "react";
import { Link, Loader2, MessageSquare, Palette } from "lucide-react";
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
import { PlanRequired } from "~/components/billing/plan-required";
import { NotionIcon } from "~/components/branding/notion-icon";
import { ThemeEditor } from "~/components/integrations/theme-editor";
import { useSubscription } from "~/lib/subscription-context";
import { AnthropicKeySection } from "./_components/anthropic-key-section";
import { NotionInstallationCard } from "./_components/notion-installation-card";
import { SlackInstallationCard } from "./_components/slack-installation-card";
import { useOrgSecrets } from "./_components/use-org-secrets";

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

export default function IntegrationsPage() {
  const { isLoaded } = useAppAuth();
  const { isBillable, isLoaded: subLoaded } = useSubscription();

  const gated = IS_CLOUD_MODE && subLoaded && !isBillable;

  if (!isLoaded || (IS_CLOUD_MODE && !subLoaded)) return <ApiKeysSkeleton />;
  if (gated) {
    return (
      <PlanRequired
        feature="integrations"
        description="Connect Notion and Slack to a governed project so the agent can publish and answer where your team works."
      />
    );
  }
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
  const orgSecretsState = useOrgSecrets();

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
        if (installation?.config?.enabled && installation.config.default_project_id && installation.config.parent_page_id) {
          if (active) toast("notion connected", "success");
          return;
        }
        if (!installation) {
          if (active) toast("notion connected, but installation was not found", "error");
          return;
        }

        if (active) toast("notion connected; complete setup", "success");
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
    const installation = oauthInstallations.find((candidate) => candidate.id === installationId);
    const selectedProjectId = projectSelections[installationId] || "";
    const selectedProject = workspaceProjects.find((project) => project.id === selectedProjectId);
    if (!selectedProject) {
      toast("select a project", "error");
      return;
    }

    const alreadyProvisioned = Boolean(installation?.config?.enabled);
    setProvisioningId(installationId);
    try {
      await provisionNotionOAuthInstallation(installationId, {
        default_project_id: selectedProject.id,
        default_branch: selectedProject.default_branch || "main",
        analysis_branch_mode: "per_request",
      });
      toast(alreadyProvisioned ? "notion setup saved" : "notion workspace provisioned", "success");
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
    (installation) => installation.config?.enabled && installation.config?.default_project_id && installation.config?.parent_page_id,
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
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-bg)] bg-[var(--color-text)] rounded-[10px] hover:opacity-90 transition-opacity duration-150 disabled:opacity-30"
            >
              {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <NotionIcon className="w-3 h-3" />}
              connect notion
            </button>
          )}
        </div>

        {loadError && (
          <div className="border border-[var(--color-error)]/20 bg-[var(--color-bg-card)] rounded-[14px] p-8 text-center">
            <p className="text-[12px] text-[var(--color-text-dim)] mb-3">
              failed to load integrations
            </p>
            <button
              disabled={loading}
              onClick={() => { setLoading(true); fetchIntegrations(); }}
              className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150 disabled:opacity-30"
            >
              retry
            </button>
          </div>
        )}

        {!loadError && visibleInstallations.length === 0 && (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-8 text-center">
            <Link className="w-6 h-6 text-[var(--color-text-dim)] mx-auto mb-3" strokeWidth={1} />
            <p className="text-[12px] text-[var(--color-text-dim)] mb-3">
              no oauth installs connected
            </p>
            <button
              onClick={handleConnectNotion}
              disabled={connecting}
              className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30"
            >
              {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <NotionIcon className="w-3 h-3" />}
              connect notion
            </button>
          </div>
        )}

        {visibleInstallations.map((installation) => (
          <NotionInstallationCard
            key={installation.id}
            installation={installation}
            workspaceProjects={workspaceProjects}
            projectsById={projectsById}
            selection={projectSelections[installation.id]}
            onSelectProject={(projectId) => setProjectSelections((prev) => ({ ...prev, [installation.id]: projectId }))}
            provisioning={provisioningId === installation.id}
            deleting={deletingOauthId === installation.id}
            onRequestDelete={() => setDeletingOauthId(installation.id)}
            onCancelDelete={() => setDeletingOauthId(null)}
            onDelete={() => handleDeleteOAuth(installation.id)}
            onProvision={() => handleProvision(installation.id)}
          />
        ))}
      </section>

      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <SectionHeader icon={MessageSquare} title="slack oauth" />
          {!hasConnectedSlackInstall && (
            <button
              onClick={handleConnectSlack}
              disabled={connectingSlack}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-bg)] bg-[var(--color-text)] rounded-[10px] hover:opacity-90 transition-opacity duration-150 disabled:opacity-30"
            >
              {connectingSlack ? <Loader2 className="w-3 h-3 animate-spin" /> : <MessageSquare className="w-3 h-3" />}
              connect slack
            </button>
          )}
        </div>

        {!loadError && visibleSlackInstallations.length === 0 && (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-8 text-center">
            <MessageSquare className="w-6 h-6 text-[var(--color-text-dim)] mx-auto mb-3" strokeWidth={1} />
            <p className="text-[12px] text-[var(--color-text-dim)] mb-3">
              no slack workspaces connected
            </p>
            <button
              onClick={handleConnectSlack}
              disabled={connectingSlack}
              className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30"
            >
              {connectingSlack ? <Loader2 className="w-3 h-3 animate-spin" /> : <MessageSquare className="w-3 h-3" />}
              connect slack
            </button>
          </div>
        )}

        {visibleSlackInstallations.map((installation) => (
          <SlackInstallationCard
            key={installation.id}
            installation={installation}
            workspaceProjects={workspaceProjects}
            projectsById={projectsById}
            selection={slackProjectSelections[installation.id]}
            onSelectProject={(projectId) => setSlackProjectSelections((prev) => ({ ...prev, [installation.id]: projectId }))}
            provisioning={provisioningSlackId === installation.id}
            deleting={deletingSlackId === installation.id}
            onRequestDelete={() => setDeletingSlackId(installation.id)}
            onCancelDelete={() => setDeletingSlackId(null)}
            onDelete={() => handleDeleteSlackOAuth(installation.id)}
            onProvision={() => handleProvisionSlack(installation.id)}
          />
        ))}
      </section>

      <AnthropicKeySection {...orgSecretsState} />

      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <SectionHeader icon={Palette} title="AI generations theme" />
        </div>
        <ThemeEditor />
      </section>
    </div>
  );
}
