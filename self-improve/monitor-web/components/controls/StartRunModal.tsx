"use client";

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import Image from "next/image";
import { Button } from "@/components/ui/Button";
import { clsx } from "clsx";

function BranchPicker({
  branches,
  selected,
  onSelect,
}: {
  branches: string[];
  selected: string;
  onSelect: (b: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const filtered = query
    ? branches.filter((b) => b.toLowerCase().includes(query.toLowerCase()))
    : branches;

  const sorted = [...filtered].sort((a, b) => {
    const pinned = ["main", "staging"];
    const aPin = pinned.indexOf(a);
    const bPin = pinned.indexOf(b);
    if (aPin !== -1 && bPin !== -1) return aPin - bPin;
    if (aPin !== -1) return -1;
    if (bPin !== -1) return 1;
    return a.localeCompare(b);
  });

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <label className="text-[10px] uppercase tracking-[0.15em] text-[#999] font-semibold">
        Branch from
      </label>
      <button
        onClick={() => setOpen(!open)}
        className="mt-1.5 w-full flex items-center justify-between px-3 py-2 bg-black/30 border border-[#1a1a1a] rounded text-[11px] text-left hover:border-[#2a2a2a] transition-colors"
      >
        <span className="font-mono text-[#e8e8e8]">{selected}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#999" strokeWidth="1.5" strokeLinecap="round">
          <polyline points="2 4 5 6 8 4" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[#0d0d0d] border border-[#1a1a1a] rounded shadow-xl shadow-black/40 overflow-hidden">
          <div className="p-2 border-b border-[#1a1a1a]">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search branches..."
              className="w-full bg-black/30 border border-[#1a1a1a] rounded px-2.5 py-1.5 text-[10px] text-[#ccc] placeholder-[#666] focus:outline-none focus:border-[#00ff88]/30"
              onKeyDown={(e) => {
                if (e.key === "Escape") { setOpen(false); setQuery(""); }
                if (e.key === "Enter" && sorted.length > 0) {
                  onSelect(sorted[0]);
                  setOpen(false);
                  setQuery("");
                }
              }}
            />
          </div>
          <div className="max-h-48 overflow-y-auto">
            {sorted.length === 0 ? (
              <div className="px-3 py-2 text-[9px] text-[#888]">No branches match</div>
            ) : (
              sorted.map((b) => (
                <button
                  key={b}
                  onClick={() => { onSelect(b); setOpen(false); setQuery(""); }}
                  className={clsx(
                    "w-full flex items-center gap-2 px-3 py-1.5 text-left text-[10px] font-mono transition-colors",
                    b === selected
                      ? "bg-[#00ff88]/[0.06] text-[#00ff88]"
                      : "text-[#888] hover:bg-white/[0.03] hover:text-[#ccc]"
                  )}
                >
                  {b === selected ? (
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#00ff88" strokeWidth="1.5" className="shrink-0">
                      <polyline points="2 5 4 7 8 3" />
                    </svg>
                  ) : (
                    <span className="w-[10px]" />
                  )}
                  {b}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface StartRunModalProps {
  open: boolean;
  onClose: () => void;
  onStart: (prompt: string | undefined, budget: number, durationMinutes: number, baseBranch: string) => void;
  busy: boolean;
  branches: string[];
  mode?: "single" | "parallel";
}

const DURATION_PRESETS = [
  { label: "No lock", minutes: 0, desc: "Agent can end anytime" },
  { label: "30 min", minutes: 30, desc: "Quick pass" },
  { label: "1 hour", minutes: 60, desc: "Focused session" },
  { label: "2 hours", minutes: 120, desc: "Deep dive" },
  { label: "4 hours", minutes: 240, desc: "Extended run" },
  { label: "8 hours", minutes: 480, desc: "Overnight" },
];

const QUICK_PROMPTS = [
  {
    label: "General improvement",
    prompt: undefined as string | undefined,
    desc: "Default: security, bugs, tests, quality",
  },
  {
    label: "Security audit fixes",
    prompt:
      "Focus on fixing the CRITICAL and HIGH security findings from SECURITY_AUDIT.md. Start there and work through each one.",
    desc: "Address audit findings",
  },
  {
    label: "Test coverage",
    prompt:
      "Focus exclusively on adding test coverage. Find untested critical paths and write thorough tests for them.",
    desc: "Add missing tests",
  },
  {
    label: "Gateway hardening",
    prompt:
      "Focus on hardening the gateway module: add authentication, fix CORS, add rate limiting, improve error handling.",
    desc: "Auth, CORS, rate limits",
  },
];

export function StartRunModal({
  open,
  onClose,
  onStart,
  busy,
  branches,
  mode = "single",
}: StartRunModalProps) {
  const [customPrompt, setCustomPrompt] = useState("");
  const [budgetEnabled, setBudgetEnabled] = useState(false);
  const [budget, setBudget] = useState(50);
  const [duration, setDuration] = useState(0);
  const [baseBranch, setBaseBranch] = useState("main");
  const [selectedQuick, setSelectedQuick] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) setTimeout(() => textareaRef.current?.focus(), 150);
  }, [open]);

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  const handleStart = () => {
    const prompt =
      selectedQuick !== null
        ? QUICK_PROMPTS[selectedQuick].prompt
        : customPrompt.trim() || undefined;
    onStart(prompt, budgetEnabled ? budget : 0, duration, baseBranch);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleStart();
    }
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="modal-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[9990] bg-black/70 frosted-glass"
            onClick={onClose}
          />

          {/* Centering wrapper — uses flexbox, no transforms */}
          <div
            className="fixed inset-0 z-[9991] flex items-center justify-center pointer-events-none"
          >
            <motion.div
              key="modal-content"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ type: "spring", stiffness: 400, damping: 30 }}
              className="w-[520px] max-h-[80vh] overflow-y-auto bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg shadow-2xl shadow-black/60 card-accent-top pointer-events-auto"
            >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-[#1a1a1a]">
                <div className="flex items-center gap-2.5">
                  <div className="flex items-center justify-center h-7 w-7 rounded bg-white/[0.04] border border-white/[0.08]">
                    <Image src="/logo.svg" alt="SignalPilot" width={16} height={16} />
                  </div>
                  <div>
                    <h2 className="text-[12px] font-semibold text-[#e8e8e8]">
                      {mode === "parallel" ? "Start Parallel Run" : "Start Improvement Run"}
                    </h2>
                    <p className="text-[9px] text-[#999] mt-0.5">
                      {mode === "parallel" ? "Spawns an isolated container with its own sandbox" : "Creates a branch, makes improvements, opens a PR"}
                    </p>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="p-1 rounded hover:bg-white/[0.04] text-[#999] hover:text-[#aaa] transition-colors"
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <line x1="3" y1="3" x2="9" y2="9" /><line x1="9" y1="3" x2="3" y2="9" />
                  </svg>
                </button>
              </div>

              <div className="p-5 space-y-5">
                <BranchPicker
                  branches={branches}
                  selected={baseBranch}
                  onSelect={setBaseBranch}
                />

                {/* Quick prompts */}
                <div>
                  <label className="text-[10px] uppercase tracking-[0.15em] text-[#999] font-semibold">
                    Quick Start
                  </label>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    {QUICK_PROMPTS.map((q, i) => (
                      <button
                        key={i}
                        onClick={() => {
                          setSelectedQuick(selectedQuick === i ? null : i);
                          setCustomPrompt("");
                        }}
                        className={clsx(
                          "text-left p-3 rounded border transition-all",
                          selectedQuick === i
                            ? "border-[#00ff88]/30 bg-[#00ff88]/[0.04]"
                            : "border-[#1a1a1a] bg-white/[0.01] hover:bg-white/[0.03]"
                        )}
                      >
                        <div className="text-[10px] font-medium text-[#ccc]">
                          {q.label}
                        </div>
                        <div className="text-[9px] text-[#999] mt-0.5">
                          {q.desc}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Divider */}
                <div className="separator-subtle" />

                {/* Custom prompt */}
                <div>
                  <label className="text-[10px] uppercase tracking-[0.15em] text-[#999] font-semibold">
                    Custom Prompt
                  </label>
                  <textarea
                    ref={textareaRef}
                    value={customPrompt}
                    onChange={(e) => {
                      setCustomPrompt(e.target.value);
                      setSelectedQuick(null);
                    }}
                    onKeyDown={handleKeyDown}
                    placeholder="Describe what the agent should focus on..."
                    rows={3}
                    className="mt-2 w-full bg-black/30 border border-[#1a1a1a] rounded px-3 py-2.5 text-[11px] text-[#ccc] placeholder-[#666] resize-y focus:outline-none focus:border-[#00ff88]/30 transition-all"
                  />
                </div>

                {/* Duration lock */}
                <div>
                  <label className="text-[10px] uppercase tracking-[0.15em] text-[#999] font-semibold">
                    Session Duration
                  </label>
                  <p className="text-[10px] text-[#888] mt-0.5 mb-2">
                    Agent cannot call end_session until this time expires
                  </p>
                  <div className="flex gap-1.5 flex-wrap">
                    {DURATION_PRESETS.map((d) => (
                      <button
                        key={d.minutes}
                        onClick={() => setDuration(d.minutes)}
                        className={clsx(
                          "text-[9px] px-2 py-1.5 rounded border transition-all",
                          duration === d.minutes
                            ? "border-[#00ff88]/30 bg-[#00ff88]/[0.06] text-[#00ff88]"
                            : "border-[#1a1a1a] bg-white/[0.01] text-[#777] hover:bg-white/[0.03]"
                        )}
                      >
                        {d.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Budget */}
                <div>
                  <label
                    className="text-[10px] uppercase tracking-[0.15em] text-[#999] font-semibold flex items-center gap-2 cursor-pointer select-none"
                    onClick={() => setBudgetEnabled(!budgetEnabled)}
                  >
                    <span
                      className={clsx(
                        "flex items-center justify-center h-3 w-3 rounded border transition-all",
                        budgetEnabled
                          ? "bg-[#00ff88] border-[#00ff88]"
                          : "border-[#666] bg-transparent"
                      )}
                    >
                      {budgetEnabled && (
                        <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="white" strokeWidth="1.5">
                          <polyline points="1.5 4 3 5.5 6.5 2" />
                        </svg>
                      )}
                    </span>
                    Max Budget
                    {!budgetEnabled && (
                      <span className="text-[10px] text-[#888] font-normal normal-case tracking-normal ml-1">
                        (unlimited)
                      </span>
                    )}
                  </label>
                  {budgetEnabled && (
                    <div className="flex items-center gap-3 mt-2">
                      <input
                        type="range"
                        min={5}
                        max={200}
                        step={5}
                        value={budget}
                        onChange={(e) => setBudget(Number(e.target.value))}
                        className="flex-1 accent-[#00ff88]"
                      />
                      <span className="text-[12px] font-semibold text-[#e8e8e8] tabular-nums w-16 text-right">
                        ${budget}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between px-5 py-3 border-t border-[#1a1a1a]">
                <span className="text-[9px] text-[#888]">
                  Ctrl+Enter to start
                </span>
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={onClose}>
                    Cancel
                  </Button>
                  <Button
                    variant="success"
                    size="md"
                    onClick={handleStart}
                    disabled={busy}
                    icon={
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <polygon points="3 2 8 5 3 8" />
                      </svg>
                    }
                  >
                    {busy ? "Starting..." : mode === "parallel" ? "Start Parallel Run" : "Start Run"}
                  </Button>
                </div>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}
