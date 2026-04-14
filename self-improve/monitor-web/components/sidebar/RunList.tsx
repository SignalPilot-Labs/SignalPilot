"use client";

import { AnimatePresence } from "framer-motion";
import type { Run } from "@/lib/types";
import { RunItem } from "./RunItem";
import { EmptyRuns } from "@/components/ui/EmptyStates";

export function RunList({
  runs,
  activeId,
  onSelect,
  loading,
  mobile,
}: {
  runs: Run[];
  activeId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  mobile?: boolean;
}) {
  return (
    <aside className={mobile ? "flex-1 flex flex-col bg-[#030303]" : "w-[280px] flex-shrink-0 flex flex-col border-r border-[#1a1a1a] bg-[#030303]"}>
      <div className="px-4 py-3 border-b border-[#1a1a1a]">
        <div className="flex items-center gap-2">
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            stroke="#888"
            strokeWidth="1.5"
            strokeLinecap="round"
          >
            <rect x="1" y="1" width="10" height="10" rx="1.5" />
            <line x1="1" y1="4" x2="11" y2="4" />
            <line x1="1" y1="7" x2="11" y2="7" />
          </svg>
          <h2 className="text-[11px] font-bold uppercase tracking-[0.15em] text-[#999]">
            Runs
          </h2>
          <span className="text-[10px] text-[#666] tabular-nums ml-auto">
            {runs.length}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && runs.length === 0 ? (
          <div className="p-6 text-center">
            <div
              className="inline-flex h-5 w-5 rounded-full border-2 border-[#333] border-t-[#00ff88]"
              style={{ animation: "spin 1s linear infinite" }}
            />
          </div>
        ) : runs.length === 0 ? (
          <EmptyRuns />
        ) : (
          <AnimatePresence mode="popLayout">
            {runs.map((run) => (
              <RunItem
                key={run.id}
                run={run}
                active={run.id === activeId}
                onClick={() => onSelect(run.id)}
              />
            ))}
          </AnimatePresence>
        )}
      </div>
    </aside>
  );
}
