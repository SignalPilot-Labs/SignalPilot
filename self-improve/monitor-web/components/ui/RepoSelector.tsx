"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { RepoInfo } from "@/lib/types";

interface RepoSelectorProps {
  repos: RepoInfo[];
  activeRepo: string | null;
  onSelect: (repo: string) => void;
}

export function RepoSelector({
  repos,
  activeRepo,
  onSelect,
}: RepoSelectorProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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

  const displayName = activeRepo
    ? activeRepo.split("/").pop() || activeRepo
    : "Select repo";

  const fullName = activeRepo || "";

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-white/[0.04] transition-colors group"
      >
        {/* Repo icon */}
        <svg
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="currentColor"
          className="text-[#888] group-hover:text-[#aaa] transition-colors"
        >
          <path d="M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z" />
        </svg>
        <span className="text-[10px] font-medium text-[#ccc] max-w-[120px] truncate">
          {displayName}
        </span>
        <svg
          width="8"
          height="8"
          viewBox="0 0 8 8"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className={`text-[#666] transition-transform ${open ? "rotate-180" : ""}`}
        >
          <polyline points="2 3 4 5 6 3" />
        </svg>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full left-0 mt-1 z-50 w-[260px] bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg shadow-xl shadow-black/50 overflow-hidden"
          >
            <div className="px-3 py-2 border-b border-[#1a1a1a]">
              <span className="text-[9px] uppercase tracking-[0.1em] text-[#666] font-semibold">
                Repositories
              </span>
            </div>

            <div className="max-h-[200px] overflow-y-auto">
              {repos.length === 0 && (
                <div className="px-3 py-3 text-[10px] text-[#666]">
                  No repos configured
                </div>
              )}
              {repos.map((r) => (
                <button
                  key={r.repo}
                  onClick={() => {
                    onSelect(r.repo);
                    setOpen(false);
                  }}
                  className={`w-full flex items-center gap-2 px-3 py-3 sm:py-2 text-left hover:bg-white/[0.04] transition-colors ${
                    r.repo === activeRepo ? "bg-white/[0.02]" : ""
                  }`}
                >
                  {/* Active indicator */}
                  <div
                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      r.repo === activeRepo ? "bg-[#00ff88]" : "bg-transparent"
                    }`}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-[10px] font-medium text-[#ccc] truncate">
                      {r.repo}
                    </div>
                    <div className="text-[9px] text-[#666]">
                      {r.run_count} run{r.run_count !== 1 ? "s" : ""}
                    </div>
                  </div>
                  {r.repo === activeRepo && (
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      fill="none"
                      stroke="#00ff88"
                      strokeWidth="1.5"
                    >
                      <polyline points="2 5 4 7 8 3" />
                    </svg>
                  )}
                </button>
              ))}
            </div>

            {/* Show all runs option */}
            <div className="border-t border-[#1a1a1a]">
              <button
                onClick={() => {
                  onSelect("");
                  setOpen(false);
                }}
                className={`w-full flex items-center gap-2 px-3 py-3 sm:py-2 text-left hover:bg-white/[0.04] transition-colors ${
                  !activeRepo ? "bg-white/[0.02]" : ""
                }`}
              >
                <div
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    !activeRepo ? "bg-[#88ccff]" : "bg-transparent"
                  }`}
                />
                <span className="text-[10px] text-[#888]">
                  All repositories
                </span>
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
