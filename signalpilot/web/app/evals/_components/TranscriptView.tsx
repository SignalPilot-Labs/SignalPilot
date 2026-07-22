"use client";

/**
 * Eval-run transcript: parses claude stream-json and renders it with the
 * shared agent-transcript turn components (turns.tsx). Tool results are
 * paired into their tool-call cards. TranscriptSlideOver presents it in a
 * right slide-over that can expand to take over the page.
 */

import { useEffect, useState } from "react";
import { Loader2, Maximize2, Minimize2, X } from "lucide-react";
import { getEvalTranscript } from "~/lib/api";
import {
  AgentTurn,
  ResultFooter,
  SessionCard,
  ThinkingTurn,
  ToolCallTurn,
  ToolResultTurn,
  UnknownTurn,
  UserTurn,
} from "./turns";

type Turn =
  | { kind: "init"; model: string; mcpServers: string[]; toolCount: number }
  | { kind: "user_text"; text: string }
  | { kind: "text"; text: string }
  | { kind: "thinking"; text: string }
  | { kind: "tool_use"; name: string; input: unknown; result?: string; resultError?: boolean }
  | { kind: "tool_result"; text: string; isError: boolean }
  | { kind: "result"; durationMs: number; turns: number; costUsd: number }
  | { kind: "unknown"; label: string; payload: unknown };

/* eslint-disable @typescript-eslint/no-explicit-any */
function parseTranscript(raw: string): Turn[] {
  const turns: Turn[] = [];
  for (const line of raw.split("\n")) {
    const l = line.trim().replace(/\r$/, "");
    if (!l.startsWith("{")) continue;
    let e: any;
    try {
      e = JSON.parse(l);
    } catch {
      continue;
    }
    if (e.type === "system" && e.subtype === "init") {
      turns.push({
        kind: "init",
        model: e.model ?? "?",
        mcpServers: (e.mcp_servers ?? []).map((s: any) => s.name ?? String(s)),
        toolCount: (e.tools ?? []).length,
      });
    } else if (e.type === "assistant" || e.type === "user") {
      const content = e.message?.content;
      if (!Array.isArray(content)) {
        if (typeof content === "string" && content.trim()) {
          turns.push({ kind: e.type === "user" ? "user_text" : "text", text: content });
        }
        continue;
      }
      for (const item of content) {
        if (item.type === "text" && item.text?.trim()) {
          turns.push({ kind: e.type === "user" ? "user_text" : "text", text: item.text });
        } else if (item.type === "thinking") {
          // Signature-only thinking blocks (empty text) are skipped entirely.
          if (item.thinking?.trim()) turns.push({ kind: "thinking", text: item.thinking });
        } else if (item.type === "tool_use") {
          turns.push({ kind: "tool_use", name: String(item.name ?? "tool"), input: item.input ?? {} });
        } else if (item.type === "tool_result") {
          let text = "";
          if (typeof item.content === "string") text = item.content;
          else if (Array.isArray(item.content)) {
            text = item.content
              .map((c: any) =>
                c.type === "text" ? c.text
                : c.type === "tool_reference" ? `· ${String(c.tool_name ?? "")}`
                : `[${c.type}]`,
              )
              .join("\n");
          }
          turns.push({ kind: "tool_result", text, isError: !!item.is_error });
        } else if (item.type) {
          turns.push({ kind: "unknown", label: String(item.type), payload: item });
        }
      }
    } else if (e.type === "result") {
      turns.push({
        kind: "result",
        durationMs: e.duration_ms ?? 0,
        turns: e.num_turns ?? 0,
        costUsd: e.total_cost_usd ?? 0,
      });
    }
    // Other top-level stream events (system:*, rate_limit_event, …) are
    // harness telemetry, not conversation — skip rather than render noise.
  }
  // Pair each tool_result with the nearest preceding unresolved tool_use so
  // the result renders inside its call card.
  const paired: Turn[] = [];
  const pending: Extract<Turn, { kind: "tool_use" }>[] = [];
  for (const t of turns) {
    if (t.kind === "tool_use") {
      pending.push(t);
      paired.push(t);
    } else if (t.kind === "tool_result" && pending.length > 0) {
      const call = pending.shift()!;
      call.result = t.text;
      call.resultError = t.isError;
    } else {
      paired.push(t);
    }
  }
  return paired;
}

export function TranscriptItems({ turns }: { turns: Turn[] }) {
  return (
    <>
      {turns.map((t, i) => {
        switch (t.kind) {
          case "init":
            return <SessionCard key={i} model={t.model} toolCount={t.toolCount} mcpServers={t.mcpServers} />;
          case "user_text":
            return <UserTurn key={i} text={t.text} />;
          case "text":
            return <AgentTurn key={i} text={t.text} />;
          case "thinking":
            return <ThinkingTurn key={i} text={t.text} />;
          case "tool_use":
            return <ToolCallTurn key={i} name={t.name} input={t.input} resultText={t.result} isError={t.resultError} />;
          case "tool_result":
            return <ToolResultTurn key={i} text={t.text} isError={t.isError} />;
          case "result":
            return <ResultFooter key={i} durationMs={t.durationMs} turns={t.turns} costUsd={t.costUsd} />;
          default:
            return <UnknownTurn key={i} label={t.kind === "unknown" ? t.label : "event"} payload={t.kind === "unknown" ? t.payload : t} />;
        }
      })}
    </>
  );
}

export function TranscriptSlideOver({
  runId,
  questionId,
  title,
  onClose,
}: {
  runId: string;
  questionId: string;
  title: string;
  onClose: () => void;
}) {
  const [turns, setTurns] = useState<Turn[] | null>(null);
  const [error, setError] = useState(false);
  const [full, setFull] = useState(false);

  useEffect(() => {
    let alive = true;
    getEvalTranscript(runId, questionId)
      .then((raw) => alive && setTurns(parseTranscript(raw)))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [runId, questionId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="ev-overlay" onClick={onClose} />
      <div className={`ev-panel ev-panel--wide ${full ? "ev-panel--full" : ""}`}>
        <div className="sticky top-0 z-10 bg-[var(--color-bg-card)] border-b border-[var(--color-border)] px-6 py-3.5 flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-text-dim)]">transcript</div>
            <div className="text-sm text-[var(--color-text)] truncate">{title}</div>
          </div>
          <button
            onClick={() => setFull(!full)}
            aria-label={full ? "shrink" : "expand"}
            title={full ? "Shrink to panel" : "Expand to full page"}
            className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] p-1"
          >
            {full ? <Minimize2 className="w-4 h-4" strokeWidth={1.5} /> : <Maximize2 className="w-4 h-4" strokeWidth={1.5} />}
          </button>
          <button onClick={onClose} aria-label="close" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] p-1">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className={`px-6 py-4 ${full ? "max-w-4xl mx-auto" : ""}`}>
          {error ? (
            <p className="text-sm text-[var(--color-text-dim)]">transcript not available</p>
          ) : !turns ? (
            <p className="text-sm text-[var(--color-text-dim)] flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> loading transcript…
            </p>
          ) : (
            <TranscriptItems turns={turns} />
          )}
        </div>
      </div>
    </>
  );
}
