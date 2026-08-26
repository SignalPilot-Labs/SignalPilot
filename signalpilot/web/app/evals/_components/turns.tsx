"use client";

/**
 * Agent-transcript design system: one polished component per turn type,
 * shared by the eval transcript slide-over and the /chats reader.
 * Unknown tools/messages degrade gracefully to labeled generic cards.
 */

import { useState } from "react";
import {
  AlertTriangle,
  Brain,
  ChevronDown,
  ChevronRight,
  Database,
  FileText,
  Search,
  Terminal,
  Wrench,
} from "lucide-react";
import { Md } from "./Markdown";

/* ─── helpers ───────────────────────────────────────────────────────────── */

const SQL_KEYWORDS =
  /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|GROUP BY|ORDER BY|HAVING|LIMIT|SUM|COUNT|AVG|MIN|MAX|DISTINCT|AS|ON|AND|OR|NOT|IN|CASE|WHEN|THEN|ELSE|END|WITH|UNION|ALL|INSERT|UPDATE|CREATE|DROP|TABLE)\b/gi;

/** SQL block with lightweight keyword highlighting. */
export function SqlBlock({ sql }: { sql: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of sql.matchAll(SQL_KEYWORDS)) {
    if (m.index! > last) parts.push(sql.slice(last, m.index));
    parts.push(<span key={m.index} className="kw">{m[0]}</span>);
    last = m.index! + m[0].length;
  }
  if (last < sql.length) parts.push(sql.slice(last));
  return <pre className="tr-sql">{parts}</pre>;
}

function toolIcon(name: string) {
  const n = name.toLowerCase();
  if (n.includes("query") || n.includes("sql") || n.includes("database") || n.includes("table")) return Database;
  if (n.includes("search") || n.includes("knowledge") || n.includes("schema")) return Search;
  if (n.includes("read") || n.includes("file") || n.includes("doc")) return FileText;
  return Wrench;
}

export function prettyToolName(name: string): string {
  return name.replace(/^mcp__signalpilot__/, "sp:").replace(/^mcp__([^_]+)__/, "$1:");
}

/** One-line human summary of a tool's input, for the collapsed card header. */
export function toolHint(input: unknown): string {
  if (input == null) return "";
  if (typeof input === "string") return input.slice(0, 120);
  if (typeof input === "object") {
    const o = input as Record<string, unknown>;
    for (const key of ["sql", "query", "task_description", "question", "table", "path", "file_path", "connection_name", "name"]) {
      if (typeof o[key] === "string" && (o[key] as string).trim()) {
        return String(o[key]).replace(/\s+/g, " ").slice(0, 120);
      }
    }
    const keys = Object.keys(o);
    return keys.length ? keys.join(", ").slice(0, 120) : "";
  }
  return String(input).slice(0, 120);
}

function CollapsibleCard({
  variant,
  head,
  children,
  defaultOpen = false,
}: {
  variant: string;
  head: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`tr-item tr-card ${variant}`}>
      <button className="tr-card-head" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown className="w-3 h-3 flex-shrink-0" /> : <ChevronRight className="w-3 h-3 flex-shrink-0" />}
        {head}
      </button>
      {open && <div className="tr-card-body">{children}</div>}
    </div>
  );
}

/* ─── turn components ───────────────────────────────────────────────────── */

export function SessionCard({ model, toolCount, mcpServers }: { model: string; toolCount: number; mcpServers: string[] }) {
  return (
    <div className="tr-item tr-card tr-card--meta">
      <div className="tr-card-head" style={{ cursor: "default" }}>
        <Terminal className="w-3 h-3 flex-shrink-0" />
        <span className="hint">
          session · {model} · {toolCount} tools · mcp: {mcpServers.join(", ") || "none"}
        </span>
      </div>
    </div>
  );
}

export function UserTurn({ text }: { text: string }) {
  return (
    <div className="tr-item tr-user">
      <div className="tr-user-bubble">
        <div className="tr-role">you</div>
        <div className="text-sm text-[var(--color-text)] whitespace-pre-wrap">{text}</div>
      </div>
    </div>
  );
}

