"use client";

import { motion } from "framer-motion";
import type { Run } from "@/lib/types";
import {
  CurrencyDollarIcon,
  WrenchScrewdriverIcon,
  ArrowsRightLeftIcon,
  LinkIcon,
  SignalIcon,
} from "@heroicons/react/16/solid";

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
      <span className="text-zinc-600">{icon}</span>
      <span className="text-[10px] text-zinc-600">{label}</span>
      <span className={`text-[10px] font-semibold tabular-nums ${accent || "text-zinc-300"}`}>
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
      <div className="h-9 flex items-center px-4 border-t border-white/[0.04] bg-[#0a0d12]">
        <span className="text-[10px] text-zinc-600">No run selected</span>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="h-9 flex items-center gap-5 px-4 border-t border-white/[0.04] bg-[#0a0d12]"
    >
      <Stat
        icon={<WrenchScrewdriverIcon className="h-3 w-3" />}
        label="Tools"
        value={String(run.total_tool_calls || 0)}
      />
      <Stat
        icon={<CurrencyDollarIcon className="h-3 w-3" />}
        label="Cost"
        value={`$${(run.total_cost_usd || 0).toFixed(2)}`}
        accent="text-emerald-400"
      />
      <Stat
        icon={<ArrowsRightLeftIcon className="h-3 w-3" />}
        label="In/Out"
        value={`${formatTokens(run.total_input_tokens)} / ${formatTokens(run.total_output_tokens)}`}
      />
      {run.pr_url && (
        <a
          href={run.pr_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors"
        >
          <LinkIcon className="h-3 w-3" />
          PR #{run.pr_url.split("/").pop()}
        </a>
      )}

      <div className="flex-1" />

      <div className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            connected ? "bg-emerald-400" : "bg-zinc-600"
          }`}
        />
        <span className="text-[9px] text-zinc-600">
          {connected ? "Live" : "Disconnected"}
        </span>
      </div>
    </motion.div>
  );
}
