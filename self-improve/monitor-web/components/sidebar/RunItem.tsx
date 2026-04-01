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

export function RunItem({
  run,
  active,
  onClick,
}: {
  run: Run;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <motion.button
      layout
      onClick={onClick}
      className={clsx(
        "group relative w-full text-left px-4 py-3 border-b border-white/[0.04] transition-colors",
        active
          ? "bg-sky-500/[0.08]"
          : "hover:bg-white/[0.03]"
      )}
    >
      {active && (
        <motion.div
          layoutId="sidebar-indicator"
          className="absolute left-0 top-0 bottom-0 w-[3px] bg-sky-400 rounded-r"
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
        />
      )}

      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[11px] font-semibold text-sky-400 truncate flex-1">
          {run.branch_name}
        </span>
        <StatusBadge status={run.status} />
      </div>

      <div className="flex items-center gap-3 text-[10px] text-zinc-500">
        <span>{timeAgo(run.started_at)}</span>
        {run.total_tool_calls > 0 && (
          <span>{run.total_tool_calls} tools</span>
        )}
        {formatCost(run.total_cost_usd) && (
          <span className="text-emerald-500/70">
            {formatCost(run.total_cost_usd)}
          </span>
        )}
      </div>
    </motion.button>
  );
}