export function AgentTurn({ text, costUsd }: { text: string; costUsd?: number | null }) {
  return (
    <div className="tr-item tr-agent">
      <div className="tr-role">agent{costUsd ? ` · $${costUsd.toFixed(3)}` : ""}</div>
      <Md>{text}</Md>
    </div>
  );
}

export function ThinkingTurn({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text.trim()) return null;
  return (
    <div className="tr-item tr-thinking">
      <button className="tr-role" onClick={() => setOpen(!open)} style={{ cursor: "pointer" }}>
        <Brain className="w-3 h-3" />
        thinking · {text.length.toLocaleString()} chars
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
      </button>
      {open && <div className="text-xs italic text-[var(--color-text-dim)] whitespace-pre-wrap leading-relaxed">{text}</div>}
    </div>
  );
}

export function ToolCallTurn({
  name,
  input,
  isError = false,
  resultText,
}: {
  name: string;
  input: unknown;
  isError?: boolean;
  resultText?: string;
}) {
  const isMcp = name.startsWith("mcp__") || name.startsWith("sp:");
  const Icon = toolIcon(name);
  const obj = (typeof input === "object" && input !== null ? input : null) as Record<string, unknown> | null;
  const sql = obj && typeof obj.sql === "string" ? obj.sql : null;
  const rest = obj ? Object.fromEntries(Object.entries(obj).filter(([k]) => k !== "sql")) : null;

  return (
    <CollapsibleCard
      variant={isError ? "tr-card--error" : isMcp ? "tr-card--mcp" : "tr-card--tool"}
      head={
        <>
          <Icon className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={1.5} />
          <span className={`name${isMcp ? " mcp" : ""}`}>{prettyToolName(name)}</span>
          <span className="hint">{toolHint(input)}</span>
          {isError && <AlertTriangle className="w-3 h-3 flex-shrink-0" style={{ color: "#e5484d" }} />}
        </>
      }
    >
      {sql && <SqlBlock sql={sql} />}
      {rest && Object.keys(rest).length > 0 && (
        <dl className={`tr-kv ${sql ? "mt-3 pt-3 border-t border-[var(--color-border)]" : ""}`}>
          {Object.entries(rest).map(([k, v]) => (
            <div key={k} className="contents">
              <dt>{k}</dt>
              <dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {!sql && !rest && <pre className="ev-raw">{typeof input === "string" ? input : JSON.stringify(input, null, 2)}</pre>}
      {resultText && (
        <pre className="ev-raw mt-3 pt-3 border-t border-[var(--color-border)]">{resultText.slice(0, 20000)}</pre>
      )}
    </CollapsibleCard>
  );
}

export function ToolResultTurn({ text, isError = false }: { text: string; isError?: boolean }) {
  return (
    <CollapsibleCard
      variant={isError ? "tr-card--error" : "tr-card--tool"}
      head={
        <span className="hint" style={isError ? { color: "#e5484d" } : undefined}>
          {isError ? "tool error" : "result"} · {text.length.toLocaleString()} chars · {text.replace(/\s+/g, " ").slice(0, 90)}
        </span>
      }
    >
      <pre className="ev-raw">{text.slice(0, 20000)}</pre>
    </CollapsibleCard>
  );
}

export function ResultFooter({ durationMs, turns, costUsd }: { durationMs: number; turns: number; costUsd: number }) {
  return (
    <div className="tr-footer">
      <span>done</span>
      <span><b>{(durationMs / 1000).toFixed(1)}s</b></span>
      <span><b>{turns}</b> turns</span>
      <span><b>${costUsd.toFixed(3)}</b></span>
    </div>
  );
}

/** Fallback for message/event types nothing else claims. */
export function UnknownTurn({ label, payload }: { label: string; payload: unknown }) {
  const text = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  if (!text || text === "{}" || text === "null") return null;
  return (
    <CollapsibleCard
      variant="tr-card--meta"
      head={<span className="hint">{label} · {text.replace(/\s+/g, " ").slice(0, 100)}</span>}
    >
      <pre className="ev-raw">{text.slice(0, 20000)}</pre>
    </CollapsibleCard>
  );
}
