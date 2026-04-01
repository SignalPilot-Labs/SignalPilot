"use client";

import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { clsx } from "clsx";
import type { FeedEvent } from "@/lib/types";
import { groupEvents } from "@/lib/groupEvents";
import { GroupedEventCard } from "./GroupedEventCard";
import { EmptyEvents } from "@/components/ui/EmptyStates";

export function EventFeed({ events }: { events: FeedEvent[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [userScrolled, setUserScrolled] = useState(false);

  const grouped = useMemo(() => groupEvents(events), [events]);

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
          <span className="text-[9px] text-[#555]">Events</span>
          <span className="text-[10px] text-[#e8e8e8] font-semibold tabular-nums">{events.length}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] text-[#555]">Tools</span>
          <span className="text-[10px] text-[#e8e8e8] font-semibold tabular-nums">{toolCount}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] text-[#555]">Groups</span>
          <span className="text-[10px] text-[#e8e8e8] font-semibold tabular-nums">{grouped.length}</span>
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
