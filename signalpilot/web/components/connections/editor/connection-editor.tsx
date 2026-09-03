"use client";

import type { Ref } from "react";
import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Clock, Copy, Filter, Link2, Loader2, Lock, RefreshCw, Settings2, Shield, Table2, TestTube, XCircle } from "lucide-react";

import { DbTypeIcon } from "~/components/connections/db-type-icon";
import { ConnectionFieldsForm } from "./connection-fields-form";
import { FormInput, fieldProps } from "./form-controls";
import { SslSection as SSLSection, SshSection as SSHSection } from "./security-sections";
import type { ConnectionsController } from "~/components/connections/hooks/use-connections-controller";
import { CONNECTOR_TIERS, DB_CONFIGS, DB_TYPE_ORDER, DB_VARIANTS, DEFAULT_VARIANT } from "~/lib/connections/connector-catalog";
import { DEFAULT_CONNECTION_FORM as defaultForm } from "~/lib/connections/defaults";
import { buildConnectionPreview, parseConnectionUrl } from "~/lib/connections/connection-url";

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

interface ConnectionEditorProps {
  controller: ConnectionsController;
}

export function ConnectionEditor({ controller }: ConnectionEditorProps) {
  const {
    toast, showForm, setShowForm, editingConnection, setEditingConnection,
    form, setForm, selectedVariant,
    showAdvanced, setShowAdvanced, advancedTab, setAdvancedTab, serverIp,
    preTesting, preTestResult, setPreTestResult, saving, formErrors,
    hasFormErrors, fieldRefs, serverFieldErrors, setServerFieldErrors,
    handleDbTypeChange, handleVariantChange, handlePreTest, handleCreate,
    handleSaveAndTest, config,
  } = controller;

  return (
    <>
      {showForm && (
        <div className="connection-form-shell animate-scale-in">
          <header>
            <div className="flex items-center gap-2">
              <DbTypeIcon type={form.db_type} />
              <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
                {editingConnection ? `edit ${editingConnection}` : `new ${DB_CONFIGS[form.db_type].label} connection`}
              </span>
            </div>
            <span className="text-[11px] text-[var(--color-text-dim)] opacity-50">
              {DB_CONFIGS[form.db_type].description}
            </span>
          </header>

          <div className="connection-form-body">
            {/* Step 1: database type */}
            <div className="mb-5">
              <label className="block text-[12px] text-[var(--color-text-dim)] mb-2">
                {editingConnection ? "database type" : <><span className="font-medium text-[var(--color-text)]">1.</span> select a database</>}
              </label>
              <div className="flex flex-wrap gap-1.5">
                {DB_TYPE_ORDER.filter((t) => !IS_CLOUD_MODE || t !== "sqlite").map((dbType) => {
                  const cfg = DB_CONFIGS[dbType];
                  const isSelected = form.db_type === dbType;
                  return (
                    <button
                      key={dbType}
                      onClick={() => handleDbTypeChange(dbType)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                        isSelected
                          ? "border-[var(--color-text)] text-[var(--color-text)] bg-[var(--color-text)]/5"
                          : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
                      }`}
                    >
                      <DbTypeIcon type={dbType} />
                      {cfg.label}
                      <span className={`text-[10px] opacity-60 ${CONNECTOR_TIERS[dbType]?.tier === 1 ? "text-emerald-400" : CONNECTOR_TIERS[dbType]?.tier === 2 ? "text-sky-400" : "text-zinc-400"}`}>
                        {CONNECTOR_TIERS[dbType]?.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Step 2: variant of the selected database type — only for new connections */}
            {!editingConnection && (() => {
              const variants = DB_VARIANTS[form.db_type] ?? [DEFAULT_VARIANT];
              const active = variants.find((v) => v.key === selectedVariant) ?? variants[0];
              return (
                <div className="mb-5">
                  <label className="block text-[12px] text-[var(--color-text-dim)] mb-2">
                    <span className="font-medium text-[var(--color-text)]">2.</span> where is your {DB_CONFIGS[form.db_type].label} running?
                  </label>
                  <div className="flex flex-wrap gap-1.5">
                    {variants.map((variant) => {
                      const isSelected = variant.key === active.key;
                      return (
                        <button
                          key={variant.key}
                          type="button"
                          onClick={() => handleVariantChange(variant)}
                          className={`flex items-center gap-1.5 px-3 py-1.5 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                            isSelected
                              ? "border-[var(--color-text)] text-[var(--color-text)] bg-[var(--color-text)]/5"
                              : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
                          }`}
                        >
                          {variant.label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-[11px] text-[var(--color-text-dim)] mt-1.5 opacity-70">{active.hint}</p>
                </div>
              );
            })()}

            {/* Name + Description */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              {editingConnection ? (
                <div>
                  <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">connection name</label>
                  <div className="px-3 py-2 bg-[var(--color-bg-hover)] border border-[var(--color-border)] rounded-[10px] text-xs text-[var(--color-text-dim)] font-mono">{editingConnection}</div>
                </div>
              ) : (
                <FormInput label="connection name" value={form.name} onChange={(v) => { setForm({ ...form, name: v }); setServerFieldErrors((prev) => { if (!("name" in prev)) return prev; const { name: _, ...rest } = prev; return rest; }); }} placeholder="prod-analytics" hint="alphanumeric, dashes, underscores" required {...fieldProps("name", formErrors, fieldRefs)} />
              )}
              <FormInput label="description" value={form.description} onChange={(v) => setForm({ ...form, description: v })} placeholder="Production analytics DB" />
            </div>

            {/* Tags */}
            <div className="mb-4">
              <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">tags</label>
              <div className="flex flex-wrap items-center gap-1.5">
                {form.tags.map((tag) => (
                  <span key={tag} className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-[var(--color-bg-hover)] border border-[var(--color-border)] rounded-[6px] text-[var(--color-text-dim)]">
                    {tag}
                    <button type="button" onClick={() => setForm({ ...form, tags: form.tags.filter(t => t !== tag) })} className="text-[var(--color-text-dim)] hover:text-[var(--color-error)] ml-0.5">&times;</button>
                  </span>
                ))}
                <input
                  type="text"
                  value={form.tagInput}
                  onChange={(e) => setForm({ ...form, tagInput: e.target.value })}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === ",") && form.tagInput.trim()) {
                      e.preventDefault();
                      const tag = form.tagInput.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
                      if (tag && !form.tags.includes(tag)) {
                        setForm({ ...form, tags: [...form.tags, tag], tagInput: "" });
                      } else {
                        setForm({ ...form, tagInput: "" });
                      }
                    }
                  }}
                  placeholder={form.tags.length === 0 ? "prod, analytics, team-data..." : "add tag..."}
                  className="flex-1 min-w-[100px] px-2 py-1 text-[12px] bg-transparent border-none outline-none text-[var(--color-text)] placeholder:text-[var(--color-text-dim)]"
                />
              </div>
              <p className="text-[11px] text-[var(--color-text-dim)] mt-1 opacity-60">press enter or comma to add — organize connections by environment, team, or purpose</p>
            </div>

            {/* Connection mode toggle (fields vs URL) — bidirectional sync */}
            {config.connectionModes.length > 1 && (
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[12px] text-[var(--color-text-dim)]">connect via:</span>
                {config.connectionModes.map((mode) => (
                  <button
                    key={mode}
                    onClick={() => {
                      if (mode === form.connectionMode) return;
                      if (mode === "url") {
                        // Fields → URL: build connection string from current fields
                        const preview = buildConnectionPreview({ ...form, connectionMode: "fields" });
                        setForm({ ...form, connectionMode: "url", connection_string: preview.replace(":****@", `:${form.password || ""}@`) });
                      } else {
                        // URL → Fields: parse connection string into fields
                        const parsed = parseConnectionUrl(form.connection_string, form.db_type);
                        setForm({ ...form, connectionMode: "fields", ...parsed });
                      }
                    }}
                    className={`flex items-center gap-1.5 px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                      form.connectionMode === mode
                        ? "border-[var(--color-text)] text-[var(--color-text)]"
                        : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                    }`}
                  >
                    {mode === "url" ? <Link2 className="w-3 h-3" strokeWidth={1.5} /> : <Settings2 className="w-3 h-3" strokeWidth={1.5} />}
                    {mode === "url" ? "connection string" : "individual fields"}
                  </button>
                ))}
              </div>
            )}

            {/* DB-specific fields */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <ConnectionFieldsForm form={form} setForm={setForm} formErrors={formErrors} fieldRefs={fieldRefs} clearServerError={(key) => setServerFieldErrors((prev) => { if (!(key in prev)) return prev; const { [key]: _, ...rest } = prev; return rest; })} />
            </div>

            {/* Connection string preview with copy button */}
            {form.connectionMode !== "url" && (
              <div className="mb-4 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px]">
                <div className="flex items-center gap-2">
                  <Link2 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                  <span className="text-[11px] text-[var(--color-text-dim)]">connection preview</span>
                  <div className="flex-1" />
                  <button
                    type="button"
                    onClick={() => {
                      const fullUrl = buildConnectionPreview({ ...form, connectionMode: "fields" }).replace(":****@", `:${form.password || ""}@`);
                      navigator.clipboard.writeText(fullUrl).then(() => toast("Connection URL copied", "info"));
                    }}
                    className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
                  >
                    copy url
                  </button>
                </div>
                <code className="text-[12px] text-[var(--color-text-muted)] font-mono break-all">{buildConnectionPreview(form)}</code>
              </div>
            )}

            {/* Advanced: SSL + SSH + Access Controls + Schema Refresh */}
            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors mb-2"
              >
                {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                advanced options
                {(form.ssl_enabled || form.ssh_enabled || !form.read_only || form.schema_refresh_enabled || form.connection_timeout !== "15" || form.query_timeout !== "120") && (
                  <span className="text-[var(--color-success)] text-[11px] ml-1">
                    {[form.ssl_enabled && "ssl", form.ssh_enabled && "ssh", !form.read_only && "read-write", form.schema_refresh_enabled && "auto-refresh", (form.connection_timeout !== "15" || form.query_timeout !== "120") && "custom timeouts"].filter(Boolean).join(" + ")}
                  </span>
                )}
              </button>
                {showAdvanced && (
                  <div className="animate-fade-in">
                    <div className="flex gap-0 mb-4 border-b border-[var(--color-border)]">
                      {(["security", "performance", "schema"] as const).map((tab) => {
                        const tabIcons = { security: <Lock className="w-3 h-3" strokeWidth={1.5} />, performance: <Activity className="w-3 h-3" strokeWidth={1.5} />, schema: <Table2 className="w-3 h-3" strokeWidth={1.5} /> };
                        const tabBadges = {
                          security: form.ssl_enabled || form.ssh_enabled,
                          performance: form.connection_timeout !== "15" || form.query_timeout !== "120" || form.keepalive_interval !== "0",
                          schema: form.schema_refresh_enabled || form.schema_filter_include.trim() !== "" || form.schema_filter_exclude.trim() !== "",
                        };
                        return (
                          <button
                            key={tab}
                            type="button"
                            onClick={() => setAdvancedTab(tab)}
                            className={`flex items-center gap-1.5 px-3 py-2 text-[12px] border-b-2 transition-colors duration-150 ${
                              advancedTab === tab
                                ? "border-[var(--color-text)] text-[var(--color-text)]"
                                : "border-transparent text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)]"
                            }`}
                          >
                            {tabIcons[tab]}
                            {tab}
                            {tabBadges[tab] && <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />}
                          </button>
                        );
                      })}
                    </div>

                    {/* Security tab */}
                    {advancedTab === "security" && (
                      <div className="animate-fade-in">
                    <SSLSection form={form} setForm={setForm} formErrors={formErrors} fieldRefs={fieldRefs} />
                    <SSHSection form={form} setForm={setForm} serverIp={serverIp} formErrors={formErrors} fieldRefs={fieldRefs} clearServerError={(key) => setServerFieldErrors((prev) => { if (!(key in prev)) return prev; const { [key]: _, ...rest } = prev; return rest; })} />
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-3">
                        <Settings2 className="w-3 h-3" strokeWidth={1.5} />
                        <span>access controls</span>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">connection scope</label>
                          <select
                            value={form.scope}
                            onChange={(e) => setForm({ ...form, scope: e.target.value as "workspace" | "project" })}
                            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                          >
                            <option value="workspace">workspace — all projects</option>
                            <option value="project">project — current only</option>
                          </select>
                          <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">
                            workspace connections are shared across all projects
                          </p>
                        </div>
                        <div>
                          <label className="flex items-center gap-2 cursor-pointer mt-5">
                            <input
                              type="checkbox"
                              checked={form.read_only}
                              onChange={(e) => setForm({ ...form, read_only: e.target.checked })}
                              className="accent-[var(--color-text)]"
                            />
                            <span className="text-[12px] text-[var(--color-text-muted)]">
                              read-only mode
                            </span>
                          </label>
                          <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60 ml-5">
                            only SELECT queries allowed (recommended)
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* IP Allowlist Info */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-2">
                        <Shield className="w-3 h-3" strokeWidth={1.5} />
                        <span>ip allowlisting</span>
                      </div>
                      <div className="px-3 py-2.5 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px]">
                        <p className="text-[11px] text-[var(--color-text-dim)] mb-1.5">
                          if your database requires ip allowlisting, add this signalpilot server ip to your firewall rules:
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <code className="text-[12px] text-[var(--color-text)] bg-[var(--color-bg-hover)] px-2 py-0.5 font-mono">
                            {serverIp ? `${serverIp}/32` : "detecting..."}
                          </code>
                          {serverIp && (
                            <button
                              type="button"
                              onClick={() => { navigator.clipboard.writeText(serverIp); toast("IP copied to clipboard", "success"); }}
                              className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
                            >
                              <Copy className="w-3 h-3 inline" /> copy
                            </button>
                          )}
                        </div>
                        <p className="text-[10px] text-[var(--color-text-dim)] mt-1.5 opacity-60">
                          {serverIp ? "add this ip to your database firewall, security group, or network policy." : "fetching server ip..."}
                        </p>
                      </div>
                    </div>
                      </div>
                    )}

                    {/* Performance tab */}
                    {advancedTab === "performance" && (
                      <div className="animate-fade-in">
                        {/* Connection Timeouts */}
                        <div>
                          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-3">
                            <Clock className="w-3 h-3" strokeWidth={1.5} />
                            <span>timeouts & keepalive</span>
                          </div>
                          <div className="grid grid-cols-3 gap-4">
                            <div>
                              {(() => { const { id: ctId, inputRef: ctRef, error: ctError } = fieldProps("connection_timeout", formErrors, fieldRefs); return (
                              <>
                              <label htmlFor={ctId} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">connection timeout</label>
                              <div className="flex items-center gap-1.5">
                                <input type="number" min="1" max="300" id={ctId} ref={ctRef as Ref<HTMLInputElement>} aria-invalid={ctError ? "true" : undefined} aria-describedby={ctError ? `${ctId}-error` : undefined} value={form.connection_timeout} onChange={(e) => setForm({ ...form, connection_timeout: e.target.value })} className={`w-20 px-3 py-2 bg-[var(--color-bg-input)] border rounded-[10px] text-xs focus:outline-none font-mono tabular-nums${ctError ? " border-[var(--color-error)]/60 focus:border-[var(--color-error)]" : " border-[var(--color-border)] focus:border-[var(--color-text-dim)]"}`} />
                                <span className="text-[11px] text-[var(--color-text-dim)]">sec</span>
                              </div>
                              {ctError && <p id={`${ctId}-error`} role="alert" className="text-[11px] text-[var(--color-error)] mt-1">{ctError}</p>}
                              <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">max time to establish connection</p>
                              </>
                              ); })()}
                            </div>
                            <div>
                              {(() => { const { id: qtId, inputRef: qtRef, error: qtError } = fieldProps("query_timeout", formErrors, fieldRefs); return (
                              <>
                              <label htmlFor={qtId} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">query timeout</label>
                              <div className="flex items-center gap-1.5">
                                <input type="number" min="1" max="3600" id={qtId} ref={qtRef as Ref<HTMLInputElement>} aria-invalid={qtError ? "true" : undefined} aria-describedby={qtError ? `${qtId}-error` : undefined} value={form.query_timeout} onChange={(e) => setForm({ ...form, query_timeout: e.target.value })} className={`w-20 px-3 py-2 bg-[var(--color-bg-input)] border rounded-[10px] text-xs focus:outline-none font-mono tabular-nums${qtError ? " border-[var(--color-error)]/60 focus:border-[var(--color-error)]" : " border-[var(--color-border)] focus:border-[var(--color-text-dim)]"}`} />
                                <span className="text-[11px] text-[var(--color-text-dim)]">sec</span>
                              </div>
                              {qtError && <p id={`${qtId}-error`} role="alert" className="text-[11px] text-[var(--color-error)] mt-1">{qtError}</p>}
                              <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">max query execution time</p>
                              </>
                              ); })()}
                            </div>
                            <div>
                              <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">keepalive interval</label>
                              <div className="flex items-center gap-1.5">
                                <select value={form.keepalive_interval} onChange={(e) => setForm({ ...form, keepalive_interval: e.target.value })} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-2 py-2">
                                  <option value="0">disabled</option>
                                  <option value="30">30 sec</option>
                                  <option value="60">1 min</option>
                                  <option value="120">2 min</option>
                                  <option value="300">5 min</option>
                                </select>
                              </div>
                              <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">ping to prevent idle disconnect</p>
                            </div>
                          </div>
                          {/* Pool sizing — only for pool-capable connectors */}
                          {(form.db_type === "postgres") && (
                            <div className="grid grid-cols-2 gap-4 mt-3 pt-3 border-t border-[var(--color-border)]/50">
                              <div>
                                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">pool min size</label>
                                <div className="flex items-center gap-1.5">
                                  <input type="number" min="1" max="20" value={form.pool_min_size} onChange={(e) => setForm({ ...form, pool_min_size: e.target.value })} className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)] font-mono tabular-nums" />
                                  <span className="text-[11px] text-[var(--color-text-dim)]">conns</span>
                                </div>
                                <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">minimum idle connections</p>
                              </div>
                              <div>
                                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">pool max size</label>
                                <div className="flex items-center gap-1.5">
                                  <input type="number" min="1" max="50" value={form.pool_max_size} onChange={(e) => setForm({ ...form, pool_max_size: e.target.value })} className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)] font-mono tabular-nums" />
                                  <span className="text-[11px] text-[var(--color-text-dim)]">conns</span>
                                </div>
                                <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">max concurrent connections</p>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Schema tab */}
                    {advancedTab === "schema" && (
                      <div className="animate-fade-in">
                        {/* Schema Filtering */}
                        <div>
                          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-2">
                            <Filter className="w-3 h-3" strokeWidth={1.5} />
                            <span>schema filtering</span>
                          </div>
                          <div className="text-[10px] text-[var(--color-text-dim)] mb-3 opacity-60">
                            filter which schemas are visible to the ai agent. excludes staging, dev, and raw schemas to improve accuracy.
                          </div>
                          <div className="space-y-3">
                            <div>
                              <label className="block text-[11px] text-[var(--color-text-muted)] mb-1">
                                include schemas <span className="opacity-50">(comma-separated, empty = all)</span>
                              </label>
                              <input type="text" placeholder="public, analytics, production" value={form.schema_filter_include} onChange={(e) => setForm({ ...form, schema_filter_include: e.target.value })} className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-3 py-2 placeholder:text-[var(--color-text-dim)]" />
                            </div>
                            <div>
                              <label className="block text-[11px] text-[var(--color-text-muted)] mb-1">
                                exclude schemas <span className="opacity-50">(comma-separated, glob patterns supported)</span>
                              </label>
                              <input type="text" placeholder="staging*, dev*, raw, tmp*, _dbt_*" value={form.schema_filter_exclude} onChange={(e) => setForm({ ...form, schema_filter_exclude: e.target.value })} className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-3 py-2 placeholder:text-[var(--color-text-dim)]" />
                            </div>
                          </div>
                        </div>

                        {/* Scheduled Schema Refresh */}
                        <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-2">
                            <RefreshCw className="w-3 h-3" strokeWidth={1.5} />
                            <span>scheduled schema refresh</span>
                          </div>
                          <div className="flex items-center gap-3 mb-2">
                            <label className="flex items-center gap-2 cursor-pointer">
                              <input type="checkbox" checked={form.schema_refresh_enabled} onChange={(e) => setForm({ ...form, schema_refresh_enabled: e.target.checked })} className="accent-[var(--color-text)]" />
                              <span className="text-[12px] text-[var(--color-text-muted)]">auto-refresh schema metadata</span>
                            </label>
                          </div>
                          {form.schema_refresh_enabled && (
                            <div className="flex items-center gap-2 animate-fade-in">
                              <span className="text-[11px] text-[var(--color-text-dim)]">every</span>
                              <select value={form.schema_refresh_interval} onChange={(e) => setForm({ ...form, schema_refresh_interval: e.target.value })} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-2 py-1">
                                <option value="60">1 min</option>
                                <option value="300">5 min</option>
                                <option value="900">15 min</option>
                                <option value="1800">30 min</option>
                                <option value="3600">1 hour</option>
                                <option value="14400">4 hours</option>
                                <option value="43200">12 hours</option>
                                <option value="86400">24 hours</option>
                              </select>
                              <span className="text-[10px] text-[var(--color-text-dim)] opacity-60">keeps ai agent schema knowledge current</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

            {/* Pre-test result display */}
            {preTestResult && (
              <div className={`mt-4 p-3 border rounded-[10px] ${preTestResult.status === "healthy" ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5"}`}>
                <div className="flex items-center gap-2 mb-2">
                  {preTestResult.status === "healthy" ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-red-400" />
                  )}
                  <span className={`text-[12px] font-medium ${preTestResult.status === "healthy" ? "text-emerald-400" : "text-red-400"}`}>
                    {preTestResult.message}
                  </span>
                </div>
                {preTestResult.phases?.length > 0 && (
                  <div className="space-y-1 ml-5">
                    {preTestResult.phases.map((phase, i) => (
                      <div key={i} className="flex items-center gap-2 text-[11px]">
                        <span className={phase.status === "ok" ? "text-emerald-400" : phase.status === "error" ? "text-red-400" : "text-amber-400"}>
                          {phase.status === "ok" ? "pass" : phase.status === "error" ? "fail" : phase.status}
                        </span>
                        <span className="text-[var(--color-text-dim)]">{phase.phase}:</span>
                        <span className="text-[var(--color-text-muted)]">{phase.message}</span>
                        {phase.duration_ms !== undefined && (
                          <span className="text-[var(--color-text-dim)] opacity-50">{phase.duration_ms.toFixed(0)}ms</span>
                        )}
                      </div>
                    ))}
                    {preTestResult.phases.some(p => p.hint) && (
                      <div className="mt-1.5 pl-2 border-l border-amber-500/30">
                        {preTestResult.phases.filter(p => p.hint).map((p, i) => (
                          <div key={i} className="text-[11px] text-amber-400/80">
                            hint: {p.hint}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Show security warnings before the user saves the connection. */}
            {(() => {
              const warnings: string[] = [];
              const cfg = DB_CONFIGS[form.db_type];
              // Warn if SSL not enabled on a production-capable connector.
              // In URL mode, check the connection string for sslmode= param.
              const urlHasSsl = form.connectionMode === "url" && form.connection_string &&
                /[?&]sslmode=(require|verify-ca|verify-full|prefer|allow)/i.test(form.connection_string);
              if (cfg.supportsSSL && !form.ssl_enabled && !urlHasSsl && !["duckdb", "sqlite"].includes(form.db_type)) {
                warnings.push("SSL/TLS is not enabled. Recommended for production databases to encrypt traffic in transit.");
              }
              // Prefer key-pair authentication because Snowflake is phasing out password-only access.
              if (form.db_type === "snowflake" && form.snowflake_auth_method === "password") {
                warnings.push("Snowflake recommends key-pair authentication over password. Password auth may be blocked by Snowflake's mandatory MFA policy.");
              }
              // Warn about read-write mode
              if (!form.read_only) {
                warnings.push("Read-write mode enabled. This allows INSERT, UPDATE, DELETE, and DDL queries. Use read-only for analytics workloads.");
              }
              // Warn about missing schema filtering for large warehouses
              if (["snowflake", "bigquery", "redshift", "databricks"].includes(form.db_type) && !form.schema_filter_include.trim() && !form.schema_filter_exclude.trim()) {
                warnings.push("No schema filtering configured. For large warehouses, filtering schemas improves AI agent accuracy and reduces metadata overhead.");
              }
              if (warnings.length === 0) return null;
              return (
                <div className="mt-4 space-y-1.5">
                  {warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-2 px-3 py-2 border border-amber-500/20 bg-amber-500/5 rounded-[10px]">
                      <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0 mt-0.5" strokeWidth={1.5} />
                      <span className="text-[11px] text-amber-400/80">{w}</span>
                    </div>
                  ))}
                </div>
              );
            })()}

            {/* Action buttons */}
            <div className="flex items-center gap-3 mt-5 pt-4 border-t border-[var(--color-border)]">
              <button onClick={handleCreate} disabled={saving || preTesting || hasFormErrors} className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {editingConnection ? "update connection" : "save connection"}
              </button>
              <button onClick={handlePreTest} disabled={saving || preTesting || hasFormErrors} className="flex items-center gap-2 px-4 py-2 border border-emerald-500/30 rounded-[10px] text-xs text-emerald-400 hover:bg-emerald-500/10 hover:border-emerald-500/50 transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed">
                {preTesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <TestTube className="w-3.5 h-3.5" strokeWidth={1.5} />}
                test connection
              </button>
              <button onClick={handleSaveAndTest} disabled={saving || preTesting || hasFormErrors} className="flex items-center gap-2 px-4 py-2 border border-[var(--color-border)] rounded-[10px] text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed">
                {editingConnection ? "update & test" : "save & test"}
              </button>
              <button onClick={() => { setShowForm(false); setEditingConnection(null); setForm({ ...defaultForm }); setServerFieldErrors({}); setShowAdvanced(false); setPreTestResult(null); }} className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
                cancel
              </button>
              {editingConnection && (
                <span className="text-[11px] text-[var(--color-text-dim)] opacity-60 ml-auto">
                  leave password blank to keep existing credentials
                </span>
              )}
            </div>
          </div>
        </div>
      )}

    </>
  );
}
