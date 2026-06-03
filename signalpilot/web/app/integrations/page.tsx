"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BookOpen,
  Database,
  ExternalLink,
  Link,
  Loader2,
  Trash2,
  X,
} from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import {
  deleteNotionOAuthInstallation,
  getNotionOAuthInstallations,
  provisionNotionOAuthInstallation,
  startNotionOAuth,
  type NotionOAuthInstallation,
} from "~/lib/api";
import { PageHeader, TerminalBar } from "~/components/ui/page-header";
import { StatusDot } from "~/components/ui/data-viz";
import { SectionHeader } from "~/components/ui/section-header";
import { useToast } from "~/components/ui/toast";
import { ApiKeysSkeleton } from "~/components/ui/skeleton";

function oauthStatus(installation: NotionOAuthInstallation): { label: string; tone: "healthy" | "warning" | "error" | "unknown" } {
  if (installation.status === "disconnected") return { label: "disconnected", tone: "error" };
  if (installation.config?.enabled) return { label: "active", tone: "healthy" };
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

export default function IntegrationsPage() {
  const { isLoaded } = useAppAuth();
  if (!isLoaded) return <ApiKeysSkeleton />;
  return <IntegrationsContent />;
}

function IntegrationsContent() {
  const { toast } = useToast();

  const [oauthInstallations, setOauthInstallations] = useState<NotionOAuthInstallation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [provisioningId, setProvisioningId] = useState<string | null>(null);
  const [deletingOauthId, setDeletingOauthId] = useState<string | null>(null);

  const fetchIntegrations = useCallback(async () => {
    try {
      setOauthInstallations(await getNotionOAuthInstallations());
      setLoadError(false);
    } catch {
      setLoadError(true);
      toast("failed to load integrations", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { fetchIntegrations(); }, [fetchIntegrations]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const notion = params.get("notion");
    if (!notion) return;
    toast(notion === "connected" ? "notion connected" : `notion ${notion}`, notion === "connected" ? "success" : "error");
    params.delete("notion");
    params.delete("installation_id");
    const next = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${next ? `?${next}` : ""}`);
  }, [toast]);

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

  async function handleProvision(installationId: string) {
    setProvisioningId(installationId);
    try {
      await provisionNotionOAuthInstallation(installationId);
      toast("notion workspace provisioned", "success");
      await fetchIntegrations();
    } catch (e) {
      toast(`provision failed: ${e}`, "error");
    } finally {
      setProvisioningId(null);
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

  if (loading) return <ApiKeysSkeleton />;

  const visibleInstallations = oauthInstallations.filter((installation) => installation.status !== "disconnected");
  const hasConnectedInstall = visibleInstallations.length > 0;
  const activeOauthCount = visibleInstallations.filter((installation) => installation.config?.enabled).length;

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="integrations"
        subtitle="notion"
        description="connect external services to signalpilot"
      />

      <TerminalBar
        path="integrations --list"
        status={<StatusDot status={activeOauthCount > 0 ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            active: <code className="text-[12px] text-[var(--color-text)]">{activeOauthCount}</code>
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
              {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Link className="w-3 h-3" />}
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
              {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Link className="w-3 h-3" />}
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

              {!installation.config?.enabled && (
                <div className="flex justify-end">
                  <button
                    onClick={() => handleProvision(installation.id)}
                    disabled={provisioningId === installation.id}
                    className="flex items-center justify-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
                  >
                    {provisioningId === installation.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Database className="w-3 h-3" />}
                    provision workspace
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
