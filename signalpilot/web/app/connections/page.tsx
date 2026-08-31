"use client";

import { ChevronDown, ChevronRight, Download, Plus, Shield, Upload } from "lucide-react";

import { ConnectionEditor } from "~/components/connections/editor/connection-editor";
import { ConnectionList } from "~/components/connections/connection-list";
import { useConnectionsController } from "~/components/connections/hooks/use-connections-controller";
import { PageLoader } from "~/components/ui/page-loader";
import { CONNECTIONS_TABS, PageHeader } from "~/components/ui/page-header";

import "./connections.css";

export default function ConnectionsPage() {
  const controller = useConnectionsController();
  const {
    connectionsLoading,
    connections,
    setShowForm,
    securityBannerExpanded,
    setSecurityBannerExpanded,
    healthData,
    planData,
    piiConfig,
    importFileRef,
    handleExport,
    handleImportFile,
  } = controller;

  if (connectionsLoading) return <PageLoader label="loading connections" />;

  return (
    <div className="connections-page animate-fade-in">
      <input
        ref={importFileRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={handleImportFile}
      />
      <PageHeader
        title="Connections"
        subtitle="Data access"
        tabs={CONNECTIONS_TABS}
        description="Manage governed warehouse access, health, schema visibility, and credential controls."
        actions={
          <div className="flex items-center gap-2">
            <a
              href="/query"
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150"
              title="Open the governed SQL query console"
            >
              query console
            </a>
            <button
              onClick={handleExport}
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150"
              title="Export connections"
            >
              <Download className="w-3 h-3" /> Export
            </button>
            <button
              onClick={() => importFileRef.current?.click()}
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150"
              title="Import connections from JSON"
            >
              <Upload className="w-3 h-3" /> Import
            </button>
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium rounded-[10px] transition-opacity duration-150 hover:opacity-90"
            >
              <Plus className="w-3.5 h-3.5" /> Add connection
            </button>
          </div>
        }
      />

      <section className="connections-overview" aria-label="Connection overview">
        <div><span>Connections</span><strong>{connections.length}/{planData?.limits.connections === "unlimited" ? "unlimited" : (planData?.limits.connections ?? "--")}</strong><small>{planData?.tier ?? "local"} plan</small></div>
        <div><span>Healthy</span><strong>{connections.filter((connection) => healthData[connection.name]?.status === "healthy").length}</strong><small>{connections.filter((connection) => !healthData[connection.name] || healthData[connection.name]?.status === "unknown").length} awaiting samples</small></div>
        <div><span>Needs attention</span><strong>{connections.filter((connection) => ["warning", "degraded", "unhealthy"].includes(healthData[connection.name]?.status ?? "")).length}</strong><small>Health and connectivity</small></div>
        <div><span>PII protection</span><strong>{Object.values(piiConfig).filter((config) => config.enabled).length}</strong><small>Active connections</small></div>
        <div className="connections-security">
          <Shield aria-hidden="true" />
          <div><strong>Credential custody active</strong><small>Encrypted storage, scoped access, audited use</small></div>
          <button type="button" onClick={() => setSecurityBannerExpanded(!securityBannerExpanded)} aria-expanded={securityBannerExpanded} aria-label="Show credential security details">{securityBannerExpanded ? <ChevronDown /> : <ChevronRight />}</button>
        </div>
        {securityBannerExpanded && <div className="connections-security-details"><span>Encrypted before persistence</span><span>PBKDF2 key derivation</span><span>Secrets decrypted in memory only</span><span>Connection access is audited</span><span>Passwords are never returned</span></div>}
      </section>

      <ConnectionEditor controller={controller} />
      <ConnectionList controller={controller} />
    </div>
  );
}
