"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Save,
  Server,
  Shield,
  Settings as SettingsIcon,
  CheckCircle2,
  XCircle,
  Loader2,
  Cpu,
  Key,
  Eye,
  EyeOff,
  Info,
  Plus,
  X,
  Ban,
} from "lucide-react";
import { getSettings, updateSettings, getHealth, setApiKey } from "@/lib/api";
import type { GatewaySettings } from "@/lib/types";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { CodeBlock } from "@/components/ui/code-block";

function SectionHeader({ icon: Icon, title, iconColor }: { icon: React.ElementType; title: string; iconColor?: string }) {
  return (
    <div className="section-header mb-4">
      <div className="flex items-center gap-2">
        <Icon className={`w-3.5 h-3.5 ${iconColor || "text-[var(--color-text-dim)]"}`} strokeWidth={1.5} />
        <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{title}</span>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { toast } = useToast();
  const [settings, setSettings] = useState<GatewaySettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testingHealth, setTestingHealth] = useState(false);
  const [healthResult, setHealthResult] = useState<Record<string, unknown> | null>(null);
  const [browserApiKey, setBrowserApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [showGatewayKey, setShowGatewayKey] = useState(false);
  const [browserKeySaved, setBrowserKeySaved] = useState(false);
  const [blockedTables, setBlockedTables] = useState<string[]>([]);
  const [newBlockedTable, setNewBlockedTable] = useState("");

  useEffect(() => {
    getSettings().then((s) => {
      setSettings(s);
      setBlockedTables(s.blocked_tables || []);
    }).catch(() => {});
    const stored = localStorage.getItem("sp_api_key") || "";
    setBrowserApiKey(stored);
  }, []);

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    try {
      await updateSettings({ ...settings, blocked_tables: blockedTables });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      toast("settings saved", "success");
    } catch (e) { toast(String(e), "error"); }
    finally { setSaving(false); }
  }

  function handleSaveBrowserKey() {
    setApiKey(browserApiKey || null);
    setBrowserKeySaved(true);
    setTimeout(() => setBrowserKeySaved(false), 3000);
    toast("api key saved to localStorage", "success");
  }

  async function handleTestConnection() {
    setTestingHealth(true);
    try {
      const data = await getHealth();
      setHealthResult(data);
    } catch (e) { setHealthResult({ error: String(e) }); }
    finally { setTestingHealth(false); }
  }

  // Keyboard shortcut: ctrl+s to save
  const handleSaveShortcut = useCallback((e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      if (settings && !saving) handleSave();
    }
  }, [settings, saving]);

  useEffect(() => {
    window.addEventListener("keydown", handleSaveShortcut);
    return () => window.removeEventListener("keydown", handleSaveShortcut);
  }, [handleSaveShortcut]);

  if (!settings) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="settings"
        subtitle="config"
        description="configure signalpilot instance, auth, and governance"
      />

      <TerminalBar
        path="settings --edit"
        status={<StatusDot status={settings ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">instance: <code className="text-[10px] text-[var(--color-text)]">{settings ? "loaded" : "—"}</code></span>
        </div>
      </TerminalBar>

      {/* Browser Authentication */}
      <section className="mb-8">
        <SectionHeader icon={Key} title="browser authentication" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          <div className="p-6 space-y-4">
            <div className="flex items-start gap-3 p-3 border border-[var(--color-border)] bg-[var(--color-bg)]">
              <Info className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
              <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
                if the gateway has an api key configured, enter it here. stored in localStorage, sent as Bearer token.
              </p>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">api key</label>
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={browserApiKey}
                    onChange={(e) => setBrowserApiKey(e.target.value)}
                    placeholder="enter gateway api key"
                    className="w-full px-3 py-2 pr-10 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                  />
                  <button onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
                    {showApiKey ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                  </button>
                </div>
                <button onClick={handleSaveBrowserKey}
                  className="flex items-center gap-1.5 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs tracking-wider uppercase transition-all hover:opacity-90">
                  <Key className="w-3 h-3" /> save
                </button>
              </div>
              {browserKeySaved && (
                <span className="flex items-center gap-1 mt-2 text-[10px] text-[var(--color-success)] tracking-wider animate-fade-in">
                  <CheckCircle2 className="w-3 h-3" /> saved
                </span>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* BYOF Firecracker Configuration */}
      <section className="mb-8">
        <SectionHeader icon={Server} title="firecracker sandbox (byof)" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          <div className="p-6 space-y-4">
            <p className="text-[10px] text-[var(--color-text-dim)] -mt-1 mb-2 tracking-wider">
              bring your own firecracker — point to any sandbox manager endpoint.
            </p>
            <div>
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">provider</label>
              <select value={settings.sandbox_provider}
                onChange={(e) => setSettings({ ...settings, sandbox_provider: e.target.value as "local" | "remote" })}
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]">
                <option value="local">local (same machine / docker)</option>
                <option value="remote">remote (byof hosted instance)</option>
              </select>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">sandbox manager url</label>
              <input type="text" value={settings.sandbox_manager_url}
                onChange={(e) => setSettings({ ...settings, sandbox_manager_url: e.target.value })}
                placeholder="http://localhost:8080"
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide" />
            </div>
            {settings.sandbox_provider === "remote" && (
              <div className="animate-fade-in">
                <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">sandbox api key</label>
                <input type="password" value={settings.sandbox_api_key || ""}
                  onChange={(e) => setSettings({ ...settings, sandbox_api_key: e.target.value || null })}
                  placeholder="bearer token for remote sandbox manager"
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]" />
              </div>
            )}
            <div>
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">max concurrent sandboxes</label>
              <input type="number" value={settings.max_concurrent_sandboxes}
                onChange={(e) => setSettings({ ...settings, max_concurrent_sandboxes: parseInt(e.target.value) || 10 })}
                className="w-32 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tabular-nums" />
            </div>
            <div className="pt-2">
              <button onClick={handleTestConnection} disabled={testingHealth}
                className="flex items-center gap-2 px-3 py-1.5 text-[10px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider">
                {testingHealth ? <Loader2 className="w-3 h-3 animate-spin" /> : <Cpu className="w-3 h-3" strokeWidth={1.5} />}
                test sandbox connection
              </button>
              {healthResult && (
                <div className="mt-3 animate-fade-in">
                  {"error" in healthResult ? (
                    <div className="p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5">
                      <span className="text-[10px] text-[var(--color-error)] flex items-center gap-1">
                        <XCircle className="w-3 h-3" />{String(healthResult.error)}
                      </span>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="flex items-center gap-1 text-[10px] text-[var(--color-success)] tracking-wider">
                        <CheckCircle2 className="w-3 h-3" /> connected
                      </div>
                      <CodeBlock
                        code={JSON.stringify(healthResult, null, 2)}
                        language="json"
                        maxHeight="12rem"
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Governance Defaults */}
      <section className="mb-8">
        <SectionHeader icon={Shield} title="governance defaults" iconColor="text-[var(--color-success)]" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          <div className="p-6">
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: "default row limit", key: "default_row_limit", desc: "max rows per query", type: "number" },
                { label: "default budget (usd)", key: "default_budget_usd", desc: "per-session spending limit", type: "number", step: "0.01" },
                { label: "default timeout (s)", key: "default_timeout_seconds", desc: "per-query hard timeout", type: "number" },
              ].map((field) => (
                <div key={field.key}>
                  <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">{field.label}</label>
                  <input
                    type={field.type}
                    step={field.step}
                    value={settings[field.key as keyof GatewaySettings] as number}
                    onChange={(e) => setSettings({ ...settings, [field.key]: field.step ? parseFloat(e.target.value) : parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tabular-nums"
                  />
                  <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider">{field.desc}</p>
                </div>
              ))}
            </div>

            {/* Blocked Tables */}
            <div className="mt-6 pt-6 border-t border-[var(--color-border)]">
              <div className="flex items-center gap-2 mb-3">
                <Ban className="w-3 h-3 text-[var(--color-error)]" strokeWidth={1.5} />
                <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">blocked tables</span>
              </div>
              <p className="text-[9px] text-[var(--color-text-dim)] mb-3 tracking-wider leading-relaxed">
                tables here are rejected at policy check. queries referencing them get a governance error.
              </p>

              <div className="flex items-center gap-2 mb-3">
                <input
                  type="text"
                  value={newBlockedTable}
                  onChange={(e) => setNewBlockedTable(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newBlockedTable.trim()) {
                      e.preventDefault();
                      const table = newBlockedTable.trim().toLowerCase();
                      if (!blockedTables.includes(table)) setBlockedTables([...blockedTables, table]);
                      setNewBlockedTable("");
                    }
                  }}
                  placeholder="e.g. users_private, financial_records"
                  className="flex-1 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
                <button
                  onClick={() => {
                    const table = newBlockedTable.trim().toLowerCase();
                    if (table && !blockedTables.includes(table)) setBlockedTables([...blockedTables, table]);
                    setNewBlockedTable("");
                  }}
                  disabled={!newBlockedTable.trim()}
                  className="flex items-center gap-1 px-3 py-2 text-[10px] text-[var(--color-error)] border border-[var(--color-error)]/20 hover:bg-[var(--color-error)]/5 transition-colors disabled:opacity-30 tracking-wider uppercase"
                >
                  <Plus className="w-3 h-3" /> block
                </button>
              </div>

              {blockedTables.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {blockedTables.map((table) => (
                    <span key={table} className="flex items-center gap-1.5 px-2 py-1 border border-[var(--color-error)]/20 text-[10px] tracking-wider group hover:border-[var(--color-error)]/40 transition-colors">
                      <Ban className="w-2.5 h-2.5 text-[var(--color-error)]" />
                      <code className="text-[var(--color-text-muted)]">{table}</code>
                      <button onClick={() => setBlockedTables(blockedTables.filter((t) => t !== table))}
                        className="ml-0.5 p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-colors">
                        <X className="w-2.5 h-2.5" />
                      </button>
                    </span>
                  ))}
                </div>
              )}

              {blockedTables.length === 0 && (
                <p className="text-[9px] text-[var(--color-text-dim)] italic tracking-wider">
                  no tables blocked.
                </p>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Gateway Config */}
      <section className="mb-8">
        <SectionHeader icon={SettingsIcon} title="gateway" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          <div className="p-6 space-y-4">
            <div>
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">gateway url</label>
              <input type="text" value={settings.gateway_url}
                onChange={(e) => setSettings({ ...settings, gateway_url: e.target.value })}
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide" />
              <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider">url sandbox vms use to call back to the gateway</p>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">gateway api key</label>
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <input
                    type={showGatewayKey ? "text" : "password"}
                    value={settings.api_key || ""}
                    onChange={(e) => setSettings({ ...settings, api_key: e.target.value || null })}
                    placeholder="protect gateway with api key"
                    className="w-full px-3 py-2 pr-10 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                  />
                  <button onClick={() => setShowGatewayKey(!showGatewayKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
                    {showGatewayKey ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                  </button>
                </div>
                <button
                  onClick={() => {
                    const key = "sp_" + Array.from(crypto.getRandomValues(new Uint8Array(24)))
                      .map((b) => b.toString(16).padStart(2, "0")).join("");
                    setSettings({ ...settings, api_key: key });
                    setShowGatewayKey(true);
                  }}
                  className="px-3 py-2 text-[10px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all whitespace-nowrap tracking-wider"
                >
                  generate
                </button>
              </div>
              <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider">when set, all api requests require this key</p>
            </div>
          </div>
        </div>
      </section>

      {/* MCP Integration */}
      <section className="mb-8">
        <SectionHeader icon={Cpu} title="mcp integration" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          <div className="p-6 space-y-5">
            <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
              connect claude code or any mcp client to signalpilot:
            </p>

            {/* Step-by-step setup */}
            <div className="space-y-3">
              {[
                { step: "01", label: "install", code: "pip install signalpilot" },
                { step: "02", label: "register", code: "claude mcp add signalpilot -- python -m gateway.mcp_server" },
                { step: "03", label: "verify", code: "claude mcp list | grep signalpilot" },
              ].map((s) => (
                <div key={s.step} className="flex items-start gap-3">
                  <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums tracking-wider mt-2.5 w-5">{s.step}</span>
                  <div className="flex-1">
                    <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{s.label}</span>
                    <CodeBlock
                      code={s.code}
                      language="bash"
                      showLineNumbers={false}
                      maxHeight="3rem"
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Available tools */}
            <div className="pt-3 border-t border-[var(--color-border)]">
              <div className="flex items-center gap-2 mb-3">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <rect x="1" y="1" width="10" height="10" stroke="var(--color-success)" strokeWidth="1" fill="none" opacity="0.4" />
                  <path d="M4 6L5.5 7.5L8 4.5" stroke="var(--color-success)" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">available tools</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { name: "query_database", desc: "governed sql queries" },
                  { name: "execute_code", desc: "sandbox code execution" },
                  { name: "describe_table", desc: "schema introspection" },
                  { name: "check_budget", desc: "spending limit status" },
                ].map(tool => (
                  <div key={tool.name} className="flex items-center gap-2.5 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-colors group">
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="flex-shrink-0">
                      <rect width="10" height="10" fill="var(--color-success)" opacity="0.15" />
                      <rect x="2.5" y="2.5" width="5" height="5" fill="var(--color-success)" />
                    </svg>
                    <div className="min-w-0">
                      <code className="text-[10px] text-[var(--color-text-muted)] tracking-wider block">{tool.name}</code>
                      <span className="text-[8px] text-[var(--color-text-dim)] tracking-wider">{tool.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button onClick={handleSave} disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30">
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          save gateway settings
          <kbd className="ml-2 px-1.5 py-0.5 bg-[var(--color-bg)]/20 text-[8px] opacity-60 border border-[var(--color-bg)]/30">
            ctrl+S
          </kbd>
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-[10px] text-[var(--color-success)] tracking-wider animate-fade-in">
            <CheckCircle2 className="w-3 h-3" /> saved
          </span>
        )}
      </div>
    </div>
  );
}
