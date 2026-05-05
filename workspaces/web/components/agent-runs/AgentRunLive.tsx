"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentRunV1 } from "@/lib/agent-runs/types";
import { STATUS_LABEL } from "@/components/agent-runs/_status-label";
import { StatusPill, statusToneFor } from "@/components/ui/StatusPill";
import { TimeAgo } from "@/components/ui/TimeAgo";
import { FieldRow } from "@/components/ui/FieldRow";
import Link from "next/link";

interface LogEntry {
  type: "text" | "thinking" | "tool" | "system" | "rate_limit";
  content: string;
}

export function AgentRunLive({ run }: { run: AgentRunV1 }) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState(run.status);
  const [resultSummary, setResultSummary] = useState(run.summary ?? "");
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status !== "running" || !run.sessionId) return;

    const url = `/api/agent-runs/${run.id}/events`;
    const es = new EventSource(url);
    let closed = false;

    es.addEventListener("assistant_message", (e) => {
      try {
        const data = JSON.parse(e.data);
        for (const block of data.content ?? []) {
          if (block.type === "text" && block.text) {
            setEntries((prev) => [...prev, { type: "text", content: block.text }]);
          } else if (block.type === "thinking" && block.thinking) {
            setEntries((prev) => [
              ...prev,
              { type: "thinking", content: block.thinking.slice(0, 300) },
            ]);
          } else if (block.type === "tool_use") {
            const name = block.name ?? "?";
            let inp = JSON.stringify(block.input ?? {});
            if (inp.length > 200) inp = inp.slice(0, 200) + "...";
            setEntries((prev) => [
              ...prev,
              { type: "tool", content: `${name}(${inp})` },
            ]);
          }
        }
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener("result", (e) => {
      try {
        const data = JSON.parse(e.data);
        const cost = data.total_cost_usd?.toFixed(4) ?? "?";
        const turns = data.num_turns ?? "?";
        const summary = `Cost: $${cost} | Turns: ${turns}`;
        setResultSummary(summary);
        setStatus("succeeded");
        setEntries((prev) => [
          ...prev,
          { type: "system", content: `Session complete. ${summary}` },
        ]);
      } catch { /* ignore */ }
    });

    es.addEventListener("rate_limit", (e) => {
      try {
        const data = JSON.parse(e.data);
        setEntries((prev) => [
          ...prev,
          { type: "rate_limit", content: `Rate limit: ${data.status}` },
        ]);
      } catch { /* ignore */ }
    });

    es.addEventListener("session_end", () => {
      setStatus((prev) => (prev === "running" ? "succeeded" : prev));
      closed = true;
      es.close();
    });

    es.addEventListener("session_error", (e) => {
      setStatus("failed");
      try {
        const data = JSON.parse(e.data);
        setEntries((prev) => [
          ...prev,
          { type: "system", content: `Error: ${data.error ?? "unknown"}` },
        ]);
      } catch { /* ignore */ }
      closed = true;
      es.close();
    });

    es.onerror = () => {
      if (closed) return;
      setEntries((prev) => [
        ...prev,
        { type: "system", content: "Connection lost. Reconnecting..." },
      ]);
    };

    return () => {
      closed = true;
      es.close();
    };
    // Only re-run if the run identity changes, not on status changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, run.sessionId]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [entries]);

  const heading = run.prompt.split("\n")[0];

  return (
    <article className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6">
      <Link
        href="/agent-runs"
        className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider uppercase mb-3 inline-flex items-center gap-1 transition-colors"
      >
        &larr; agent runs
      </Link>

      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-light tracking-wide text-[var(--color-text)] line-clamp-1 flex-1 min-w-0">
          {heading}
        </h1>
        <StatusPill tone={statusToneFor(status)}>
          {STATUS_LABEL[status]}
        </StatusPill>
      </div>

      <dl className="flex flex-col mb-6">
        <FieldRow label="Created" first>
          <span className="text-[var(--color-text-dim)]">
            <TimeAgo timestamp={run.createdAt} />
          </span>
        </FieldRow>
        <FieldRow label="Prompt">
          <pre className="whitespace-pre-wrap font-mono text-[13px] text-[var(--color-text)] bg-[var(--color-bg)] border border-[var(--color-border)] p-3">
            {run.prompt}
          </pre>
        </FieldRow>
        {resultSummary && (
          <FieldRow label="Result">
            <span className="text-[var(--color-text)]">{resultSummary}</span>
          </FieldRow>
        )}
      </dl>

      <div className="border border-[var(--color-border)]">
        <div className="flex items-center justify-between px-4 py-2 bg-[var(--color-bg)] border-b border-[var(--color-border)]">
          <span className="text-[11px] tracking-wider uppercase text-[var(--color-text-dim)]">
            agent output
          </span>
          {status === "running" && (
            <span className="text-[11px] text-[var(--color-text-dim)] animate-pulse">
              streaming...
            </span>
          )}
        </div>
        <div
          ref={logRef}
          className="h-[500px] overflow-y-auto p-4 font-mono text-[12px] leading-relaxed bg-[var(--color-bg)]"
        >
          {entries.length === 0 && status === "running" && (
            <p className="text-[var(--color-text-dim)]">Waiting for agent output...</p>
          )}
          {entries.map((entry, i) => (
            <div key={i} className={entryClass(entry.type)}>
              {entry.type === "thinking" && (
                <span className="text-[var(--color-text-dim)]">[thinking] </span>
              )}
              {entry.type === "tool" && (
                <span className="text-[var(--color-accent,#6e9eff)]">[tool] </span>
              )}
              {entry.type === "system" && (
                <span className="text-[var(--color-text-dim)]">[system] </span>
              )}
              {entry.type === "rate_limit" && (
                <span className="text-[var(--color-text-dim)]">[rate] </span>
              )}
              <span className="whitespace-pre-wrap">{entry.content}</span>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function entryClass(type: LogEntry["type"]): string {
  const base = "py-0.5";
  switch (type) {
    case "thinking":
      return `${base} text-[var(--color-text-dim)] italic`;
    case "tool":
      return `${base} text-[var(--color-accent,#6e9eff)]`;
    case "system":
      return `${base} text-[var(--color-text-muted)] font-bold`;
    case "rate_limit":
      return `${base} text-[var(--color-text-dim)]`;
    default:
      return `${base} text-[var(--color-text)]`;
  }
}
