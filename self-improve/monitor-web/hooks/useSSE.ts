"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { FeedEvent, ToolCall, AuditEvent, UsageEvent } from "@/lib/types";
import { createSSE, pollEvents } from "@/lib/api";

function processTool(prev: FeedEvent[], data: ToolCall): FeedEvent[] {
  if (data.phase === "post") {
    for (let i = prev.length - 1; i >= 0; i--) {
      const ev = prev[i];
      if (ev._kind !== "tool" || ev.data.phase !== "pre" || ev.data.output_data)
        continue;
      const idMatch =
        data.tool_use_id && ev.data.tool_use_id === data.tool_use_id;
      const nameMatch =
        !data.tool_use_id && ev.data.tool_name === data.tool_name;
      if (idMatch || nameMatch) {
        const merged = { ...ev.data };
        merged.output_data = data.output_data;
        merged.duration_ms = data.duration_ms;
        merged.phase = "post";
        const next = [...prev];
        next[i] = { _kind: "tool", data: merged };
        return next;
      }
    }
  }
  return [...prev, { _kind: "tool", data }];
}

function processAudit(prev: FeedEvent[], raw: AuditEvent): FeedEvent[] {
  const details =
    typeof raw.details === "string"
      ? JSON.parse(raw.details)
      : raw.details || {};

  if (raw.event_type === "usage") {
    return [
      ...prev,
      { _kind: "usage", data: { ...details, ts: raw.ts } as UsageEvent },
    ];
  }
  if (raw.event_type === "llm_text") {
    const role = details.agent_role || "worker";
    const last = prev[prev.length - 1];
    if (last && last._kind === "llm_text" && last.agent_role === role) {
      return [
        ...prev.slice(0, -1),
        { ...last, text: last.text + (details.text || "") },
      ];
    }
    return [
      ...prev,
      {
        _kind: "llm_text",
        text: details.text || "",
        ts: raw.ts,
        agent_role: role,
      },
    ];
  }
  if (raw.event_type === "llm_thinking") {
    const role = details.agent_role || "worker";
    const last = prev[prev.length - 1];
    if (last && last._kind === "llm_thinking" && last.agent_role === role) {
      return [
        ...prev.slice(0, -1),
        { ...last, text: last.text + (details.text || "") },
      ];
    }
    return [
      ...prev,
      {
        _kind: "llm_thinking",
        text: details.text || "",
        ts: raw.ts,
        agent_role: role,
      },
    ];
  }
  return [...prev, { _kind: "audit", data: { ...raw, details } }];
}

const SSE_FAIL_THRESHOLD = 3; // switch to polling after N consecutive errors
const POLL_INTERVAL = 1000; // ms

export function useSSE(runId: string | null) {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearEvents = useCallback(() => setEvents([]), []);

  useEffect(() => {
    if (!runId) return;

    setEvents([]);
    setConnected(false);

    let sseGotMessage = false;
    let afterTool = 0;
    let afterAudit = 0;

    // --- Polling fallback ---
    function startPolling() {
      if (pollingRef.current) return;
      setConnected(true);
      pollingRef.current = setInterval(async () => {
        try {
          const result = await pollEvents(runId!, afterTool, afterAudit);
          if (result.tool_calls.length > 0 || result.audit_events.length > 0) {
            setEvents((prev) => {
              let next = prev;
              for (const tc of result.tool_calls) {
                afterTool = Math.max(afterTool, tc.id ?? 0);
                next = processTool(next, tc);
              }
              for (const ae of result.audit_events) {
                afterAudit = Math.max(afterAudit, ae.id ?? 0);
                next = processAudit(next, ae);
              }
              return next;
            });
          }
        } catch {
          // ignore poll errors
        }
      }, POLL_INTERVAL);
    }

    function switchToPolling() {
      if (pollingRef.current) return;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      startPolling();
    }

    // --- SSE primary with timeout fallback ---
    const es = createSSE(runId);
    esRef.current = es;

    // If no SSE message within 3s, assume SSE is blocked and switch to polling
    const sseTimeout = setTimeout(() => {
      if (!sseGotMessage) switchToPolling();
    }, 3000);

    es.addEventListener("connected", () => {
      sseGotMessage = true;
      clearTimeout(sseTimeout);
      setConnected(true);
    });

    es.addEventListener("ping", () => {
      sseGotMessage = true;
    });

    es.addEventListener("tool_call", (e) => {
      sseGotMessage = true;
      try {
        const data: ToolCall = JSON.parse(e.data);
        setEvents((prev) => processTool(prev, data));
      } catch {}
    });

    es.addEventListener("audit", (e) => {
      sseGotMessage = true;
      try {
        const raw: AuditEvent = JSON.parse(e.data);
        setEvents((prev) => processAudit(prev, raw));
      } catch {}
    });

    es.onerror = () => {
      setConnected(false);
      if (!sseGotMessage) switchToPolling();
    };

    return () => {
      clearTimeout(sseTimeout);
      es.close();
      esRef.current = null;
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [runId]);

  return { events, connected, clearEvents };
}
