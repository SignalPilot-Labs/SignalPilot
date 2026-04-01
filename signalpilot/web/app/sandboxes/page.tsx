"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Plus,
  Terminal,
  Trash2,
  Play,
  Loader2,
  Clock,
  Cpu,
  DollarSign,
  Shield,
  Database,
  ArrowRight,
} from "lucide-react";
import { getSandboxes, createSandbox, deleteSandbox, getConnections } from "@/lib/api";
import type { SandboxInfo, ConnectionInfo } from "@/lib/types";
import { EmptySandbox, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot, MiniBar } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { TimeAgo } from "@/components/ui/time-ago";

const statusConfig: Record<string, { indicator: string; label: string }> = {
  ready: { indicator: "bg-blue-400", label: "ready" },
  starting: { indicator: "bg-[var(--color-warning)] pulse-dot", label: "starting" },
  running: { indicator: "bg-[var(--color-success)]", label: "running" },
  stopped: { indicator: "bg-[var(--color-text-dim)]", label: "stopped" },
  error: { indicator: "bg-[var(--color-error)]", label: "error" },
};

export default function SandboxesPage() {
  const { toast } = useToast();
  const [sandboxes, setSandboxes] = useState<SandboxInfo[]>([]);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [creating, setCreating] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ label: "", connection_name: "" });

  const refresh = useCallback(() => {
    getSandboxes().then(setSandboxes).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    getConnections().then(setConnections).catch(() => {});
    const i = setInterval(refresh, 5000);
    return () => clearInterval(i);
  }, [refresh]);

  async function handleCreate() {
    setCreating(true);
    try {
      const sb = await createSandbox({
        label: form.label || `sandbox-${Date.now().toString(36)}`,
        connection_name: form.connection_name || undefined,
      });
      setSandboxes((p) => [sb, ...p]);
      setShowCreate(false);
      setForm({ label: "", connection_name: "" });
    } catch (e) { toast(String(e), "error"); }
    finally { setCreating(false); }
  }

  async function handleDelete(id: string) {
    await deleteSandbox(id);
    setSandboxes((p) => p.filter((s) => s.id !== id));
  }

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="sandboxes"
        subtitle="microvms"
        description="firecracker microvms for isolated code execution"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Plus className="w-3.5 h-3.5" /> new sandbox
          </button>
        }
      />

      <TerminalBar
        path="sandboxes --list --watch"
        status={<StatusDot status={sandboxes.some(s => s.status === "running") ? "healthy" : sandboxes.length > 0 ? "warning" : "unknown"} size={4} pulse={sandboxes.some(s => s.status === "running")} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">total: <code className="text-[10px] text-[var(--color-text)]">{sandboxes.length}</code></span>
          <span className="text-[var(--color-text-dim)]">running: <code className="text-[10px] text-[var(--color-success)]">{sandboxes.filter(s => s.status === "running").length}</code></span>
        </div>
      </TerminalBar>

      {/* Create dialog */}
      {showCreate && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <Terminal className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">create sandbox</span>
          </div>
          <div className="p-5">
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">label</label>
                <input
                  type="text"
                  placeholder="my-analysis"
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
              </div>
              <div>
                <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection (optional)</label>
                <select
                  value={form.connection_name}
                  onChange={(e) => setForm({ ...form, connection_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                >
                  <option value="">none</option>
                  {connections.map((c) => (
                    <option key={c.name} value={c.name}>{c.name} ({c.db_type})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleCreate}
                disabled={creating}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
              >
                {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                create
              </button>
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sandbox grid */}
      {sandboxes.length === 0 ? (
        <EmptyState
          icon={EmptySandbox}
          title="no sandboxes"
          description="create a sandbox to execute code in an isolated firecracker microvm"
          action={
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider"
            >
              <Plus className="w-3.5 h-3.5" /> create first sandbox
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-3 gap-px bg-[var(--color-border)] stagger-fade-in">
          {sandboxes.map((sb) => {
            const status = statusConfig[sb.status] || statusConfig.error;
            const budgetPct = sb.budget_usd > 0 ? (sb.budget_used / sb.budget_usd) * 100 : 0;

            return (
              <Link
                key={sb.id}
                href={`/sandboxes/${sb.id}`}
                className="group block bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-accent-top"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <StatusDot
                      status={sb.status === "running" ? "healthy" : sb.status === "error" ? "error" : sb.status === "ready" ? "idle" : "warning"}
                      size={4}
                      pulse={sb.status === "running"}
                    />
                    <span className="text-xs text-[var(--color-text)] group-hover:text-white transition-colors">
                      {sb.label || sb.id.slice(0, 8)}
                    </span>
                    <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">{status.label}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <ArrowRight className="w-3 h-3 text-[var(--color-text-dim)] opacity-0 group-hover:opacity-100 transition-opacity" />
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        handleDelete(sb.id);
                      }}
                      className="opacity-0 group-hover:opacity-100 p-1 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-all"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                <div className="space-y-2 text-[10px] text-[var(--color-text-dim)] tracking-wider">
                  {sb.connection_name && (
                    <div className="flex items-center gap-2">
                      <Database className="w-3 h-3" strokeWidth={1.5} />
                      <span>{sb.connection_name}</span>
                    </div>
                  )}
                  {sb.vm_id && (
                    <div className="flex items-center gap-2">
                      <Cpu className="w-3 h-3" strokeWidth={1.5} />
                      <code className="text-[9px]">{sb.vm_id}</code>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <Clock className="w-3 h-3" strokeWidth={1.5} />
                    <TimeAgo timestamp={sb.created_at} live className="tabular-nums" />
                    {sb.uptime_sec != null && sb.uptime_sec > 0 && (
                      <span className="text-[var(--color-text-dim)]">
                        ({sb.uptime_sec < 60 ? `${sb.uptime_sec.toFixed(0)}s` : `${(sb.uptime_sec / 60).toFixed(0)}m`})
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 pt-1">
                    <span className="flex items-center gap-1 tabular-nums">
                      <DollarSign className="w-3 h-3" strokeWidth={1.5} />
                      ${sb.budget_used.toFixed(4)} / ${sb.budget_usd.toFixed(2)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Shield className="w-3 h-3 text-[var(--color-success)]" strokeWidth={1.5} />
                      {sb.row_limit.toLocaleString()}
                    </span>
                  </div>
                  {/* Budget bar */}
                  {sb.budget_usd > 0 && (
                    <div className="mt-1">
                      <MiniBar
                        value={budgetPct}
                        max={100}
                        height={3}
                        color={budgetPct > 80 ? "var(--color-error)" : budgetPct > 50 ? "var(--color-warning)" : "var(--color-success)"}
                      />
                    </div>
                  )}
                  {sb.boot_ms != null && (
                    <span className="inline-block px-1.5 py-0.5 border badge-success text-[9px] tracking-wider">
                      boot: {sb.boot_ms.toFixed(0)}ms
                    </span>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
