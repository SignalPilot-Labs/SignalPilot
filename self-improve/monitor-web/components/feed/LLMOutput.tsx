"use client";

import { motion } from "framer-motion";
import { clsx } from "clsx";
import {
  SparklesIcon,
  LightBulbIcon,
} from "@heroicons/react/16/solid";

export function LLMTextBlock({ text }: { text: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="relative border-l-[3px] border-l-zinc-500/40 rounded-r-md px-3 py-2 bg-white/[0.015]"
    >
      <div className="flex items-start gap-2">
        <SparklesIcon className="h-3 w-3 text-zinc-500 mt-0.5 shrink-0" />
        <div className="text-[11px] text-zinc-300 leading-relaxed whitespace-pre-wrap break-words min-w-0">
          {text}
          <span className="inline-block w-[6px] h-[13px] bg-sky-400/60 ml-0.5 animate-pulse rounded-[1px]" />
        </div>
      </div>
    </motion.div>
  );
}

export function LLMThinkingBlock({ text }: { text: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="relative border-l-[3px] border-l-zinc-700/50 rounded-r-md px-3 py-2 bg-zinc-800/20"
    >
      <div className="flex items-start gap-2">
        <LightBulbIcon className="h-3 w-3 text-zinc-600 mt-0.5 shrink-0" />
        <div className="text-[10px] text-zinc-500 italic leading-relaxed whitespace-pre-wrap break-words min-w-0">
          {text}
          <span className="inline-block w-[5px] h-[11px] bg-zinc-500/40 ml-0.5 animate-pulse rounded-[1px]" />
        </div>
      </div>
    </motion.div>
  );
}
