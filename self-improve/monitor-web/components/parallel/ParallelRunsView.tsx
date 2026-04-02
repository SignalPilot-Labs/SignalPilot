"use client";

import { useParallelRuns } from "@/hooks/useParallelRuns";
import { ParallelRunsPanel } from "@/components/parallel/ParallelRunsPanel";
import { Button } from "@/components/ui/Button";

export interface ParallelRunsViewProps {
  onStartNew: () => void;
  branches: string[];
  label?: string;
}

function GridIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect x="3" y="3" width="11" height="11" rx="2" stroke="#00ff88" strokeWidth="1.5" strokeOpacity="0.5" />
      <rect x="18" y="3" width="11" height="11" rx="2" stroke="#00ff88" strokeWidth="1.5" strokeOpacity="0.3" />
      <rect x="3" y="18" width="11" height="11" rx="2" stroke="#00ff88" strokeWidth="1.5" strokeOpacity="0.3" />
      <rect x="18" y="18" width="11" height="11" rx="2" stroke="#00ff88" strokeWidth="1.5" strokeOpacity="0.15" />
    </svg>
  );
}

export function ParallelRunsView({ onStartNew, branches, label = "Parallel Runners" }: ParallelRunsViewProps) {
  const { status } = useParallelRuns();
  const slots = status?.slots ?? [];
  const isEmpty = slots.length === 0;

  return (
    <div className="flex flex-col h-full bg-[#0a0a0a]">
      {/* Page header */}
      <div className="flex-none px-6 py-5 border-b border-[#1a1a1a]">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-[13px] font-semibold text-[#e8e8e8] tracking-tight">
              {label}
            </h2>
            <p className="text-[10px] text-[#888] mt-0.5">
              Manage concurrent agent runs in isolated containers
            </p>
          </div>
          {!isEmpty && (
            <Button variant="success" size="md" onClick={onStartNew}>
              + New Bot
            </Button>
          )}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto">
        {isEmpty ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center h-full gap-5 px-6">
            <GridIcon />
            <div className="text-center">
              <p className="text-[12px] font-medium text-[#e8e8e8]">No active bots</p>
              <p className="text-[10px] text-[#666] mt-1 max-w-[260px] leading-relaxed">
                Launch a bot to spin up an isolated agent container on a separate branch.
              </p>
            </div>
            <Button variant="success" size="md" onClick={onStartNew}>
              Launch Bot
            </Button>
          </div>
        ) : (
          /* Panel with runs */
          <div className="p-6">
            <div className="bg-[#0d0d0d] border border-[#1a1a1a] rounded-lg p-4">
              <ParallelRunsPanel onStartNew={onStartNew} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
