"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTunnel } from "@/hooks/useTunnel";
import { Button } from "./Button";

export function TunnelPopover() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { status, url, loading, start, stop } = useTunnel();

  const isRunning = status === "running";
  const isStopped = status === "exited" || status === "not_found";

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleCopy = async () => {
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const statusColor = isRunning
    ? "bg-[#00ff88]"
    : isStopped
      ? "bg-[#ff4444]/60"
      : "bg-[#ffaa00]";

  const statusLabel = isRunning
    ? "Running"
    : status === "exited"
      ? "Stopped"
      : status === "not_found"
        ? "Not Found"
        : status === "restarting"
          ? "Restarting"
          : "Error";

  return (
    <div ref={ref} className="relative">
      {/* Trigger */}
      <button
        onClick={() => setOpen(!open)}
        className="relative p-1.5 rounded hover:bg-white/[0.04] text-[#888] hover:text-[#ccc] transition-colors"
        title="Mobile Access"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
          <line x1="12" y1="18" x2="12.01" y2="18" />
        </svg>
        {/* Active indicator dot */}
        {isRunning && (
          <span className="absolute top-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-[#00ff88]" />
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full right-0 mt-1 z-50 w-[280px] bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg shadow-xl shadow-black/50 overflow-hidden"
          >
            {/* Header */}
            <div className="px-3 py-2 border-b border-[#1a1a1a]">
              <span className="text-[9px] uppercase tracking-[0.1em] text-[#666] font-semibold">
                Mobile Access
              </span>
            </div>

            <div className="p-3 space-y-3">
              {/* Status */}
              <div className="flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
                <span className="text-[11px] text-[#ccc] font-medium">
                  {statusLabel}
                </span>
              </div>

              {/* URL */}
              {isRunning && url && (
                <div className="flex items-center gap-1.5">
                  <div className="flex-1 min-w-0 px-2 py-1.5 bg-white/[0.03] border border-[#1a1a1a] rounded text-[10px] text-[#88ccff] font-mono truncate">
                    {url}
                  </div>
                  <button
                    onClick={handleCopy}
                    className="shrink-0 p-1.5 rounded hover:bg-white/[0.04] text-[#888] hover:text-[#ccc] transition-colors"
                    title="Copy URL"
                  >
                    {copied ? (
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="#00ff88"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    ) : (
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <rect x="9" y="9" width="13" height="13" rx="2" />
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                      </svg>
                    )}
                  </button>
                </div>
              )}

              {isRunning && !url && (
                <p className="text-[10px] text-[#666]">
                  Waiting for tunnel URL...
                </p>
              )}

              {isRunning && url && (
                <p className="text-[10px] text-[#666] leading-relaxed">
                  Open this URL on your phone to access the monitor remotely.
                </p>
              )}

              {/* Toggle */}
              <Button
                variant={isRunning ? "danger" : "success"}
                size="sm"
                onClick={isRunning ? stop : start}
                disabled={loading}
                icon={
                  isRunning ? (
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      fill="currentColor"
                    >
                      <rect x="2" y="2" width="6" height="6" rx="1" />
                    </svg>
                  ) : (
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                    >
                      <polygon points="3 2 8 5 3 8" />
                    </svg>
                  )
                }
              >
                {loading
                  ? "..."
                  : isRunning
                    ? "Stop Tunnel"
                    : "Start Tunnel"}
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
