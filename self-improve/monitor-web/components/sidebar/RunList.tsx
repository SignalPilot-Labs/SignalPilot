"use client";

import { AnimatePresence } from "framer-motion";
import type { Run } from "@/lib/types";
import { RunItem } from "./RunItem";

export function RunList({
  runs,
  activeId,
  onSelect,
  loading,
}: {
  runs: Run[];
  activeId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
}) {
  return (
    <aside className="w-[280px] flex-shrink-0 flex flex-col border-r border-white/[0.06] bg-[#0c0f14]">
      <div className="px-4 py-3 border-b border-white/[0.06]">
        <h2 className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">
          Runs
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && runs.length === 0 ? (
          <div className="p-6 text-center">
            <div className="inline-flex h-5 w-5 animate-spin rounded-full border-2 border-zinc-600 border-t-sky-400" />
          </div>
        ) : runs.length === 0 ? (
          <div className="p-6 text-center text-xs text-zinc-600">
            No runs yet
          </div>
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
