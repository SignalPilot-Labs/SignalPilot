"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/Button";

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "Ready to resume";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function RateLimitBanner({
  resetsAt,
  onResume,
  busy,
}: {
  resetsAt: number;
  onResume: () => void;
  busy: boolean;
}) {
  const [remaining, setRemaining] = useState(() =>
    Math.max(0, resetsAt - Date.now() / 1000)
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setRemaining(Math.max(0, resetsAt - Date.now() / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [resetsAt]);

  const isReady = remaining <= 0;

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      className={`px-4 py-2.5 border-b ${
        isReady
          ? "bg-[#00ff88]/[0.04] border-[#00ff88]/15"
          : "bg-[#ffaa00]/[0.04] border-[#ffaa00]/15"
      }`}
    >
      <div className="flex items-center gap-3">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={isReady ? "#00ff88" : "#ffaa00"} strokeWidth="1.5" strokeLinecap="round" className="shrink-0">
          <circle cx="7" cy="7" r="5.5" />
          <line x1="7" y1="3.5" x2="7" y2="7" />
          <line x1="7" y1="7" x2="9.5" y2="9" />
        </svg>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-[10px] font-semibold ${isReady ? "text-[#00ff88]" : "text-[#ffaa00]"}`}>
              {isReady ? "Rate limit cleared" : "Rate limited"}
            </span>
            <span className={`text-[11px] font-bold tabular-nums ${isReady ? "text-[#00ff88]" : "text-[#ffaa00]"}`}>
              {formatCountdown(remaining)}
            </span>
          </div>

          {!isReady && (
            <div className="mt-1.5 h-[2px] bg-white/[0.04] rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-[#ffaa00]/40 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${100 - (remaining / 3600) * 100}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
          )}
        </div>

        <Button
          variant={isReady ? "success" : "warning"}
          size="sm"
          disabled={busy}
          onClick={onResume}
          icon={
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M1 5a4 4 0 017-2" />
              <polyline points="6 1 8 3 6 5" />
            </svg>
          }
        >
          {isReady ? "Resume Now" : "Force Resume"}
        </Button>
      </div>
    </motion.div>
  );
}
