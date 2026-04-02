"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Plus,
  Trash2,
  Loader2,
  Play,
  Square,
  Copy,
  Check,
  ExternalLink,
  Globe,
} from "lucide-react";
import {
  getTunnels,
  createTunnel,
  deleteTunnel,
  stopTunnel,
  startTunnel,
} from "@/lib/api";
import type { TunnelInfo } from "@/lib/types";
import { EmptyTerminal, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

const PORT_PRESETS = [
  { port: 3200, label: "Web UI" },
  { port: 3300, label: "Gateway API" },
  { port: 3400, label: "Monitor" },
  { port: 3401, label: "Monitor API" },
];

function formatUptime(startedAt: number | null): string {
  if (!startedAt) return "--";
  const sec = Math.floor((Date.now() / 1000) - startedAt);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}

export default function TunnelsPage() {
  const { toast } = useToast();
  const [tunnels, setTunnels] = useState<TunnelInfo[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [stopping, setStopping] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TunnelInfo | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [form, setForm] = useState({ port: "3200", label: "", customPort: "" });

  const refresh = useCallback(() => {
    getTunnels().then(setTunnels).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const i = setInterval(refresh, 5000);
    return () => clearInterval(i);
  }, [refresh]);

  const selectedPort = form.port === "custom" ? parseInt(form.customPort) || 0 : parseInt(form.port);

  async function handleCreate() {
    if (!selectedPort || selectedPort < 1 || selectedPort > 65535) {
      toast("invalid port number", "error");
      return;
    }
    setCreating(true);
    try {
      const t = await createTunnel({ local_port: selectedPort, label: form.label || undefined });
      if (t.status === "error") {
        toast(t.error_message || "tunnel failed to start", "error");
      } else {
        toast("tunnel created", "success");
      }
      setShowForm(false);
      setForm({ port: "3200", label: "", customPort: "" });
      refresh();
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setCreating(false);
    }
  }

  async function handleStop(id: string) {
    setStopping(id);
    try {
      await stopTunnel(id);
      toast("tunnel stopped", "info");
      refresh();
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setStopping(null);
    }
  }

  async function handleStart(id: string) {
    setStarting(id);
    try {
      const t = await startTunnel(id);
      if (t.status === "error") {
        toast(t.error_message || "tunnel failed to start", "error");
      } else {
        toast("tunnel started", "success");
      }
      refresh();
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setStarting(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await deleteTunnel(deleteTarget.id);
      toast("tunnel deleted", "info");
      refresh();
    } catch (e) {
      toast(String(e), "error");
    }
    setDeleteTarget(null);
  }

  function copyUrl(url: string) {
    navigator.clipboard.writeText(url);
    setCopied(url);
    setTimeout(() => setCopied(null), 2000);
  }

  const running = tunnels.filter((t) => t.status === "running").length;

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="tunnels"
        subtitle="networking"
        description="expose local services to the internet via cloudflare quick tunnels"
        actions={
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Plus className="w-3.5 h-3.5" /> new tunnel
          </button>
        }
      />

      <TerminalBar
        path="tunnels --list"
        status={<StatusDot status={running > 0 ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            total: <code className="text-[10px] text-[var(--color-text)]">{tunnels.length}</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            active: <code className="text-[10px] text-[var(--color-success)]">{running}</code>
          </span>
        </div>
      </TerminalBar>

      {/* Create form */}
      {showForm && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-6 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <Globe className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">new tunnel</span>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-3 gap-4 mb-5">
              <div>
                <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">service</label>
                <select
                  value={form.port}
                  onChange={(e) => setForm({ ...form, port: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                >
                  {PORT_PRESETS.map((p) => (
                    <option key={p.port} value={String(p.port)}>
                      {p.label} (:{p.port})
                    </option>
                  ))}
                  <option value="custom">Custom port</option>
                </select>
              </div>
              {form.port === "custom" && (
                <div>
                  <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">port</label>
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    placeholder="8080"
                    value={form.customPort}
                    onChange={(e) => setForm({ ...form, customPort: e.target.value })}
                    className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                  />
                </div>
              )}
              <div>
                <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">label (optional)</label>
                <input
                  type="text"
                  placeholder="my-tunnel"
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleCreate}
                disabled={creating || !selectedPort}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
              >
                {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                create + start
              </button>
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tunnel list */}
      {tunnels.length === 0 && !showForm ? (
        <EmptyState
          icon={EmptyTerminal}
          title="no tunnels configured"
          description="create a tunnel to expose a local service to the internet via cloudflare"
          action={
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider"
            >
              <Plus className="w-3.5 h-3.5" /> create first tunnel
            </button>
          }
        />
      ) : (
        <div className="space-y-2">
          {tunnels.map((tunnel) => (
            <div
              key={tunnel.id}
              className="bg-[var(--color-bg-card)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all card-accent-top"
            >
              <div className="flex items-center gap-4 p-4">
                {/* Status */}
                <div className="flex-shrink-0">
                  <StatusDot
                    status={
                      tunnel.status === "running" ? "healthy" :
                      tunnel.status === "starting" ? "warning" :
                      tunnel.status === "error" ? "error" : "unknown"
                    }
                    size={5}
                    pulse={tunnel.status === "running"}
                  />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-[var(--color-text)]">{tunnel.label}</span>
                    <span className="text-[9px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
                      cf
                    </span>
                    <span className={`text-[10px] tracking-wider ${
                      tunnel.status === "running" ? "text-[var(--color-success)]" :
                      tunnel.status === "error" ? "text-[var(--color-error)]" :
                      tunnel.status === "starting" ? "text-[var(--color-warning)]" :
                      "text-[var(--color-text-dim)]"
                    }`}>
                      {tunnel.status}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider tabular-nums">
                      localhost:{tunnel.local_port}
                    </span>
                    {tunnel.public_url && (
                      <>
                        <span className="text-[10px] text-[var(--color-text-dim)]">&rarr;</span>
                        <button
                          onClick={() => copyUrl(tunnel.public_url!)}
                          className="flex items-center gap-1.5 text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors tracking-wider group"
                        >
                          <span className="truncate max-w-[300px]">{tunnel.public_url}</span>
                          {copied === tunnel.public_url ? (
                            <Check className="w-3 h-3 text-[var(--color-success)] flex-shrink-0" />
                          ) : (
                            <Copy className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
                          )}
                        </button>
                        <a
                          href={tunnel.public_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
                        >
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      </>
                    )}
                  </div>

                  {tunnel.error_message && (
                    <p className="text-[10px] text-[var(--color-error)] mt-1 tracking-wider truncate max-w-lg">
                      {tunnel.error_message}
                    </p>
                  )}

                  {tunnel.status === "running" && tunnel.started_at && (
                    <span className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider inline-block">
                      uptime: {formatUptime(tunnel.started_at)}
                    </span>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1">
                  {tunnel.status === "running" ? (
                    <button
                      onClick={() => handleStop(tunnel.id)}
                      disabled={stopping === tunnel.id}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-warning)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider"
                    >
                      {stopping === tunnel.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Square className="w-3 h-3" strokeWidth={1.5} />
                      )}
                      stop
                    </button>
                  ) : (
                    <button
                      onClick={() => handleStart(tunnel.id)}
                      disabled={starting === tunnel.id || tunnel.status === "starting"}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-success)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider"
                    >
                      {starting === tunnel.id || tunnel.status === "starting" ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Play className="w-3 h-3" strokeWidth={1.5} />
                      )}
                      start
                    </button>
                  )}
                  <button
                    onClick={() => setDeleteTarget(tunnel)}
                    className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] hover:bg-[var(--color-error)]/5 transition-all"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="delete tunnel"
        message={`Stop and remove tunnel "${deleteTarget?.label}" (port ${deleteTarget?.local_port})? The public URL will become inaccessible.`}
        confirmLabel="delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
