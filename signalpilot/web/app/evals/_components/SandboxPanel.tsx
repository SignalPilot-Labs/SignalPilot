"use client";

/**
 * This component displays evaluation sandboxes.
 * It shows sandbox status, current activity, and scheduling delays.
 * It displays pod events automatically for a sandbox that is not Running.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Activity, AlertTriangle, Box, Loader2, RefreshCw, Terminal } from "lucide-react";
import {
  evalSandboxName,
  getEvalSandboxEvents,
  listEvalSandboxes,
  subscribeEvalSandboxLogs,
  type EvalActiveTask,
  type EvalLogEvent,
  type EvalRunProgress,
  type EvalSandbox,
} from "~/lib/api";

/**
 * An active-task card sends a DOM event to select its sandbox row.
 * The event keeps RunDetail independent of SandboxPanel.
 */
export const OPEN_SANDBOX_EVENT = "ev-open-sandbox";
export function requestOpenSandbox(name: string) {
  window.dispatchEvent(new CustomEvent(OPEN_SANDBOX_EVENT, { detail: name }));
}

const LOG_TAIL_LINES = 400;
// The viewer retains this number of log entries in the DOM.
// The server limits the stream size.
const MAX_LOG_CHARS = 400_000;
// The interface marks a live sandbox as stalled after this interval without output.
const SILENCE_WARN_SECONDS = 90;

const PHASE_COLOR: Record<string, string> = {
  running: "var(--color-success)",
  pending: "var(--color-warning, #f5a623)",
  succeeded: "var(--color-text-dim)",
  failed: "#e5484d",
  unknown: "var(--color-text-dim)",
};

function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

/* The following code displays run progress. */

function ActiveTaskCard({ task, now }: { task: EvalActiveTask; now: number }) {
  const startedMs = Date.parse(task.started_at);
  const elapsed = Number.isFinite(startedMs) ? Math.max(0, Math.round(now - startedMs / 1000)) : null;
  const sandbox = evalSandboxName(task.sandbox);
  return (
    <div className="border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg-card)] px-3 py-2">
      <div className="flex items-center gap-2 text-xs">
        <Loader2 className="w-3 h-3 animate-spin flex-shrink-0 text-[var(--color-warning,#f5a623)]" />
        <span className="text-[var(--color-text)] truncate min-w-0">{task.title || task.task_id}</span>
        <span className="ev-badge flex-shrink-0">{task.phase}</span>
        <span className="ml-auto text-[var(--color-text-dim)] font-mono tabular-nums whitespace-nowrap">
          {elapsed != null ? fmtAge(elapsed) : "—"}
        </span>
      </div>
      {sandbox && (
        <button
          onClick={() => requestOpenSandbox(sandbox)}
          title="Open this sandbox's live logs below"
          className="mt-1 text-[11px] font-mono text-[var(--color-text-dim)] hover:text-[var(--color-text)] underline underline-offset-2 truncate max-w-full block text-left"
        >
          {sandbox}
        </button>
      )}
    </div>
  );
}

