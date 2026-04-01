"use client";

import { useState, useMemo } from "react";
import { motion } from "framer-motion";
import { clsx } from "clsx";
import type { FeedEvent, ToolCall, AuditEvent, UsageEvent } from "@/lib/types";
import { getToolCategory, TOOL_COLORS, AUDIT_EVENT_META } from "@/lib/types";
import { getToolIcon, getAuditIcon } from "@/components/ui/ToolIcons";

/* ── Helpers ── */

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function extractToolSummary(tc: ToolCall): string {
  const input = tc.input_data;
  if (!input) return "";
  const cat = getToolCategory(tc.tool_name);

  switch (cat) {
    case "bash": {
      const cmd = (input.command as string) || "";
      const desc = (input.description as string) || "";
      return desc || (cmd.length > 100 ? cmd.slice(0, 100) + "…" : cmd);
    }
    case "read": {
      const fp = (input.file_path as string) || "";
      const name = fp.split("/").pop() || fp;
      const offset = input.offset ? ` :${input.offset}` : "";
      return `${name}${offset}`;
    }
    case "write": {
      const fp = (input.file_path as string) || "";
      return fp.split("/").pop() || fp;
    }
    case "edit": {
      const fp = (input.file_path as string) || "";
      return fp.split("/").pop() || fp;
    }
    case "glob": return (input.pattern as string) || "";
    case "grep": {
      const pat = (input.pattern as string) || "";
      const path = (input.path as string) || "";
      const shortPath = path.split("/").slice(-2).join("/");
      return `/${pat}/ in ${shortPath}`;
    }
    case "agent": return (input.description as string) || "";
    case "web_search": return (input.query as string) || "";
    case "web_fetch": return (input.url as string) || "";
    case "todo": {
      const todos = (input.todos as Array<{ status: string; content: string }>) || [];
      const active = todos.filter(t => t.status === "in_progress");
      const pending = todos.filter(t => t.status === "pending");
      const done = todos.filter(t => t.status === "completed");
      return `${done.length} done, ${active.length} active, ${pending.length} pending`;
    }
    case "tool_search": return (input.query as string) || "";
    case "skill": return (input.skill as string) || "";
    case "playwright_navigate": return (input.url as string) || "";
    case "playwright_screenshot": return (input.filename as string) || "screenshot";
    case "playwright_click": return "click";
    case "playwright_form": case "playwright_type": return "form input";
    case "playwright_evaluate": return "evaluate";
    case "playwright_snapshot": return "DOM snapshot";
    case "session_gate": return "end_session";
    default: return JSON.stringify(input).slice(0, 80);
  }
}

function extractOutputSummary(tc: ToolCall): string | null {
  const output = tc.output_data;
  if (!output) return null;
  const cat = getToolCategory(tc.tool_name);

  switch (cat) {
    case "bash": {
      const stdout = (output.stdout as string) || "";
      const stderr = (output.stderr as string) || "";
      const text = stdout || stderr;
      if (!text) return "(no output)";
      const lines = text.split("\n").filter(Boolean);
      if (lines.length <= 3) return text.trim();
      return `${lines.length} lines`;
    }
    case "read": {
      const file = output.file as Record<string, unknown> | undefined;
      if (file) return `${file.totalLines || "?"} lines`;
      return null;
    }
    case "edit": {
      const patch = output.structuredPatch as Array<Record<string, unknown>> | undefined;
      if (patch && patch.length > 0) {
        let added = 0, removed = 0;
        for (const hunk of patch) {
          const lines = (hunk.lines as string[]) || [];
          for (const l of lines) {
            if (l.startsWith("+") && !l.startsWith("+++")) added++;
            if (l.startsWith("-") && !l.startsWith("---")) removed++;
          }
        }
        return `+${added} -${removed}`;
      }
      return null;
    }
    case "write": {
      const patch = output.structuredPatch as Array<Record<string, unknown>> | undefined;
      if (patch) {
        let added = 0;
        for (const hunk of patch) {
          added += (hunk.newLines as number) || 0;
        }
        return `${added} lines written`;
      }
      return (output.type as string) || null;
    }
    default: return null;
  }
}

