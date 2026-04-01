"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { FeedEvent, ToolCall, AuditEvent } from "@/lib/types";
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
        setEvents((prev) => [...prev, { _kind: "tool", data }]);
      } catch {}
    });

    es.addEventListener("audit", (e) => {
      try {
        const raw: AuditEvent = JSON.parse(e.data);
        const details =
          typeof raw.details === "string"
            ? JSON.parse(raw.details)
            : raw.details || {};

        if (raw.event_type === "llm_text") {
          setEvents((prev) => {
            const last = prev[prev.length - 1];
            if (last && last._kind === "llm_text") {
              return [
                ...prev.slice(0, -1),
                { ...last, text: last.text + (details.text || "") },
              ];
            }
            return [
              ...prev,
              { _kind: "llm_text", text: details.text || "", ts: raw.ts },
            ];
          });
        } else if (raw.event_type === "llm_thinking") {
          setEvents((prev) => {
            const last = prev[prev.length - 1];
            if (last && last._kind === "llm_thinking") {
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
