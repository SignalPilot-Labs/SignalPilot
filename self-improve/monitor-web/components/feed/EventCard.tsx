"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { clsx } from "clsx";
import type { FeedEvent, ToolCall, AuditEvent } from "@/lib/types";
import {
  ChevronRightIcon,
  ShieldExclamationIcon,
  CommandLineIcon,
  DocumentTextIcon,
  ClockIcon,
} from "@heroicons/react/16/solid";

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "\u2026" : s;
}

function ToolCallCard({ tc }: { tc: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const denied = !tc.permitted;

  const borderColor = denied
    ? "border-l-red-500"
    : tc.phase === "pre"
      ? "border-l-sky-500"
      : "border-l-emerald-500";

  const bgColor = denied
    ? "bg-red-500/[0.03]"
    : tc.phase === "pre"
      ? "bg-sky-500/[0.02]"
      : "bg-emerald-500/[0.02]";

  const inputStr = tc.input_data ? JSON.stringify(tc.input_data) : "";
  const outputStr = tc.output_data ? JSON.stringify(tc.output_data) : "";

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className={clsx(
        "group border-l-[3px] rounded-r-md px-3 py-1.5 cursor-pointer transition-colors",
        borderColor,
        bgColor,
        "hover:bg-white/[0.03]"
      )}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[10px] text-zinc-600 tabular-nums shrink-0">
          {formatTs(tc.ts)}
        </span>

        <span
          className={clsx(
            "text-[11px] font-semibold shrink-0",
            denied ? "text-red-400" : "text-sky-400"
          )}
        >
          {tc.tool_name}
        </span>

        <span className="text-[10px] text-zinc-600 shrink-0">
          {tc.phase}
        </span>

        {denied && (
          <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-red-400 bg-red-500/10 rounded px-1.5 py-0.5 shrink-0">
            <ShieldExclamationIcon className="h-3 w-3" />
            DENIED
          </span>
        )}

        {tc.duration_ms != null && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-400/70 shrink-0">
            <ClockIcon className="h-2.5 w-2.5" />
            {tc.duration_ms}ms
          </span>
        )}

        <span className="text-[10px] text-zinc-600 truncate min-w-0">
          {denied
            ? tc.deny_reason
            : truncate(inputStr, 120)}
        </span>

        <ChevronRightIcon
          className={clsx(
            "h-3 w-3 text-zinc-600 shrink-0 transition-transform duration-150",
            expanded && "rotate-90"
          )}
        />
      </div>

      {expanded && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          transition={{ duration: 0.2 }}
          className="mt-2 space-y-2"
        >
          {tc.input_data && (
            <div>
              <div className="text-[9px] uppercase tracking-wider text-zinc-600 mb-0.5">
                Input
              </div>
              <pre className="text-[10px] text-zinc-400 bg-black/30 rounded-md p-2 overflow-x-auto max-h-48 scrollbar-thin">
                {JSON.stringify(tc.input_data, null, 2)}
              </pre>
            </div>
          )}
          {tc.output_data && (
            <div>
              <div className="text-[9px] uppercase tracking-wider text-zinc-600 mb-0.5">
                Output
              </div>
              <pre className="text-[10px] text-zinc-400 bg-black/30 rounded-md p-2 overflow-x-auto max-h-48 scrollbar-thin">
                {JSON.stringify(tc.output_data, null, 2)}
              </pre>
            </div>
          )}
        </motion.div>
      )}
    </motion.div>
  );
}

function AuditCard({ event }: { event: AuditEvent }) {
  const [expanded, setExpanded] = useState(false);
  const detailStr = JSON.stringify(event.details);

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className="border-l-[3px] border-l-violet-500/60 bg-violet-500/[0.02] rounded-r-md px-3 py-1.5 cursor-pointer hover:bg-white/[0.03] transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[10px] text-zinc-600 tabular-nums shrink-0">
          {formatTs(event.ts)}
        </span>
        <span className="text-[11px] font-medium text-violet-400 shrink-0">
          {event.event_type}
        </span>
        <span className="text-[10px] text-zinc-600 truncate min-w-0">
          {truncate(detailStr, 150)}
        </span>
        <ChevronRightIcon
          className={clsx(
            "h-3 w-3 text-zinc-600 shrink-0 transition-transform duration-150",
            expanded && "rotate-90"
          )}
        />
      </div>

      {expanded && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          transition={{ duration: 0.2 }}
          className="mt-2"
        >
          <pre className="text-[10px] text-zinc-400 bg-black/30 rounded-md p-2 overflow-x-auto max-h-48 scrollbar-thin">
            {JSON.stringify(event.details, null, 2)}
          </pre>
        </motion.div>
      )}
    </motion.div>
  );
}

function ControlCard({ text, ts }: { text: string; ts: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      className="border-l-[3px] border-l-amber-500 bg-amber-500/[0.04] rounded-r-md px-3 py-1.5"
    >
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-zinc-600 tabular-nums">
          {formatTs(ts)}
        </span>
        <CommandLineIcon className="h-3 w-3 text-amber-400" />
        <span className="text-[11px] font-semibold text-amber-400">
          CONTROL
        </span>
        <span className="text-[10px] text-zinc-400">{text}</span>
      </div>
    </motion.div>
  );
}

export function EventCard({ event }: { event: FeedEvent }) {
  switch (event._kind) {
    case "tool":
      return <ToolCallCard tc={event.data} />;
    case "audit":
      return <AuditCard event={event.data} />;
    case "control":
      return <ControlCard text={event.text} ts={event.ts} />;
    case "llm_text":
    case "llm_thinking":
      return null; // Handled by LLMOutput
    default:
      return null;
  }
}
