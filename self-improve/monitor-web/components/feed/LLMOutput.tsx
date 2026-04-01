"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { clsx } from "clsx";

export function LLMTextBlock({
  text,
  agentRole = "worker",
}: {
  text: string;
  agentRole?: "worker" | "ceo";
}) {
  const isCeo = agentRole === "ceo";
  const [collapsed, setCollapsed] = useState(false);
  const isLong = text.length > 2000;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className={clsx(
        "relative border-l-[3px] rounded-r px-3 py-2",
        isCeo
          ? "border-l-[#ff8844]/60 bg-[#ff8844]/[0.02]"
          : "border-l-[#555]/40 bg-white/[0.01]"
      )}
    >
      <div className="flex items-start gap-2">
        {/* Icon */}
        {isCeo ? (
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#ff8844" strokeWidth="1.5" className="mt-0.5 shrink-0 opacity-60">
            <path d="M2 9l2-4 2 2.5 2-3.5 2 5" />
            <rect x="1" y="9" width="10" height="1.5" rx="0.5" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#555" strokeWidth="1.5" className="mt-0.5 shrink-0 opacity-60">
            <path d="M6 1l1 3h3l-2.5 2 1 3L6 7.5 3.5 9l1-3L2 4h3L6 1z" />
          </svg>
        )}
        <div className="min-w-0 flex-1">
          {isCeo && (
            <span className="text-[8px] font-bold uppercase tracking-[0.12em] text-[#ff8844] bg-[#ff8844]/10 rounded px-1 py-0.5 mr-1">
              CEO
            </span>
          )}

          {/* Collapsible toggle for long content */}
          {isLong && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="text-[8px] text-[#555] hover:text-[#888] ml-1 transition-colors"
            >
              [{collapsed ? "expand" : "collapse"}]
            </button>
          )}

          <AnimatePresence mode="wait">
            {!collapsed ? (
              <motion.span
                key="full"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className={clsx(
                  "text-[11px] leading-relaxed whitespace-pre-wrap break-words block",
                  isCeo ? "text-[#cc8855]" : "text-[#bbb]"
                )}
              >
                {text}
              </motion.span>
            ) : (
              <motion.span
                key="collapsed"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-[11px] text-[#666] block"
              >
                {text.slice(0, 200)}… <span className="text-[9px] text-[#555]">({text.length} chars)</span>
              </motion.span>
            )}
          </AnimatePresence>

          {/* Typing cursor */}
          <span
            className={clsx(
              "inline-block w-[5px] h-[12px] ml-0.5 rounded-[1px]",
              isCeo ? "bg-[#ff8844]/40" : "bg-[#00ff88]/30",
            )}
            style={{ animation: "blink 1s step-end infinite" }}
          />
        </div>
      </div>
    </motion.div>
  );
}

export function LLMThinkingBlock({
  text,
  agentRole = "worker",
}: {
  text: string;
  agentRole?: "worker" | "ceo";
}) {
  const isCeo = agentRole === "ceo";
  const [collapsed, setCollapsed] = useState(false);
  const isLong = text.length > 1000;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className={clsx(
        "relative border-l-[3px] rounded-r px-3 py-2",
        isCeo
          ? "border-l-[#ff8844]/30 bg-[#ff8844]/[0.01]"
          : "border-l-[#333]/50 bg-[#111]/30"
      )}
    >
      <div className="flex items-start gap-2">
        {/* Lightbulb icon */}
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke={isCeo ? "#774422" : "#444"} strokeWidth="1.5" className="mt-0.5 shrink-0 opacity-60">
          <path d="M4 9h4M4.5 9c0 1 .5 2 1.5 2s1.5-1 1.5-2M6 1a3.5 3.5 0 00-2 6.3V9h4V7.3A3.5 3.5 0 006 1z" />
        </svg>
        <div className="min-w-0 flex-1">
          {isCeo && (
            <span className="text-[7px] font-bold uppercase tracking-[0.12em] text-[#774422] mr-1">
              CEO thinking
            </span>
          )}

          {isLong && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="text-[8px] text-[#444] hover:text-[#666] ml-1 transition-colors"
            >
              [{collapsed ? "expand" : "collapse"}]
            </button>
          )}

          <AnimatePresence mode="wait">
            {!collapsed ? (
              <motion.span
                key="full"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className={clsx(
                  "text-[10px] italic leading-relaxed whitespace-pre-wrap break-words block opacity-60",
                  isCeo ? "text-[#885533]" : "text-[#777]"
                )}
              >
                {text}
              </motion.span>
            ) : (
              <motion.span
                key="collapsed"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-[10px] italic text-[#555] block"
              >
                {text.slice(0, 150)}… <span className="text-[8px] not-italic text-[#444]">({text.length} chars)</span>
              </motion.span>
            )}
          </AnimatePresence>

          <span
            className={clsx(
              "inline-block w-[4px] h-[10px] ml-0.5 rounded-[1px]",
              isCeo ? "bg-[#885533]/30" : "bg-[#555]/30",
            )}
            style={{ animation: "blink 1s step-end infinite" }}
          />
        </div>
      </div>
    </motion.div>
  );
}
