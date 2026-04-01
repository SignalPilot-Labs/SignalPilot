"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { FeedEvent, ToolCall, AuditEvent, UsageEvent } from "@/lib/types";
import { createSSE } from "@/lib/api";

export function useSSE(runId: string | null) {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const clearEvents = useCallback(() => setEvents([]), []);

  useEffect(() => {
    if (!runId) return;

    setEvents([]);
    setConnected(false);

    const es = createSSE(runId);
    esRef.current = es;

    es.addEventListener("connected", () => setConnected(true));

    es.addEventListener("tool_call", (e) => {
      try {
        const data: ToolCall = JSON.parse(e.data);
        if (data.phase === "post") {
          // Merge post into the matching pre event
          setEvents((prev) => {
            for (let i = prev.length - 1; i >= 0; i--) {
              const ev = prev[i];
              if (ev._kind !== "tool" || ev.data.phase !== "pre" || ev.data.output_data) continue;

              // Match by tool_use_id (exact) or fall back to tool_name
              const idMatch = data.tool_use_id && ev.data.tool_use_id === data.tool_use_id;
              const nameMatch = !data.tool_use_id && ev.data.tool_name === data.tool_name;

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
            return [...prev, { _kind: "tool", data }];
          });
        } else {
          setEvents((prev) => [...prev, { _kind: "tool", data }]);
        }
      } catch {}
    });

    es.addEventListener("audit", (e) => {
      try {
        const raw: AuditEvent = JSON.parse(e.data);
        const details =
          typeof raw.details === "string"
            ? JSON.parse(raw.details)
            : raw.details || {};

        if (raw.event_type === "usage") {
          setEvents((prev) => [
            ...prev,
            {
              _kind: "usage",
              data: { ...details, ts: raw.ts } as UsageEvent,
            },
          ]);
        } else if (raw.event_type === "llm_text") {
          const role = details.agent_role || "worker";
          setEvents((prev) => {
            const last = prev[prev.length - 1];
            if (last && last._kind === "llm_text" && last.agent_role === role) {
              return [
                ...prev.slice(0, -1),
                { ...last, text: last.text + (details.text || "") },
              ];
            }
            return [
              ...prev,
              { _kind: "llm_text", text: details.text || "", ts: raw.ts, agent_role: role },
            ];
          });
        } else if (raw.event_type === "llm_thinking") {
          const role = details.agent_role || "worker";
          setEvents((prev) => {
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
          });
        } else {
          setEvents((prev) => [
            ...prev,
            { _kind: "audit", data: { ...raw, details } },
          ]);
        }
      } catch {}
    });

    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [runId]);

  return { events, connected, clearEvents };
}
