"use client";

import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { clsx } from "clsx";
import type { FeedEvent } from "@/lib/types";
import { getToolCategory } from "@/lib/types";
import { groupEvents } from "@/lib/groupEvents";
import { GroupedEventCard } from "./GroupedEventCard";
import { getToolIcon } from "@/components/ui/ToolIcons";
import { EmptyEvents } from "@/components/ui/EmptyStates";

type ActivityState =
  | { kind: "idle" }
  | { kind: "thinking"; text: string }
  | { kind: "writing"; text: string }
  | { kind: "calling_tool"; toolName: string; detail: string }
  | { kind: "waiting_tool"; toolName: string; detail: string };

const TERMINAL_EVENTS = new Set([
  "session_ended", "pr_created", "pr_failed", "killed",
  "fatal_error", "agent_stop", "stop_requested",
]);

function deriveActivity(events: FeedEvent[]): ActivityState {
  // Walk backwards through recent events to find current state
  for (let i = events.length - 1; i >= Math.max(0, events.length - 20); i--) {
    const ev = events[i];

    // Terminal audit events = run is done, no activity
    if (ev._kind === "audit" && TERMINAL_EVENTS.has(ev.data.event_type)) {
      return { kind: "idle" };
    }

    // A tool pre without a matching post = currently executing
    if (ev._kind === "tool" && ev.data.phase === "pre" && !ev.data.output_data) {
      const inp = ev.data.input_data || {};
      const fp = (inp.file_path as string) || "";
      const cmd = (inp.command as string) || "";
      const desc = (inp.description as string) || "";
      const detail = fp ? fp.split("/").pop() || fp : cmd ? cmd.slice(0, 50) : desc ? desc.slice(0, 50) : "";
      return { kind: "waiting_tool", toolName: ev.data.tool_name, detail };
    }

    // LLM thinking = agent is reasoning
    if (ev._kind === "llm_thinking") {
      return { kind: "thinking", text: ev.text.slice(-80) };
    }

    // LLM text = agent is writing output
    if (ev._kind === "llm_text") {
      return { kind: "writing", text: ev.text.slice(-80) };
    }

    // A completed tool = briefly show before next action
    if (ev._kind === "tool" && ev.data.phase === "post") {
      break; // Agent will start generating next
    }
  }
  return { kind: "idle" };
}

function ActivityIndicator({ activity }: { activity: ActivityState }) {
  if (activity.kind === "idle") return null;

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={activity.kind + (activity.kind === "waiting_tool" ? activity.toolName : "")}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.15 }}
        className="flex items-center gap-2 px-4 py-2 border-t border-[#1a1a1a] bg-[#0a0a0a]/80"
      >
        {/* Animated dots */}
        <span className="flex items-center gap-[3px] shrink-0">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className={clsx(
                "h-1 w-1 rounded-full",
                activity.kind === "thinking" ? "bg-[#cc88ff]" :
                activity.kind === "writing" ? "bg-[#88ccff]" :
                "bg-[#ffaa44]"
              )}
              style={{
                animation: "activity-dot 1.2s ease-in-out infinite",
                animationDelay: `${i * 0.2}s`,
              }}
            />
          ))}
        </span>
        <style>{`@keyframes activity-dot { 0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); } 40% { opacity: 1; transform: scale(1.2); } }`}</style>

        {activity.kind === "thinking" && (
          <span className="text-[10px] text-[#cc88ff]/80 flex items-center gap-1.5">
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#cc88ff" strokeWidth="1.2" className="shrink-0 opacity-60">
              <circle cx="5" cy="5" r="4" strokeDasharray="8 6" className="animate-spin" style={{ animationDuration: "3s" }} />
            </svg>
            Thinking...
          </span>
        )}

        {activity.kind === "writing" && (
          <span className="text-[10px] text-[#88ccff]/80 flex items-center gap-1.5">
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#88ccff" strokeWidth="1.2" className="shrink-0 opacity-60">
              <path d="M2 3h6M2 5h4M2 7h5" />
            </svg>
            Generating response...
            <span className="text-[#88ccff]/40 truncate max-w-[200px]">{activity.text}</span>
          </span>
        )}

        {(activity.kind === "calling_tool" || activity.kind === "waiting_tool") && (
          <span className="text-[10px] text-[#ffaa44]/80 flex items-center gap-1.5">
            <span className="opacity-60 shrink-0">{getToolIcon(getToolCategory(activity.toolName), "#ffaa44")}</span>
            <span className="font-medium">{activity.toolName}</span>
            {activity.detail && <span className="text-[#ffaa44]/40 truncate max-w-[200px]">{activity.detail}</span>}
          </span>
        )}
      </motion.div>
    </AnimatePresence>
  );
}

export function EventFeed({ events }: { events: FeedEvent[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [userScrolled, setUserScrolled] = useState(false);

  const grouped = useMemo(() => groupEvents(events), [events]);
  const activity = useMemo(() => deriveActivity(events), [events]);

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [grouped, autoScroll]);

  const handleScroll = useCallback(() => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 60;
    setAutoScroll(isAtBottom);
    setUserScrolled(!isAtBottom);
  }, []);

  const scrollToBottom = useCallback(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
      setAutoScroll(true);
      setUserScrolled(false);
    }
  }, []);

  const toolCount = events.filter(
    (e) => e._kind === "tool" && e.data.phase === "pre"
  ).length;

  return (
    <div className="flex-1 flex flex-col min-h-0 relative">
      {/* Mini toolbar */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-[#1a1a1a] bg-[#0a0a0a]/80 frosted-glass">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-[#888]">Events</span>
          <span className="text-[11px] text-[#e8e8e8] font-semibold tabular-nums">{events.length}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-[#888]">Tools</span>
          <span className="text-[11px] text-[#e8e8e8] font-semibold tabular-nums">{toolCount}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-[#888]">Groups</span>
          <span className="text-[11px] text-[#e8e8e8] font-semibold tabular-nums">{grouped.length}</span>
        </div>
      </div>

      {/* Event list */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 space-y-2"
      >
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <EmptyEvents />
          </div>
        ) : (
          grouped.map((gev, i) => (
            <GroupedEventCard key={`g-${i}`} event={gev} isLast={i === grouped.length - 1} />
          ))
        )}
      </div>

      {/* Live activity indicator */}
      <ActivityIndicator activity={activity} />

      {/* Scroll-to-bottom FAB */}
      {userScrolled && (
        <button
          onClick={scrollToBottom}
          className={clsx(
            "absolute bottom-4 right-4 z-10",
            "flex items-center gap-1.5 px-3 py-1.5 rounded",
            "bg-[#00ff88]/10 text-[#00ff88] text-[9px] font-medium",
            "border border-[#00ff88]/20 frosted-glass",
            "hover:bg-[#00ff88]/20 transition-all"
          )}
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <line x1="5" y1="2" x2="5" y2="8" />
            <polyline points="3 6 5 8 7 6" />
          </svg>
          New events
        </button>
      )}
    </div>
  );
}
