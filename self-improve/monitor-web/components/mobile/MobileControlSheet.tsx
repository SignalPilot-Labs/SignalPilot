"use client";

import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { RunStatus, RepoInfo } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { RepoSelector } from "@/components/ui/RepoSelector";

interface MobileControlSheetProps {
  open: boolean;
  onClose: () => void;
  // Run controls
  status: RunStatus | null;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onKill: () => void;
  onUnlock: () => void;
  onToggleInject: () => void;
  busy: boolean;
  // Repo
  repos: RepoInfo[];
  activeRepo: string | null;
  onRepoSelect: (repo: string) => void;
  // New run
  onNewRun: () => void;
  isConfigured: boolean;
}

export function MobileControlSheet({
  open,
  onClose,
  status,
  onPause,
  onResume,
  onStop,
  onKill,
  onUnlock,
  onToggleInject,
  busy,
  repos,
  activeRepo,
  onRepoSelect,
  onNewRun,
  isConfigured,
}: MobileControlSheetProps) {
  const isActive = ["running", "paused", "rate_limited"].includes(status || "");
  const canPause = status === "running";
  const canResume = status === "paused";
  const canInject = ["running", "paused"].includes(status || "");

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[60] bg-black/60"
            onClick={onClose}
          />

          {/* Sheet */}
          <motion.div
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 400 }}
            className="fixed bottom-0 left-0 right-0 z-[61] bg-[#0a0a0a] border-t border-[#1a1a1a] rounded-t-2xl safe-area-bottom"
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-3 pb-2">
              <div className="w-8 h-1 rounded-full bg-[#333]" />
            </div>

            <div className="px-4 pb-6 space-y-4">
              {/* Repo selector */}
              <div>
                <label className="text-[10px] uppercase tracking-[0.15em] text-[#666] font-semibold mb-2 block">
                  Repository
                </label>
                <RepoSelector
                  repos={repos}
                  activeRepo={activeRepo}
                  onSelect={(repo) => { onRepoSelect(repo); onClose(); }}
                />
              </div>

              {/* New Run */}
              <Button
                variant="success"
                size="lg"
                onClick={() => { onNewRun(); onClose(); }}
                disabled={!isConfigured}
                className="w-full justify-center"
                icon={
                  <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <polygon points="3 2 8 5 3 8" />
                  </svg>
                }
              >
                {isConfigured ? "New Bot" : "Setup Required"}
              </Button>

              {/* Run controls grid */}
              {status && (
                <>
                  <label className="text-[10px] uppercase tracking-[0.15em] text-[#666] font-semibold block">
                    Run Controls
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    <Button
                      variant="warning"
                      size="lg"
                      disabled={!canPause || busy}
                      onClick={() => { onPause(); onClose(); }}
                      className="justify-center"
                      icon={
                        <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <rect x="2" y="2" width="2" height="6" rx="0.5" />
                          <rect x="6" y="2" width="2" height="6" rx="0.5" />
                        </svg>
                      }
                    >
                      Pause
                    </Button>
                    <Button
                      variant="success"
                      size="lg"
                      disabled={!canResume || busy}
                      onClick={() => { onResume(); onClose(); }}
                      className="justify-center"
                      icon={
                        <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <polygon points="3 2 8 5 3 8" />
                        </svg>
                      }
                    >
                      Resume
                    </Button>
                    <Button
                      variant="primary"
                      size="lg"
                      disabled={!canInject || busy}
                      onClick={() => { onToggleInject(); onClose(); }}
                      className="justify-center"
                      icon={
                        <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                          <path d="M1 7c0-1.5 1-2 3-2s3 .5 3 2" />
                          <path d="M7.5 1.5l1.5 3-3 3" />
                        </svg>
                      }
                    >
                      Inject
                    </Button>
                    <Button
                      variant="danger"
                      size="lg"
                      disabled={!isActive || busy}
                      onClick={() => { onStop(); onClose(); }}
                      className="justify-center"
                      icon={
                        <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <rect x="2" y="2" width="6" height="6" rx="0.5" />
                        </svg>
                      }
                    >
                      Stop
                    </Button>
                    <Button
                      variant="danger"
                      size="lg"
                      disabled={!isActive || busy}
                      onClick={() => { onKill(); onClose(); }}
                      className="justify-center"
                      icon={
                        <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <circle cx="5" cy="5" r="4" />
                          <line x1="3" y1="3" x2="7" y2="7" />
                          <line x1="7" y1="3" x2="3" y2="7" />
                        </svg>
                      }
                    >
                      Kill
                    </Button>
                    <Button
                      variant="warning"
                      size="lg"
                      disabled={!isActive || busy}
                      onClick={() => { onUnlock(); onClose(); }}
                      className="justify-center"
                      icon={
                        <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <rect x="2" y="5" width="6" height="4" rx="0.5" />
                          <path d="M3.5 5V3.5a1.5 1.5 0 013 0" />
                        </svg>
                      }
                    >
                      Unlock
                    </Button>
                  </div>
                </>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