/* ── Diff Viewer ── */
function DiffViewer({ patch }: { patch: Array<Record<string, unknown>> }) {
  return (
    <div className="font-mono text-[10px] leading-relaxed">
      {patch.map((hunk, hi) => {
        const lines = (hunk.lines as string[]) || [];
        const oldStart = (hunk.oldStart as number) || 0;
        const newStart = (hunk.newStart as number) || 0;
        return (
          <div key={hi} className="mb-2">
            <div className="text-[9px] text-[#555] px-2 py-1 bg-[#0a0a0a] border-b border-[#1a1a1a]">
              @@ -{oldStart},{(hunk.oldLines as number) || 0} +{newStart},{(hunk.newLines as number) || 0} @@
            </div>
            {lines.map((line, li) => {
              const isAdd = line.startsWith("+") && !line.startsWith("+++");
              const isDel = line.startsWith("-") && !line.startsWith("---");
              return (
                <div
                  key={li}
                  className={clsx(
                    "px-2 whitespace-pre-wrap break-all",
                    isAdd && "bg-[#00ff88]/[0.05] text-[#88ffbb]",
                    isDel && "bg-[#ff4444]/[0.05] text-[#ff8888]",
                    !isAdd && !isDel && "text-[#666]"
                  )}
                >
                  {line}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/* ── Bash Output ── */
function BashOutput({ output }: { output: Record<string, unknown> }) {
  const stdout = (output.stdout as string) || "";
  const stderr = (output.stderr as string) || "";
  const text = stdout || stderr;
  if (!text) return <span className="text-[10px] text-[#444] italic">(no output)</span>;

  return (
    <pre className="text-[10px] text-[#aaa] whitespace-pre-wrap break-all leading-relaxed">
      {stderr && <span className="text-[#ff6666]">{stderr}</span>}
      {stdout}
    </pre>
  );
}

/* ── Todo Display ── */
function TodoDisplay({ todos }: { todos: Array<{ status: string; content: string; activeForm?: string }> }) {
  return (
    <div className="space-y-1">
      {todos.map((t, i) => (
        <div key={i} className="flex items-start gap-2 text-[10px]">
          {t.status === "completed" ? (
            <span className="text-[#00ff88] mt-px shrink-0">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                <polyline points="2 5 4 7 8 3" />
              </svg>
            </span>
          ) : t.status === "in_progress" ? (
            <span className="text-[#ffaa00] mt-px shrink-0 animate-pulse">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="5" cy="5" r="3" />
              </svg>
            </span>
          ) : (
            <span className="text-[#444] mt-px shrink-0">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="2" y="2" width="6" height="6" rx="1" />
              </svg>
            </span>
          )}
          <span className={clsx(
            t.status === "completed" && "text-[#666] line-through",
            t.status === "in_progress" && "text-[#ccc]",
            t.status === "pending" && "text-[#888]"
          )}>
            {t.content}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── Tool Call Card ── */
function ToolCallCard({ tc }: { tc: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const denied = !tc.permitted;
  const isCeo = tc.agent_role === "ceo";
  const isComplete = tc.phase === "post" || !!tc.output_data;
  const isPending = tc.phase === "pre" && !tc.output_data;

  const category = getToolCategory(tc.tool_name);
  const colors = TOOL_COLORS[category];
  const summary = useMemo(() => extractToolSummary(tc), [tc]);
  const outputSummary = useMemo(() => extractOutputSummary(tc), [tc]);

  const borderColor = denied
    ? "border-l-[#ff4444]"
    : isCeo
      ? "border-l-[#ff8844]"
      : colors.border;

  const bgColor = denied
    ? "bg-[#ff4444]/[0.02]"
    : isCeo
      ? "bg-[#ff8844]/[0.02]"
      : colors.bg;

  const hasDiff = !!(tc.output_data?.structuredPatch && (category === "edit" || category === "write"));
  const hasBashOutput = !!(category === "bash" && tc.output_data);
  const hasTodos = !!(category === "todo" && tc.input_data?.todos);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className={clsx(
        "group border-l-[3px] rounded-r px-3 py-1.5 cursor-pointer transition-colors",
        borderColor,
        bgColor,
        "hover:bg-white/[0.025]"
      )}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[9px] text-[#444] tabular-nums shrink-0 w-[52px]">
          {formatTs(tc.ts)}
        </span>

        {/* Tool icon */}
        <span className="shrink-0 opacity-70">
          {getToolIcon(category, denied ? "#ff4444" : isCeo ? "#ff8844" : colors.iconColor)}
        </span>

        {/* Agent role badge */}
        <span
          className={clsx(
            "text-[8px] font-bold uppercase tracking-[0.12em] rounded px-1 py-0.5 shrink-0",
            isCeo
              ? "text-[#ff8844] bg-[#ff8844]/12"
              : "text-[#555] bg-white/[0.03]"
          )}
        >
          {isCeo ? "CEO" : "WRK"}
        </span>

        {/* Tool name */}
        <span className={clsx("text-[10px] font-semibold shrink-0", denied ? "text-[#ff4444]" : colors.text)}>
          {tc.tool_name}
        </span>

        {/* Status indicators */}
        {isPending && (
          <span className="text-[9px] text-[#ffaa00]/70 shrink-0 animate-pulse flex items-center gap-1">
            <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
              <circle cx="4" cy="4" r="3" stroke="#ffaa00" strokeWidth="1" strokeDasharray="2 2" style={{ animation: "spin 2s linear infinite" }} />
            </svg>
            running
          </span>
        )}

        {denied && (
          <span className="inline-flex items-center gap-0.5 text-[9px] font-bold text-[#ff4444] bg-[#ff4444]/8 rounded px-1.5 py-0.5 shrink-0 tracking-wider">
            DENIED
          </span>
        )}

        {tc.duration_ms != null && (
          <span className="text-[9px] text-[#555] shrink-0 tabular-nums">
            {formatDuration(tc.duration_ms)}
          </span>
        )}

        {outputSummary && (
          <span className={clsx("text-[9px] shrink-0 tabular-nums", colors.text, "opacity-50")}>
            {outputSummary}
          </span>
        )}

        {/* Summary */}
        <span className="text-[10px] text-[#555] truncate min-w-0 flex-1">
          {denied ? tc.deny_reason : summary}
        </span>

        {/* Expand chevron */}
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          stroke="#444"
          strokeWidth="1.5"
          strokeLinecap="round"
          className={clsx("shrink-0 transition-transform duration-150", expanded && "rotate-90")}
        >
          <polyline points="3 2 7 5 3 8" />
        </svg>
      </div>

      {/* Expanded content */}
      {expanded && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <div className="mt-2 space-y-2 border-t border-white/[0.04] pt-2">
            {/* Tool-specific rendered content */}
            {hasTodos && (
                <div>
                  <div className="text-[8px] uppercase tracking-[0.15em] text-[#555] mb-1">Tasks</div>
                  <TodoDisplay todos={tc.input_data!.todos as Array<{ status: string; content: string; activeForm?: string }>} />
                </div>
              )}

              {hasDiff && (
                <div>
                  <div className="text-[8px] uppercase tracking-[0.15em] text-[#555] mb-1">Diff</div>
                  <div className="bg-black/30 rounded border border-[#1a1a1a] overflow-hidden max-h-[500px] overflow-y-auto">
                    <DiffViewer patch={tc.output_data!.structuredPatch as Array<Record<string, unknown>>} />
                  </div>
                </div>
              )}

              {hasBashOutput && (
                <div>
                  <div className="text-[8px] uppercase tracking-[0.15em] text-[#555] mb-1">Output</div>
                  <div className="bg-black/30 rounded border border-[#1a1a1a] p-2 max-h-[500px] overflow-y-auto">
                    <BashOutput output={tc.output_data!} />
                  </div>
                </div>
              )}

              {/* Raw Input - always available */}
              {tc.input_data && !hasTodos && (
                <div>
                  <div className="text-[8px] uppercase tracking-[0.15em] text-[#555] mb-1">Input</div>
                  <pre className="text-[10px] text-[#777] bg-black/30 rounded border border-[#1a1a1a] p-2 overflow-x-auto max-h-[400px] overflow-y-auto whitespace-pre-wrap break-all">
                    {JSON.stringify(tc.input_data, null, 2)}
                  </pre>
                </div>
              )}

              {/* Raw Output - show when no specialized renderer */}
              {tc.output_data && !hasDiff && !hasBashOutput && (
                <div>
                  <div className="text-[8px] uppercase tracking-[0.15em] text-[#00ff88]/50 mb-1">Result</div>
                  <pre className="text-[10px] text-[#777] bg-black/30 rounded border border-[#1a1a1a] p-2 overflow-x-auto max-h-[400px] overflow-y-auto whitespace-pre-wrap break-all">
                    {JSON.stringify(tc.output_data, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
    </motion.div>
  );
}

/* ── Audit Event Card ── */
function AuditCard({ event }: { event: AuditEvent }) {
  const [expanded, setExpanded] = useState(false);
  const meta = AUDIT_EVENT_META[event.event_type] || { label: event.event_type, color: "text-[#777]", bg: "bg-[#777]/[0.03]", iconColor: "#777" };

  // Extract key details for inline preview
  const preview = useMemo(() => {
    const d = event.details;
    switch (event.event_type) {
      case "round_complete":
        return `Round ${d.round} · ${d.turns} turns · $${(d.cost_usd as number)?.toFixed(3) || "?"} · ${(d.elapsed_minutes as number)?.toFixed(1)}min`;
      case "run_started":
        return `${d.model || "claude"} · ${d.branch || "?"}${d.custom_prompt ? " · custom prompt" : ""}`;
      case "pr_created":
        return (d.url as string) || "";
      case "pr_failed":
        return ((d.error as string) || "").slice(0, 100);
      case "session_ended":
        return `${d.changes_made || 0} changes · ${(d.elapsed_minutes as number)?.toFixed(1) || "?"}min`;
      case "ceo_continuation":
        return `Round ${d.round} · ${d.tool_summary || ""}`;
      case "worker_assignment":
        return `Round ${d.round}`;
      case "killed":
        return `${(d.elapsed_minutes as number)?.toFixed(1) || "?"}min elapsed`;
      case "fatal_error":
        return ((d.error as string) || "").slice(0, 100);
      case "rate_limit":
        return `${d.status || "?"} · resets at ${d.resets_at || "?"}`;
      case "rate_limit_paused":
        return `wait ${d.wait_seconds || "?"}s`;
      case "end_session_denied":
        return `${d.time_remaining || "?"} remaining`;
      case "sdk_config":
        return `${d.model || "?"} · effort:${d.effort || "?"} · ${(d.mcp_servers as string[])?.join(", ") || ""}`;
      case "stop_requested":
        return (d.reason as string) || "";
      default:
        return JSON.stringify(d).slice(0, 120);
    }
  }, [event]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className={clsx(
        "group border-l-[3px] rounded-r px-3 py-1.5 cursor-pointer transition-colors",
        `border-l-[${meta.iconColor}]`,
        meta.bg,
        "hover:bg-white/[0.025]"
      )}
      style={{ borderLeftColor: meta.iconColor }}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[9px] text-[#444] tabular-nums shrink-0 w-[52px]">
          {formatTs(event.ts)}
        </span>

        <span className="shrink-0 opacity-70">
          {getAuditIcon(event.event_type, meta.iconColor)}
        </span>

        <span className={clsx("text-[10px] font-semibold shrink-0", meta.color)}>
          {meta.label}
        </span>

        <span className="text-[10px] text-[#555] truncate min-w-0 flex-1">
          {preview}
        </span>

        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          stroke="#444"
          strokeWidth="1.5"
          strokeLinecap="round"
          className={clsx("shrink-0 transition-transform duration-150", expanded && "rotate-90")}
        >
          <polyline points="3 2 7 5 3 8" />
        </svg>
      </div>

      {expanded && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <div className="mt-2 border-t border-white/[0.04] pt-2">
            {event.event_type === "session_ended" && !!event.details.summary && (
              <div className="text-[10px] text-[#aaa] whitespace-pre-wrap break-words leading-relaxed mb-2">
                {String(event.details.summary)}
              </div>
            )}
            {event.event_type === "worker_assignment" && !!event.details.assignment && (
              <div className="text-[10px] text-[#aaa] whitespace-pre-wrap break-words leading-relaxed mb-2">
                {String(event.details.assignment)}
              </div>
            )}
            {event.event_type === "ceo_continuation" && !!event.details.round_summary && (
              <div className="text-[10px] text-[#aaa] whitespace-pre-wrap break-words leading-relaxed mb-2">
                {String(event.details.round_summary)}
              </div>
            )}
            {event.event_type === "end_session_denied" && !!event.details.summary && (
              <div className="text-[10px] text-[#aaa] whitespace-pre-wrap break-words leading-relaxed mb-2">
                {String(event.details.summary)}
              </div>
            )}
            {event.event_type === "pr_created" && !!event.details.url && (
              <a
                href={String(event.details.url)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] text-[#88ccff] hover:text-[#aaddff] underline underline-offset-2"
                onClick={(e) => e.stopPropagation()}
              >
                {String(event.details.url)}
              </a>
            )}
            {/* Raw JSON fallback */}
            <pre className="text-[10px] text-[#666] bg-black/30 rounded border border-[#1a1a1a] p-2 overflow-x-auto max-h-[400px] overflow-y-auto whitespace-pre-wrap break-all">
              {JSON.stringify(event.details, null, 2)}
            </pre>
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

/* ── Usage Card ── */
function UsageCard({ usage }: { usage: UsageEvent }) {
  const fmt = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return n.toLocaleString();
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 2 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.1 }}
      className="border-l-[3px] border-l-[#44ccdd]/30 bg-[#44ccdd]/[0.015] rounded-r px-3 py-1"
    >
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[9px] text-[#444] tabular-nums shrink-0 w-[52px]">
          {formatTs(usage.ts)}
        </span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#44ccdd" strokeWidth="1" opacity="0.5">
          <rect x="1" y="6" width="2" height="5" rx="0.5" />
          <rect x="5" y="3" width="2" height="8" rx="0.5" />
          <rect x="9" y="1" width="2" height="10" rx="0.5" />
        </svg>
        <span className="text-[9px] font-medium text-[#44ccdd]/60 tracking-wider">USAGE</span>
        <span className="text-[9px] text-[#666] tabular-nums">
          in:{fmt(usage.input_tokens)} out:{fmt(usage.output_tokens)}
        </span>
        <span className="text-[9px] text-[#555] tabular-nums">
          total: {fmt(usage.total_input_tokens)}↓ {fmt(usage.total_output_tokens)}↑
        </span>
        {usage.cache_read_input_tokens > 0 && (
          <span className="text-[9px] text-[#555] tabular-nums">
            cache:{fmt(usage.cache_read_input_tokens)}
          </span>
        )}
      </div>
    </motion.div>
  );
}

/* ── Control Card ── */
function ControlCard({ text, ts }: { text: string; ts: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      className="border-l-[3px] border-l-[#ffaa00] bg-[#ffaa00]/[0.03] rounded-r px-3 py-1.5"
    >
      <div className="flex items-center gap-2">
        <span className="text-[9px] text-[#444] tabular-nums w-[52px]">
          {formatTs(ts)}
        </span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#ffaa00" strokeWidth="1.5" strokeLinecap="round">
          <polyline points="2 4 5 7 2 10" />
          <line x1="7" y1="10" x2="10" y2="10" />
        </svg>
        <span className="text-[9px] font-bold text-[#ffaa00] tracking-wider uppercase">
          Control
        </span>
        <span className="text-[10px] text-[#888]">{text}</span>
      </div>
    </motion.div>
  );
}

/* ── Main Event Card ── */
export function EventCard({ event }: { event: FeedEvent }) {
  switch (event._kind) {
    case "tool":
      return <ToolCallCard tc={event.data} />;
    case "audit":
      return <AuditCard event={event.data} />;
    case "control":
      return <ControlCard text={event.text} ts={event.ts} />;
    case "usage":
      return <UsageCard usage={event.data} />;
    case "llm_text":
    case "llm_thinking":
      return null; // Handled by LLMOutput
    default:
      return null;
  }
}
