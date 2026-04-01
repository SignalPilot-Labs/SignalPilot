"use client";

import { useEffect, useState } from "react";
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
  Copy,
} from "lucide-react";
import { getSettings, updateSettings, getHealth, setApiKey } from "@/lib/api";
import type { GatewaySettings } from "@/lib/types";

export default function SettingsPage() {
  const [settings, setSettings] = useState<GatewaySettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testingHealth, setTestingHealth] = useState(false);
  const [healthResult, setHealthResult] = useState<Record<string, unknown> | null>(null);
  const [browserApiKey, setBrowserApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [showGatewayKey, setShowGatewayKey] = useState(false);
  const [browserKeySaved, setBrowserKeySaved] = useState(false);

  useEffect(() => {
    getSettings().then(setSettings).catch(() => {});
    // Load browser-side API key from localStorage
    const stored = localStorage.getItem("sp_api_key") || "";
    setBrowserApiKey(stored);
  }, []);

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    try {
      await updateSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  function handleSaveBrowserKey() {
    setApiKey(browserApiKey || null);
    setBrowserKeySaved(true);
    setTimeout(() => setBrowserKeySaved(false), 3000);
  }

  async function handleTestConnection() {
    setTestingHealth(true);
    try {
      const data = await getHealth();
      setHealthResult(data);
    } catch (e) {
      setHealthResult({ error: String(e) });
    } finally {
      setTestingHealth(false);
    }
  }

  if (!settings) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--color-text-muted)]" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold mb-1">Settings</h1>
        <p className="text-sm text-[var(--color-text-muted)]">
          Configure your SignalPilot instance, authentication, and governance defaults
        </p>
      </div>

      {/* Browser Authentication */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <Key className="w-4 h-4 text-[var(--color-accent)]" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            Browser Authentication
          </h2>
        </div>
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl p-6 space-y-4">
          <div className="flex items-start gap-3 p-3 rounded-lg bg-[var(--color-accent)]/5 border border-[var(--color-accent)]/20">
            <Info className="w-4 h-4 text-[var(--color-accent)] mt-0.5 flex-shrink-0" />
            <p className="text-xs text-[var(--color-text-muted)]">
              If the gateway has an API key configured, enter it here so this browser
              can authenticate. The key is stored in localStorage and sent as a Bearer
              token with every request.
            </p>
          </div>
          <div>
            <label className="block text-xs text-[var(--color-text-muted)] mb-1">
              API Key for this browser
            </label>
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <input
                  type={showApiKey ? "text" : "password"}
                  value={browserApiKey}
                  onChange={(e) => setBrowserApiKey(e.target.value)}
                  placeholder="Enter your gateway API key"
                  className="w-full px-3 py-2 pr-10 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
                />
                <button
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                >
                  {showApiKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
              <button
                onClick={handleSaveBrowserKey}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors"
              >
                <Key className="w-3.5 h-3.5" />
                Save
              </button>
            </div>
            {browserKeySaved && (
              <span className="flex items-center gap-1 mt-2 text-xs text-[var(--color-success)]">
                <CheckCircle2 className="w-3.5 h-3.5" /> Browser key saved
              </span>
            )}
          </div>
        </div>
      </section>

      {/* BYOF Firecracker Configuration */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <Server className="w-4 h-4 text-[var(--color-accent)]" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            Firecracker Sandbox (BYOF)
          </h2>
        </div>
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl p-6 space-y-4">
          <p className="text-xs text-[var(--color-text-muted)] -mt-1 mb-2">
            Bring Your Own Firecracker — point to any sandbox manager endpoint,
            local or remote.
          </p>
          <div>
            <label className="block text-xs text-[var(--color-text-muted)] mb-1">
              Provider
            </label>
            <select
              value={settings.sandbox_provider}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  sandbox_provider: e.target.value as "local" | "remote",
                })
              }
              className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
            >
              <option value="local">Local (same machine / Docker)</option>
              <option value="remote">Remote (BYOF hosted instance)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-[var(--color-text-muted)] mb-1">
              Sandbox Manager URL
            </label>
            <input
              type="text"
              value={settings.sandbox_manager_url}
              onChange={(e) =>
                setSettings({ ...settings, sandbox_manager_url: e.target.value })
              }
              placeholder="http://localhost:8080"
              className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm font-mono focus:outline-none focus:border-[var(--color-accent)]"
            />
          </div>
          {settings.sandbox_provider === "remote" && (
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">
                Sandbox API Key
              </label>
              <input
                type="password"
                value={settings.sandbox_api_key || ""}
                onChange={(e) =>
                  setSettings({ ...settings, sandbox_api_key: e.target.value || null })
                }
                placeholder="Bearer token for remote sandbox manager"
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
              />
            </div>
          )}
          <div>
            <label className="block text-xs text-[var(--color-text-muted)] mb-1">
              Max Concurrent Sandboxes
            </label>
            <input
              type="number"
              value={settings.max_concurrent_sandboxes}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  max_concurrent_sandboxes: parseInt(e.target.value) || 10,
                })
              }
              className="w-32 px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
            />
          </div>
          <div className="pt-2">
            <button
              onClick={handleTestConnection}
              disabled={testingHealth}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-colors"
            >
              {testingHealth ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Cpu className="w-3.5 h-3.5" />
              )}
              Test Sandbox Connection
            </button>
            {healthResult && (
              <div className="mt-3 p-3 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-xs font-mono">
                {"error" in healthResult ? (
                  <span className="text-[var(--color-error)]">
                    <XCircle className="w-3.5 h-3.5 inline mr-1" />
                    {String(healthResult.error)}
                  </span>
                ) : (
                  <div className="space-y-1">
                    <div className="flex items-center gap-1 text-[var(--color-success)]">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Connected
                    </div>
                    <pre className="text-[var(--color-text-muted)] whitespace-pre-wrap">
                      {JSON.stringify(healthResult, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Governance Defaults */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <Shield className="w-4 h-4 text-[var(--color-success)]" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            Governance Defaults
          </h2>
        </div>
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl p-6">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">
                Default Row Limit
              </label>
              <input
                type="number"
                value={settings.default_row_limit}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    default_row_limit: parseInt(e.target.value) || 10000,
                  })
                }
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
              />
              <p className="text-xs text-[var(--color-text-dim)] mt-1">
                Max rows returned per query
              </p>
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">
                Default Budget (USD)
              </label>
              <input
                type="number"
                step="0.01"
                value={settings.default_budget_usd}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    default_budget_usd: parseFloat(e.target.value) || 10,
                  })
                }
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
              />
              <p className="text-xs text-[var(--color-text-dim)] mt-1">
                Per-session spending limit
              </p>
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">
                Default Timeout (seconds)
              </label>
              <input
                type="number"
                value={settings.default_timeout_seconds}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    default_timeout_seconds: parseInt(e.target.value) || 30,
                  })
                }
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
              />
              <p className="text-xs text-[var(--color-text-dim)] mt-1">
                Per-query hard timeout
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Gateway Config */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <SettingsIcon className="w-4 h-4 text-[var(--color-warning)]" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            Gateway
          </h2>
        </div>
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl p-6 space-y-4">
          <div>
            <label className="block text-xs text-[var(--color-text-muted)] mb-1">
              Gateway URL
            </label>
            <input
              type="text"
              value={settings.gateway_url}
              onChange={(e) =>
                setSettings({ ...settings, gateway_url: e.target.value })
              }
              className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm font-mono focus:outline-none focus:border-[var(--color-accent)]"
            />
            <p className="text-xs text-[var(--color-text-dim)] mt-1">
              The URL sandbox VMs use to call back to the gateway
            </p>
          </div>
          <div>
            <label className="block text-xs text-[var(--color-text-muted)] mb-1">
              Gateway API Key
            </label>
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <input
                  type={showGatewayKey ? "text" : "password"}
                  value={settings.api_key || ""}
                  onChange={(e) =>
                    setSettings({ ...settings, api_key: e.target.value || null })
                  }
                  placeholder="Protect gateway API with a key"
                  className="w-full px-3 py-2 pr-10 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
                />
                <button
                  onClick={() => setShowGatewayKey(!showGatewayKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                >
                  {showGatewayKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
              <button
                onClick={() => {
                  const key = "sp_" + Array.from(crypto.getRandomValues(new Uint8Array(24)))
                    .map((b) => b.toString(16).padStart(2, "0"))
                    .join("");
                  setSettings({ ...settings, api_key: key });
                  setShowGatewayKey(true);
                }}
                className="px-3 py-2 rounded-lg text-xs text-[var(--color-text-muted)] border border-[var(--color-border)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition-colors whitespace-nowrap"
              >
                Generate
              </button>
            </div>
            <p className="text-xs text-[var(--color-text-dim)] mt-1">
              When set, all API requests require this key in the Authorization header
            </p>
          </div>
        </div>
      </section>

      {/* MCP Integration */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <Cpu className="w-4 h-4 text-purple-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            MCP Integration
          </h2>
        </div>
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl p-6 space-y-4">
          <p className="text-xs text-[var(--color-text-muted)]">
            Connect Claude Code or any MCP client to SignalPilot with this command:
          </p>
          <div className="relative">
            <pre className="px-4 py-3 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-xs font-mono text-[var(--color-text-muted)] overflow-x-auto">
              claude mcp add signalpilot -- python -m gateway.mcp_server
            </pre>
            <button
              onClick={() => {
                navigator.clipboard.writeText(
                  "claude mcp add signalpilot -- python -m gateway.mcp_server"
                );
              }}
              className="absolute top-2 right-2 p-1.5 rounded-md text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
              title="Copy to clipboard"
            >
              <Copy className="w-3.5 h-3.5" />
            </button>
          </div>
          <p className="text-[10px] text-[var(--color-text-dim)]">
            This exposes governed tools: query_database, execute_code, describe_table, check_budget, and more.
          </p>
        </div>
      </section>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          Save Gateway Settings
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-sm text-[var(--color-success)]">
            <CheckCircle2 className="w-4 h-4" /> Saved
          </span>
        )}
      </div>
    </div>
  );
}
