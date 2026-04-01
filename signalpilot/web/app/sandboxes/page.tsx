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
} from "lucide-react";
import { getSandboxes, createSandbox, deleteSandbox, getConnections } from "@/lib/api";
import type { SandboxInfo, ConnectionInfo } from "@/lib/types";

const statusColors: Record<string, string> = {
  ready: "bg-blue-500",
  starting: "bg-yellow-500 animate-pulse",
  running: "bg-[var(--color-success)]",
  stopped: "bg-[var(--color-text-dim)]",
  error: "bg-[var(--color-error)]",
};

export default function SandboxesPage() {
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
    } catch (e) {
      alert(String(e));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    await deleteSandbox(id);
    setSandboxes((p) => p.filter((s) => s.id !== id));
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold mb-1">Sandboxes</h1>
          <p className="text-sm text-[var(--color-text-muted)]">
            Shuru microVM sandboxes for isolated code execution
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" /> New Sandbox
        </button>
      </div>

      {/* Create dialog */}
      {showCreate && (
        <div className="mb-6 p-5 bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl">
          <h3 className="text-sm font-medium mb-4">Create Sandbox</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">
                Label
              </label>
              <input
                type="text"
                placeholder="my-analysis"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">
                Connection (optional)
              </label>
              <select
                value={form.connection_name}
                onChange={(e) =>
                  setForm({ ...form, connection_name: e.target.value })
                }
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
              >
                <option value="">None</option>
                {connections.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} ({c.db_type})
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleCreate}
              disabled={creating}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors disabled:opacity-50"
            >
              {creating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              Create
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 rounded-lg text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Sandbox grid */}
      {sandboxes.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <Terminal className="w-12 h-12 text-[var(--color-text-dim)] mb-4" />
          <p className="text-sm text-[var(--color-text-muted)] mb-2">
            No sandboxes yet
          </p>
          <p className="text-xs text-[var(--color-text-dim)]">
            Create a sandbox to start executing code in an isolated Shuru
            microVM
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {sandboxes.map((sb) => (
            <Link
              key={sb.id}
              href={`/sandboxes/${sb.id}`}
              className="group block bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl p-5 hover:border-[var(--color-border-hover)] transition-colors"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div
                    className={`w-2 h-2 rounded-full ${statusColors[sb.status] || statusColors.error}`}
                  />
                  <span className="text-sm font-medium">
                    {sb.label || sb.id.slice(0, 8)}
                  </span>
                </div>
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    handleDelete(sb.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-[var(--color-error)]/10 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-all"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="space-y-2 text-xs text-[var(--color-text-muted)]">
                {sb.vm_id && (
                  <div className="flex items-center gap-2">
                    <Cpu className="w-3 h-3" />
                    <span>
                      VM: <code>{sb.vm_id}</code>
                    </span>
                  </div>
                )}
                {sb.connection_name && (
                  <div className="flex items-center gap-2">
                    <Terminal className="w-3 h-3" />
                    <span>{sb.connection_name}</span>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <Clock className="w-3 h-3" />
                  <span>
                    {new Date(sb.created_at * 1000).toLocaleTimeString()}
                  </span>
                </div>
                {sb.boot_ms != null && (
                  <span className="inline-block px-2 py-0.5 rounded bg-[var(--color-success)]/10 text-[var(--color-success)]">
                    Boot: {sb.boot_ms.toFixed(0)}ms
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