/** Show the completed-task count and one card for each active task. */
export function RunProgressBar({ progress }: { progress: EvalRunProgress }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);

  const total = progress.total || 0;
  const done = progress.done || 0;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const finished = progress.phase === "finished";
  const active = progress.active ?? [];
  const label =
    finished ? "finished"
    : progress.phase === "preparing" ? "preparing"
    : active.length > 0 ? `${active.length} task${active.length === 1 ? "" : "s"} running`
    : progress.phase;

  return (
    <div className="mt-4 border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] px-3 py-2.5">
      <div className="flex items-center gap-3 flex-wrap text-xs">
        {!finished && <Loader2 className="w-3 h-3 animate-spin text-[var(--color-warning,#f5a623)]" />}
        <span className="text-[var(--color-text)]">{label}</span>
        <span className="ml-auto text-[var(--color-text-dim)] font-mono tabular-nums">
          {done}/{total} done
          {progress.elapsed_s != null && !finished && ` · ${fmtAge(progress.elapsed_s)} elapsed`}
        </span>
      </div>
      <div className="mt-2 h-[3px] rounded-full bg-[var(--color-border)] overflow-hidden">
        <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${pct}%`, background: "var(--color-success)" }} />
      </div>
      {progress.error && <p className="mt-1.5 text-[11px] text-[#e5484d]">{progress.error}</p>}
      {active.length > 0 && (
        <div className="mt-2.5 grid grid-cols-1 md:grid-cols-2 gap-2">
          {active.map((t) => (
            <ActiveTaskCard key={t.task_id} task={t} now={now} />
          ))}
        </div>
      )}
    </div>
  );
}

/* The following code displays pod events. */

function SandboxEvents({ name }: { name: string }) {
  const { data, isLoading } = useSWR(`eval-sandbox-events-${name}`, () => getEvalSandboxEvents(name), {
    refreshInterval: 8000,
  });
  if (isLoading) return <p className="text-xs text-[var(--color-text-dim)]">reading events…</p>;
  if (!data) return null;
  if (!data.supported) return <p className="text-xs text-[var(--color-text-dim)]">{data.message}</p>;
  if (!data.events.length) {
    return <p className="text-xs text-[var(--color-text-dim)]">{data.message || "no events recorded for this sandbox"}</p>;
  }
  return (
    <div className="space-y-1">
      {data.events.map((e, i) => (
        <div key={`${e.reason}-${e.last_seen}-${i}`} className="flex items-start gap-2 text-[11px]">
          <span
            className="mt-[3px] w-1.5 h-1.5 rounded-full flex-shrink-0"
            style={{ background: e.type === "Warning" ? "#e5484d" : "var(--color-text-dim)" }}
          />
          <span className="font-mono text-[var(--color-text)] whitespace-nowrap">{e.reason}</span>
          <span className="text-[var(--color-text-muted)] break-words min-w-0">{e.message}</span>
          <span className="ml-auto text-[var(--color-text-dim)] whitespace-nowrap font-mono tabular-nums">
            {e.count > 1 ? `×${e.count} · ` : ""}{fmtAge(e.age_seconds)} ago
          </span>
        </div>
      ))}
    </div>
  );
}

/* The following code displays live logs. */

function LogViewer({ sandbox }: { sandbox: EvalSandbox }) {
  const [text, setText] = useState("");
  const [lastLineAt, setLastLineAt] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);
  const [ended, setEnded] = useState<string | null>(null);
  const [beatAt, setBeatAt] = useState<number>(() => Date.now() / 1000);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [follow, setFollow] = useState(true);
  const boxRef = useRef<HTMLPreElement>(null);
  const [nonce, setNonce] = useState(0);

  const onEvent = useCallback((e: EvalLogEvent) => {
    setBeatAt(e.at);
    if (e.type === "open") return setConnected(true);
    if (e.type === "heartbeat") return;
    if (e.type === "end") {
      setConnected(false);
      setEnded(e.reason);
      return;
    }
    setLastLineAt(e.at);
    setText((prev) => {
      const next = prev + e.text;
      return next.length > MAX_LOG_CHARS ? next.slice(next.length - MAX_LOG_CHARS) : next;
    });
  }, []);

  useEffect(() => {
    setText("");
    setEnded(null);
    setConnected(false);
    setLastLineAt(null);
    return subscribeEvalSandboxLogs(sandbox.name, LOG_TAIL_LINES, onEvent);
  }, [sandbox.name, nonce, onEvent]);

// This value supplies the activity status. The server pushes stream updates.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [text, follow]);

  const silentFor = lastLineAt ? Math.max(0, Math.round(now - lastLineAt)) : null;
  const stalled = connected && silentFor != null && silentFor > SILENCE_WARN_SECONDS;
  const linkDead = connected && now - beatAt > 30;

  return (
    <div className="mt-3">
      <div className="flex items-center gap-3 flex-wrap text-[11px] mb-1.5">
        <span className="inline-flex items-center gap-1.5" style={{ color: connected ? "var(--color-success)" : "var(--color-text-dim)" }}>
          <span
            className={`w-1.5 h-1.5 rounded-full ${connected && !linkDead ? "animate-pulse" : ""}`}
            style={{ background: connected ? (stalled ? "var(--color-warning, #f5a623)" : "var(--color-success)") : "var(--color-text-dim)" }}
          />
          {connected ? (stalled ? `no output for ${fmtAge(silentFor)}` : "streaming") : ended ? `stream ended · ${ended}` : "connecting…"}
        </span>
        {lastLineAt && (
          <span className="text-[var(--color-text-dim)] font-mono tabular-nums">
            last line {fmtAge(silentFor)} ago
          </span>
        )}
        <label className="ml-auto inline-flex items-center gap-1.5 text-[var(--color-text-dim)] cursor-pointer">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-[var(--color-success)]" />
          follow
        </label>
        <button
          onClick={() => setNonce((n) => n + 1)}
          className="inline-flex items-center gap-1 text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
        >
          <RefreshCw className="w-3 h-3" /> reattach
        </button>
      </div>
      <pre
        ref={boxRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
        }}
        className="ev-raw border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] p-3"
        style={{ maxHeight: "420px" }}
      >
        {text || (ended ? "(no output captured)" : "waiting for output…")}
      </pre>
    </div>
  );
}

/* The following code displays a sandbox row. */

function SandboxRow({ sandbox, open, onToggle }: { sandbox: EvalSandbox; open: boolean; onToggle: () => void }) {
  const color = PHASE_COLOR[sandbox.phase] ?? "var(--color-text-dim)";
  const troubled = sandbox.phase !== "running" && sandbox.phase !== "succeeded";
  return (
    <div className="border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] px-3 py-2">
      <button onClick={onToggle} className="w-full text-left">
        <div className="flex items-center gap-3 flex-wrap text-xs">
          <span className="inline-flex items-center gap-1.5 uppercase tracking-[0.12em] text-[10px]" style={{ color }}>
            <span className={`w-1.5 h-1.5 rounded-full ${sandbox.phase === "running" ? "animate-pulse" : ""}`} style={{ background: color }} />
            {sandbox.phase}
          </span>
          <code className="text-[var(--color-text)]">{sandbox.name}</code>
          <span className="ev-badge">{sandbox.reason}</span>
          {sandbox.oom_killed && (
            <span className="ev-badge" style={{ color: "#e5484d", borderColor: "#e5484d" }}>
              <AlertTriangle className="w-2.5 h-2.5" /> OOMKilled
            </span>
          )}
          {sandbox.restart_count > 0 && <span className="ev-badge">{sandbox.restart_count} restarts</span>}
          <span className="ml-auto text-[var(--color-text-dim)] font-mono tabular-nums whitespace-nowrap">
            {fmtAge(sandbox.age_seconds)}{sandbox.node ? ` · ${sandbox.node}` : ""}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--color-text-muted)]">
          <span className="ev-badge">{sandbox.task_phase}</span>
          <span className="truncate">
            {sandbox.task_title || sandbox.task_id || "unattributed"}
          </span>
          {sandbox.run_id && <code className="text-[var(--color-text-dim)] ml-auto whitespace-nowrap">{sandbox.run_id}</code>}
        </div>
      </button>

      {sandbox.oom_killed && (
        <p className="mt-1.5 text-[11px] text-[#e5484d]">
          The container exceeded its memory limit. Raise SP_EVAL_MEMORY_LIMIT (and its request in step —
          the namespace caps the limit:request ratio at 4) before reading this as an agent failure.
        </p>
      )}
      {sandbox.message && !sandbox.oom_killed && (
        <p className="mt-1.5 text-[11px] text-[var(--color-text-muted)] break-words">{sandbox.message}</p>
      )}

      {/* Display scheduling events automatically when a pod is not Running. */}
      {troubled && (
        <div className="mt-2 pt-2 border-t border-[var(--color-border)]">
          <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] mb-1.5">pod events</div>
          <SandboxEvents name={sandbox.name} />
        </div>
      )}

      {open && (
        <>
          <LogViewer sandbox={sandbox} />
          {!troubled && (
            <details className="mt-2">
              <summary className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] cursor-pointer">
                pod events
              </summary>
              <div className="mt-1.5">
                <SandboxEvents name={sandbox.name} />
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}

/* The following code displays the sandbox panel. */

export function SandboxPanel() {
  const [openName, setOpenName] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const { data, error, isLoading } = useSWR("eval-sandboxes", listEvalSandboxes, {
    refreshInterval: 4000,
  });

  const sandboxes = data?.sandboxes ?? [];
  const active = sandboxes.filter((s) => s.phase === "running" || s.phase === "pending").length;

  // Select the active sandbox automatically in the log viewer.
  useEffect(() => {
    if (openName && sandboxes.some((s) => s.name === openName)) return;
    const live = sandboxes.find((s) => s.phase === "running") ?? sandboxes[0];
    setOpenName(live ? live.name : null);
  }, [sandboxes, openName]);

  // Handle the RunDetail event that selects a sandbox log.
  useEffect(() => {
    const onOpen = (e: Event) => {
      const name = (e as CustomEvent<string>).detail;
      if (!name) return;
      setOpenName(name);
      rootRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    window.addEventListener(OPEN_SANDBOX_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_SANDBOX_EVENT, onOpen);
  }, []);

  return (
    <div className="ev-card p-5" ref={rootRef}>
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <h2 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">Sandboxes</h2>
        {data && (
          <span className="ev-badge">
            <Box className="w-2.5 h-2.5" />
            {data.backend}
            {data.namespace ? ` · ${data.namespace}` : ""}
          </span>
        )}
        {active > 0 && (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-[var(--color-success)]">
            <Activity className="w-3 h-3" /> {active} live
          </span>
        )}
        {isLoading && <Loader2 className="w-3 h-3 animate-spin text-[var(--color-text-dim)]" />}
      </div>

      {error && (
        <p className="text-sm text-[var(--color-text-dim)]">
          couldn’t read sandboxes — the gateway may not be able to reach the execution backend.
        </p>
      )}

      {data && !data.live && data.message && (
        <p className="text-sm text-[var(--color-text-dim)] flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0 text-[var(--color-warning,#f5a623)]" strokeWidth={1.5} />
          {data.message}
        </p>
      )}

      {data?.live && sandboxes.length === 0 && (
        <p className="text-sm text-[var(--color-text-dim)] flex items-center gap-2">
          <Terminal className="w-4 h-4" strokeWidth={1.5} />
          No eval sandbox is running right now.
        </p>
      )}

      {sandboxes.length > 0 && (
        <div className="space-y-2">
          {sandboxes.map((s) => (
            <SandboxRow
              key={s.name}
              sandbox={s}
              open={openName === s.name}
              onToggle={() => setOpenName(openName === s.name ? null : s.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
