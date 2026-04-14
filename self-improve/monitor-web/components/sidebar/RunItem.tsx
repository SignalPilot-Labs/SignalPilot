"use client";

import { clsx } from "clsx";
import { motion } from "framer-motion";
import type { Run } from "@/lib/types";
import { StatusBadge } from "@/components/ui/Badge";

function timeAgo(date: string): string {
  const s = Math.floor((Date.now() - new Date(date).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function formatCost(usd: number | null): string {
  if (!usd) return "";
  return `$${usd.toFixed(2)}`;
}

function formatTokens(n: number | null): string {
  if (!n) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.floor(n / 1_000)}k`;
  return n.toString();
}

export function RunItem({
  run,
  active,
  onClick,
}: {
  run: Run;
  active: boolean;
  onClick: () => void;
}) {
  const branchShort = run.branch_name
    .replace("improvements-round-", "")
    .slice(0, 20);

  return (
    <motion.button
      layout
      onClick={onClick}
      className={clsx(
        "group relative w-full text-left px-4 py-3 sm:py-3 border-b border-[#1a1a1a]/60 transition-colors min-h-[56px] sm:min-h-0",
        active ? "bg-[#00ff88]/[0.04]" : "hover:bg-white/[0.02]",
      )}
    >
      {active && (
        <motion.div
          layoutId="sidebar-indicator"
          className="absolute left-0 top-0 bottom-0 w-[2px] bg-[#00ff88]"
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
        />
      )}

      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={clsx(
            "text-[12px] font-medium truncate flex-1",
            active ? "text-[#e8e8e8]" : "text-[#ccc]",
          )}
        >
          {branchShort}
        </span>
        <StatusBadge status={run.status} />
      </div>

      <div className="flex items-center gap-3 text-[10px] text-[#888]">
        <span className="tabular-nums">{timeAgo(run.started_at)}</span>
        {run.total_tool_calls > 0 && (
          <span className="flex items-center gap-0.5">
            <svg
              width="8"
              height="8"
              viewBox="0 0 8 8"
              fill="none"
              stroke="currentColor"
              strokeWidth="1"
            >
              <path d="M5.5 1L7 2.5 2.5 7H1V5.5L5.5 1z" />
            </svg>
            {run.total_tool_calls}
          </span>
        )}
        {formatCost(run.total_cost_usd) && (
          <span className="text-[#00ff88]/70 tabular-nums">
            {formatCost(run.total_cost_usd)}
          </span>
        )}
        {(run.total_input_tokens || 0) > 0 && (
          <span className="text-[#666] tabular-nums">
            {formatTokens(run.total_input_tokens)}↓
          </span>
        )}
      </div>

      {/* Error message preview */}
      {run.error_message && (
        <div className="mt-1 text-[9px] text-[#ff4444]/80 truncate">
          {run.error_message.slice(0, 80)}
        </div>
      )}
    </motion.button>
  );
}
