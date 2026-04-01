"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/Button";
import {
  RocketLaunchIcon,
  XMarkIcon,
  CurrencyDollarIcon,
  ChevronUpDownIcon,
  CheckIcon,
} from "@heroicons/react/16/solid";

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

  // Pin main/staging to the top
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

  // Close on click outside
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
      <label className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">
        Branch from
      </label>
      <button
        onClick={() => setOpen(!open)}
        className="mt-1.5 w-full flex items-center justify-between px-3 py-2 bg-black/30 border border-white/[0.06] rounded-lg text-[12px] text-left hover:border-white/[0.12] transition-colors"
      >
        <span className="font-mono text-sky-400">{selected}</span>
        <ChevronUpDownIcon className="h-3.5 w-3.5 text-zinc-500" />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[#161b22] border border-white/[0.08] rounded-lg shadow-xl shadow-black/40 overflow-hidden">
          <div className="p-2 border-b border-white/[0.06]">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search branches..."
              className="w-full bg-black/30 border border-white/[0.06] rounded px-2.5 py-1.5 text-[11px] text-zinc-300 placeholder-zinc-600 focus:outline-none focus:border-sky-500/40"
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
          <div className="max-h-48 overflow-y-auto scrollbar-thin">
            {sorted.length === 0 ? (
              <div className="px-3 py-2 text-[10px] text-zinc-600">No branches match</div>
            ) : (
              sorted.map((b) => (
                <button
                  key={b}
                  onClick={() => { onSelect(b); setOpen(false); setQuery(""); }}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-[11px] font-mono transition-colors ${
                    b === selected
                      ? "bg-sky-500/[0.08] text-sky-400"
                      : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-300"
                  }`}
                >
                  {b === selected ? (
                    <CheckIcon className="h-3 w-3 text-sky-400 shrink-0" />
                  ) : (
                    <span className="w-3" />
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
    if (e.key === "Escape") onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[520px] max-h-[80vh] overflow-y-auto bg-[#12151c] border border-white/[0.08] rounded-xl shadow-2xl shadow-black/40"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
              <div className="flex items-center gap-2.5">
                <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                  <RocketLaunchIcon className="h-3.5 w-3.5 text-emerald-400" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-zinc-200">
                    Start Improvement Run
                  </h2>
                  <p className="text-[10px] text-zinc-500 mt-0.5">
                    Creates a new branch, makes improvements, opens a PR
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-1 rounded hover:bg-white/5 text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                <XMarkIcon className="h-4 w-4" />
              </button>
            </div>

            <div className="p-5 space-y-5">
              {/* Base branch — searchable dropdown */}
              <BranchPicker
                branches={branches}
                selected={baseBranch}
                onSelect={setBaseBranch}
              />

              {/* Quick prompts */}
              <div>
                <label className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">
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
                      className={`text-left p-3 rounded-lg border transition-all ${
                        selectedQuick === i
                          ? "border-sky-500/40 bg-sky-500/[0.06]"
                          : "border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04]"
                      }`}
                    >
                      <div className="text-[11px] font-medium text-zinc-300">
                        {q.label}
                      </div>
                      <div className="text-[10px] text-zinc-600 mt-0.5">
                        {q.desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Divider */}
              <div className="flex items-center gap-3">
                <div className="flex-1 h-px bg-white/[0.06]" />
                <span className="text-[10px] text-zinc-600">or</span>
                <div className="flex-1 h-px bg-white/[0.06]" />
              </div>

              {/* Custom prompt */}
              <div>
                <label className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">
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
                  className="mt-2 w-full bg-black/30 border border-white/[0.06] rounded-lg px-3 py-2.5 text-[12px] text-zinc-300 placeholder-zinc-600 resize-y focus:outline-none focus:border-sky-500/40 focus:ring-1 focus:ring-sky-500/20 transition-all"
                />
              </div>

              {/* Duration lock */}
              <div>
                <label className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold flex items-center gap-1">
                  Session Duration
                </label>
                <p className="text-[10px] text-zinc-600 mt-0.5 mb-2">
                  Agent cannot call end_session until this time expires
                </p>
                <div className="flex gap-1.5 flex-wrap">
                  {DURATION_PRESETS.map((d) => (
                    <button
                      key={d.minutes}
                      onClick={() => setDuration(d.minutes)}
                      className={`text-[10px] px-2.5 py-1.5 rounded-md border transition-all ${
                        duration === d.minutes
                          ? "border-emerald-500/40 bg-emerald-500/[0.08] text-emerald-400"
                          : "border-white/[0.06] bg-white/[0.02] text-zinc-400 hover:bg-white/[0.04]"
                      }`}
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Budget */}
              <div>
                <label
                  className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold flex items-center gap-2 cursor-pointer select-none"
                  onClick={() => setBudgetEnabled(!budgetEnabled)}
                >
                  <span
                    className={`flex items-center justify-center h-3.5 w-3.5 rounded border transition-all ${
                      budgetEnabled
                        ? "bg-sky-500 border-sky-500"
                        : "border-zinc-600 bg-transparent"
                    }`}
                  >
                    {budgetEnabled && (
                      <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 12 12" fill="none">
                        <path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    )}
                  </span>
                  <CurrencyDollarIcon className="h-3 w-3" />
                  Max Budget
                  {!budgetEnabled && (
                    <span className="text-[9px] text-zinc-600 font-normal normal-case tracking-normal ml-1">
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
                      className="flex-1 accent-sky-500"
                    />
                    <span className="text-sm font-semibold text-zinc-300 tabular-nums w-16 text-right">
                      ${budget}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between px-5 py-4 border-t border-white/[0.06]">
              <span className="text-[10px] text-zinc-600">
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
                  icon={<RocketLaunchIcon className="h-3.5 w-3.5" />}
                >
                  {busy ? "Starting..." : "Start Run"}
                </Button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
