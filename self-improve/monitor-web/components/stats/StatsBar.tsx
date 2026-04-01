"use client";

import { motion } from "framer-motion";
import type { Run } from "@/lib/types";

function formatTokens(n: number | null): string {
  if (!n) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.floor(n / 1_000)}k`;
  return n.toString();
}

function Stat({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[#444]">{icon}</span>
      <span className="text-[9px] text-[#444]">{label}</span>
      <span className={`text-[9px] font-semibold tabular-nums ${accent || "text-[#e8e8e8]"}`}>
        {value}
      </span>
    </div>
  );
}

export function StatsBar({
  run,
  connected,
}: {
  run: Run | null;
  connected: boolean;
}) {
  if (!run) {
    return (
      <div className="h-8 flex items-center px-4 border-t border-[#1a1a1a] bg-[#050505]">
        <span className="text-[9px] text-[#444]">No run selected</span>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="h-8 flex items-center gap-5 px-4 border-t border-[#1a1a1a] bg-[#050505]"
    >
      <Stat
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M6.5 1L9 3.5 3.5 9H1V6.5L6.5 1z" />
          </svg>
        }
        label="Tools"
        value={String(run.total_tool_calls || 0)}
      />
      <Stat
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="5" cy="5" r="4" />
            <path d="M3.5 5h3M5 3.5v3" />
          </svg>
        }
        label="Cost"
        value={`$${(run.total_cost_usd || 0).toFixed(2)}`}
        accent="text-[#00ff88]"
      />
      <Stat
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M1 5h3l1.5-3 2 6L9 5" />
          </svg>
        }
        label="In/Out"
        value={`${formatTokens(run.total_input_tokens)} / ${formatTokens(run.total_output_tokens)}`}
      />
      {run.pr_url && (
        <a
          href={run.pr_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[9px] text-[#88ccff] hover:text-[#aaddff] transition-colors"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="3" cy="3" r="1.5" />
            <circle cx="7" cy="3" r="1.5" />
            <circle cx="3" cy="7" r="1.5" />
            <line x1="3" y1="4.5" x2="3" y2="5.5" />
            <path d="M7 4.5c0 1.5-1.5 2-4 3" />
          </svg>
          PR #{run.pr_url.split("/").pop()}
        </a>
      )}

      <div className="flex-1" />

      <div className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            connected ? "bg-[#00ff88]" : "bg-[#444]"
          }`}
          style={connected ? { boxShadow: "0 0 4px rgba(0, 255, 136, 0.4)" } : undefined}
        />
        <span className="text-[8px] text-[#555]">
          {connected ? "Live" : "Disconnected"}
        </span>
      </div>
    </motion.div>
  );
}
