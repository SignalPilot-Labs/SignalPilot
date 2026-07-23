"use client";

/**
 * Chat reader (/chats) — a dedicated, full-page view for reading past agent
 * chats (chat-trace threads): roomy message layout, collapsible thinking and
 * tool calls, deep-linkable via ?thread=.
 */

import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { MessageSquare, Search, X } from "lucide-react";
import {
  getChatThreadEvents,
  listChatThreads,
  type ChatTraceEvent,
  type ChatTraceThread,
} from "~/lib/api";
import { PageHeader } from "~/components/ui/page-header";
import {
  AgentTurn,
  ThinkingTurn,
  ToolCallTurn,
  ToolResultTurn,
  UnknownTurn,
  UserTurn,
} from "../evals/_components/turns";
import "../evals/evals.css";

/* ─── helpers ───────────────────────────────────────────────────────────── */

function relTime(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function threadTitle(t: ChatTraceThread): string {
  return t.title || t.notebook_path.split(/[/\\]/).pop() || t.thread_id.slice(0, 18);
}

/* ─── thread list rail ──────────────────────────────────────────────────── */

function ThreadRow({ t, selected, onSelect }: { t: ChatTraceThread; selected: boolean; onSelect: () => void }) {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left px-3 py-2.5 border-b border-[var(--color-border)] hover:bg-[var(--color-bg)] transition-colors ${selected ? "bg-[var(--color-bg)] border-l-2 border-l-[var(--color-success)]" : ""}`}
    >
      <div className="text-sm text-[var(--color-text)] truncate">{threadTitle(t)}</div>
      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--color-text-dim)]">
        <span className="ev-badge">{t.source}</span>
        <span>{relTime(t.updated_at)}</span>
        {t.status !== "active" && <span>{t.status}</span>}
      </div>
    </button>
  );
}

/* ─── event rendering (shared turn components) ─────────────────────────── */

function EventView({ e }: { e: ChatTraceEvent }) {
  const isUser = e.type === "user" || e.role === "user";
  const isThinking = e.type === "thinking";
  const isToolResult = e.type === "tool_result";
  const isToolCall = !isToolResult && (e.type === "tool_call" || e.type === "tool_use" || !!e.tool_name);

  if (isUser) return <UserTurn text={e.content} />;
  if (isThinking) return <ThinkingTurn text={e.content} />;
  if (isToolCall) {
    return (
      <ToolCallTurn
        name={e.tool_name || e.type}
        input={e.tool_input}
        isError={e.is_error}
        resultText={e.content || undefined}
      />
    );
  }
  if (isToolResult) return <ToolResultTurn text={e.content} isError={e.is_error} />;
  if (e.type === "text" || e.role === "assistant") {
    if (!e.content.trim()) return null;
    return <AgentTurn text={e.content} costUsd={e.cost_usd} />;
  }
  return <UnknownTurn label={e.type} payload={e.content || e} />;
}

function ThreadReader({ thread }: { thread: ChatTraceThread }) {
  const { data, isLoading } = useSWR(`chat-events-${thread.thread_id}`, () => getChatThreadEvents(thread.thread_id));
  const events = data?.events ?? [];
  const totalCost = events.reduce((acc, e) => acc + (e.cost_usd ?? 0), 0);

  return (
    <div className="flex-1 min-w-0 flex flex-col">
      <div className="border-b border-[var(--color-border)] px-6 py-4">
        <h2 className="text-lg font-light text-[var(--color-text)]">{threadTitle(thread)}</h2>
        <div className="mt-1 flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
          <span className="ev-badge">{thread.source}</span>
          {thread.notebook_path && <code className="text-[var(--color-text-dim)]">{thread.notebook_path}</code>}
          <span>{events.length} events</span>
          {totalCost > 0 && <span>${totalCost.toFixed(3)}</span>}
          <span>{relTime(thread.updated_at)}</span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 max-w-3xl w-full mx-auto">
        {isLoading ? (
          <p className="text-sm text-[var(--color-text-dim)]">loading conversation…</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-[var(--color-text-dim)]">no events in this thread.</p>
        ) : (
          events.map((e) => <EventView key={e.idx} e={e} />)
        )}
      </div>
    </div>
  );
}

/* ─── page ──────────────────────────────────────────────────────────────── */

function ChatsPageInner() {
  const searchParams = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get("thread"));
  const [searchQ, setSearchQ] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  const { data } = useSWR("chat-threads", () => listChatThreads(), { refreshInterval: 30000 });
  const threads = data?.threads ?? [];
  const sources = useMemo(() => [...new Set(threads.map((t) => t.source))].sort(), [threads]);

  const filtered = threads
    .filter((t) => sourceFilter === "all" || t.source === sourceFilter)
    .filter((t) => !searchQ || threadTitle(t).toLowerCase().includes(searchQ.toLowerCase()))
    .sort((a, b) => b.updated_at - a.updated_at);

  const selected = threads.find((t) => t.thread_id === selectedId) ?? null;

  function select(id: string | null) {
    setSelectedId(id);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `/chats${id ? `?thread=${encodeURIComponent(id)}` : ""}`);
    }
  }

  return (
    <div className="h-screen flex flex-col p-8 overflow-hidden animate-fade-in">
      <PageHeader
        title="chats"
        subtitle="history"
        description="read past agent conversations — full transcripts, tool calls, costs"
      />

      <div className="flex flex-1 min-h-0 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {/* Rail */}
        <div className="w-80 flex-shrink-0 flex flex-col min-h-0 border-r border-[var(--color-border)]">
          <div className="p-3 border-b border-[var(--color-border)] space-y-2">
            <div className="flex items-center gap-2 border border-[var(--color-border)] px-2.5 py-1.5">
              <Search className="w-3.5 h-3.5 flex-shrink-0 text-[var(--color-text-dim)]" />
              <input
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                placeholder="Search chats…"
                className="w-full bg-transparent text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none"
              />
              {searchQ && (
                <button onClick={() => setSearchQ("")} aria-label="clear">
                  <X className="w-3 h-3 text-[var(--color-text-dim)]" />
                </button>
              )}
            </div>
            {sources.length > 1 && (
              <div className="flex gap-1.5 flex-wrap">
                {["all", ...sources].map((s) => (
                  <button
                    key={s}
                    onClick={() => setSourceFilter(s)}
                    className={`ev-badge ${sourceFilter === s ? "!text-[var(--color-text)] !border-[var(--color-border-hover)]" : ""}`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="p-4 text-sm text-[var(--color-text-dim)]">no chats yet.</p>
            ) : (
              filtered.map((t) => (
                <ThreadRow key={t.thread_id} t={t} selected={t.thread_id === selectedId} onSelect={() => select(t.thread_id)} />
              ))
            )}
          </div>
        </div>

        {/* Reader */}
        {selected ? (
          <ThreadReader thread={selected} />
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm text-[var(--color-text-dim)] flex items-center gap-2">
              <MessageSquare className="w-4 h-4" strokeWidth={1.5} />
              select a chat to read it
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatsPage() {
  return (
    <Suspense fallback={null}>
      <ChatsPageInner />
    </Suspense>
  );
}
