"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { clsx } from "clsx";
import type { FeedEvent } from "@/lib/types";
import { EventCard } from "./EventCard";
import { LLMTextBlock, LLMThinkingBlock } from "./LLMOutput";
import {
  ArrowDownIcon,
  ArrowsPointingOutIcon,
} from "@heroicons/react/16/solid";

export function EventFeed({ events }: { events: FeedEvent[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [userScrolled, setUserScrolled] = useState(false);

  // Auto-scroll on new events
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  // Detect user scroll
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
  const deniedCount = events.filter(
    (e) => e._kind === "tool" && !e.data.permitted
  ).length;

  return (
    <div className="flex-1 flex flex-col min-h-0 relative">
      {/* Mini toolbar */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-white/[0.04] bg-[#0a0d12]/80 backdrop-blur-sm">
        <span className="text-[10px] text-zinc-500">
          Events{" "}
          <span className="text-zinc-300 font-semibold tabular-nums">
            {events.length}
          </span>
        </span>
        <span className="text-[10px] text-zinc-500">
          Tools{" "}
          <span className="text-zinc-300 font-semibold tabular-nums">
            {toolCount}
          </span>
        </span>
        {deniedCount > 0 && (
          <span className="text-[10px] text-zinc-500">
            Denied{" "}
            <span className="text-red-400 font-semibold tabular-nums">
              {deniedCount}
            </span>
          </span>
        )}
      </div>

      {/* Event list */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-2 py-1 space-y-[2px] scrollbar-thin"
      >
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full text-zinc-600 text-xs">
            <div className="text-center space-y-2">
              <ArrowsPointingOutIcon className="h-6 w-6 mx-auto text-zinc-700" />
              <p>Waiting for events&hellip;</p>
            </div>
          </div>
        ) : (
          events.map((event, i) => {
            if (event._kind === "llm_text") {
              return <LLMTextBlock key={`text-${i}`} text={event.text} />;
            }
            if (event._kind === "llm_thinking") {
              return (
                <LLMThinkingBlock key={`think-${i}`} text={event.text} />
              );
            }
            return <EventCard key={`ev-${i}`} event={event} />;
          })
        )}
      </div>

      {/* Scroll-to-bottom FAB */}
      {userScrolled && (
        <button
          onClick={scrollToBottom}
          className={clsx(
            "absolute bottom-4 right-4 z-10",
            "flex items-center gap-1.5 px-3 py-1.5 rounded-full",
            "bg-sky-500/20 text-sky-400 text-[10px] font-medium",
            "border border-sky-500/30 backdrop-blur-sm",
            "hover:bg-sky-500/30 transition-all shadow-lg shadow-sky-500/10"
          )}
        >
          <ArrowDownIcon className="h-3 w-3" />
          New events
        </button>
      )}
    </div>
  );
}
