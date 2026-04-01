"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Play,
  Loader2,
  Trash2,
  Clock,
  Cpu,
  Database,
} from "lucide-react";
import { getSandbox, executeSandbox, deleteSandbox } from "@/lib/api";
import type { SandboxInfo } from "@/lib/types";

interface HistoryEntry {
  type: "input" | "output" | "error" | "system";
  text: string;
  timestamp: number;
  execution_ms?: number;
}

export default function SandboxDetailPage() {
  const params = useParams();
  const router = useRouter();
  const sandboxId = params.id as string;

  const [sandbox, setSandbox] = useState<SandboxInfo | null>(null);
  const [code, setCode] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getSandbox(sandboxId)
      .then((sb) => {
        setSandbox(sb);
        setHistory([
          {
            type: "system",
            text: `Sandbox ${sb.label || sb.id.slice(0, 8)} ready. ${
              sb.connection_name
                ? `Connected to: ${sb.connection_name}`
                : "No database connection."
            }`,
            timestamp: Date.now(),
          },
        ]);
      })
      .catch((e) => setError(String(e)));
  }, [sandboxId]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [history]);

  const handleExecute = useCallback(async () => {
    if (!code.trim() || running) return;

    const input = code.trim();
    setCode("");
    setRunning(true);

    setHistory((h) => [
      ...h,
      { type: "input", text: input, timestamp: Date.now() },
    ]);

    try {
      const result = await executeSandbox(sandboxId, input, 30);
      if (result.success) {
        setHistory((h) => [
          ...h,
          {
            type: "output",
            text: result.output || "(no output)",
            timestamp: Date.now(),
            execution_ms: result.execution_ms ?? undefined,
          },
        ]);
      } else {
        setHistory((h) => [
          ...h,
          {
            type: "error",
            text: result.error || "Execution failed",
            timestamp: Date.now(),
            execution_ms: result.execution_ms ?? undefined,
          },
        ]);
      }
      // Refresh sandbox state
      getSandbox(sandboxId).then(setSandbox).catch(() => {});
    } catch (e) {
      setHistory((h) => [
        ...h,
        { type: "error", text: String(e), timestamp: Date.now() },
      ]);
    } finally {
      setRunning(false);
      textareaRef.current?.focus();
    }
  }, [code, running, sandboxId]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleExecute();
    }
  }

  async function handleKill() {
    if (!confirm("Kill this sandbox? The VM will be terminated.")) return;
    await deleteSandbox(sandboxId);
    router.push("/sandboxes");
  }

  if (error) {
    return (
      <div className="p-8">
        <p className="text-[var(--color-error)]">{error}</p>
      </div>
    );
  }

  if (!sandbox) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--color-text-muted)]" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/sandboxes")}
            className="p-1.5 rounded hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-sm font-semibold">
              {sandbox.label || sandbox.id.slice(0, 8)}
            </h1>
            <div className="flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
              <span className="flex items-center gap-1">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    sandbox.status === "running"
                      ? "bg-[var(--color-success)]"
                      : "bg-blue-500"
                  }`}
                />
                {sandbox.status}
              </span>
              {sandbox.vm_id && (
                <span className="flex items-center gap-1">
                  <Cpu className="w-3 h-3" />
                  {sandbox.vm_id}
                </span>
              )}
              {sandbox.connection_name && (
                <span className="flex items-center gap-1">
                  <Database className="w-3 h-3" />
                  {sandbox.connection_name}
                </span>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={handleKill}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[var(--color-error)] hover:bg-[var(--color-error)]/10 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> Kill
        </button>
      </div>

      {/* Terminal output */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto p-4 font-mono text-sm space-y-1"
      >
        {history.map((entry, i) => (
          <div key={i} className="flex gap-2">
            {entry.type === "input" && (
              <div className="w-full">
                <div className="flex items-center gap-2 text-[var(--color-accent)] mb-0.5">
                  <span className="text-xs opacity-60">In [{history.filter((h, j) => j <= i && h.type === "input").length}]:</span>
                </div>
                <pre className="whitespace-pre-wrap text-[var(--color-text)] bg-[var(--color-bg-card)] p-3 rounded-lg border border-[var(--color-border)]">
                  {entry.text}
                </pre>
              </div>
            )}
            {entry.type === "output" && (
              <div className="w-full">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-xs text-[var(--color-success)] opacity-60">
                    Out [{history.filter((h, j) => j <= i && h.type === "output").length}]:
                  </span>
                  {entry.execution_ms != null && (
                    <span className="text-xs text-[var(--color-text-dim)] flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {entry.execution_ms.toFixed(0)}ms
                    </span>
                  )}
                </div>
                <pre className="whitespace-pre-wrap text-[var(--color-text)]">
                  {entry.text}
                </pre>
              </div>
            )}
            {entry.type === "error" && (
              <div className="w-full">
                <pre className="whitespace-pre-wrap text-[var(--color-error)] bg-[var(--color-error)]/5 p-3 rounded-lg border border-[var(--color-error)]/20">
                  {entry.text}
                </pre>
              </div>
            )}
            {entry.type === "system" && (
              <div className="w-full text-xs text-[var(--color-text-dim)] italic py-1">
                {entry.text}
              </div>
            )}
          </div>
        ))}
        {running && (
          <div className="flex items-center gap-2 text-[var(--color-text-muted)] text-xs py-1">
            <Loader2 className="w-3 h-3 animate-spin" /> Executing...
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
        <div className="flex gap-3">
          <textarea
            ref={textareaRef}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Enter Python code... (Ctrl+Enter to run)"
            rows={3}
            className="flex-1 px-4 py-3 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm font-mono focus:outline-none focus:border-[var(--color-accent)] resize-none placeholder:text-[var(--color-text-dim)]"
            autoFocus
          />
          <button
            onClick={handleExecute}
            disabled={running || !code.trim()}
            className="self-end flex items-center gap-2 px-5 py-3 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            {running ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Run
          </button>
        </div>
        <p className="text-xs text-[var(--color-text-dim)] mt-2">
          Code runs inside an isolated Shuru microVM sandbox. Ctrl+Enter to
          execute.
        </p>
      </div>
    </div>
  );
}
