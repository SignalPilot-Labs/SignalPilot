"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import Image from "next/image";
import { Button } from "@/components/ui/Button";
import { updateSettings } from "@/lib/settings-api";
import type { SettingsStatus } from "@/lib/types";
import { clsx } from "clsx";

interface OnboardingModalProps {
  open: boolean;
  onComplete: () => void;
  initialStatus: SettingsStatus;
}

const STEPS = [
  {
    key: "claude_token",
    label: "Claude OAuth Token",
    statusKey: "has_claude_token" as const,
    placeholder: "sk-ant-oat01-...",
    type: "password" as const,
    help: (
      <>
        <p className="text-[10px] text-[#888] leading-relaxed">
          This authenticates the Claude CLI inside Docker.
        </p>
        <div className="mt-2 p-2.5 bg-black/40 rounded border border-[#1a1a1a]">
          <p className="text-[9px] text-[#999] uppercase tracking-wider font-semibold mb-1.5">
            How to get it
          </p>
          <ol className="text-[10px] text-[#999] space-y-1 list-decimal list-inside">
            <li>
              Run{" "}
              <code className="text-[#00ff88] bg-[#00ff88]/[0.06] px-1 py-0.5 rounded text-[9px]">
                claude setup-token
              </code>{" "}
              in your terminal
            </li>
            <li>Follow the prompts to authenticate</li>
            <li>Copy the token that is output</li>
          </ol>
        </div>
      </>
    ),
  },
  {
    key: "git_token",
    label: "GitHub Personal Access Token",
    statusKey: "has_git_token" as const,
    placeholder: "ghp_...",
    type: "password" as const,
    help: (
      <>
        <p className="text-[10px] text-[#888] leading-relaxed">
          Used by the agent to push branches and create PRs. Never exposed to
          the LLM.
        </p>
        <div className="mt-2 p-2.5 bg-black/40 rounded border border-[#1a1a1a]">
          <p className="text-[9px] text-[#999] uppercase tracking-wider font-semibold mb-1.5">
            How to get it
          </p>
          <ol className="text-[10px] text-[#999] space-y-1 list-decimal list-inside">
            <li>
              Go to GitHub Settings &rarr; Developer settings &rarr; Personal
              access tokens &rarr; Fine-grained tokens
            </li>
            <li>Click &ldquo;Generate new token&rdquo;</li>
            <li>
              Select your repo and grant{" "}
              <code className="text-[#ffcc44] bg-[#ffcc44]/[0.06] px-1 py-0.5 rounded text-[9px]">
                Contents: Read and write
              </code>{" "}
              and{" "}
              <code className="text-[#ffcc44] bg-[#ffcc44]/[0.06] px-1 py-0.5 rounded text-[9px]">
                Pull requests: Read and write
              </code>
            </li>
            <li>Copy the generated token</li>
          </ol>
        </div>
      </>
    ),
  },
  {
    key: "github_repo",
    label: "GitHub Repository",
    statusKey: "has_github_repo" as const,
    placeholder: "your-org/SignalPilot",
    type: "text" as const,
    help: (
      <p className="text-[10px] text-[#888] leading-relaxed">
        The repository slug in{" "}
        <code className="text-[#88ccff] bg-[#88ccff]/[0.06] px-1 py-0.5 rounded text-[9px]">
          owner/repo
        </code>{" "}
        format. The agent is gated to only operate on this repository.
      </p>
    ),
  },
];

export function OnboardingModal({
  open,
  onComplete,
  initialStatus,
}: OnboardingModalProps) {
  const [step, setStep] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input on step change
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 150);
  }, [open, step]);

  // Lock body scroll
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = "";
      };
    }
  }, [open]);

  const currentStep = STEPS[step];
  const currentValue = values[currentStep.key] || "";
  const isLastStep = step === STEPS.length - 1;

  const handleNext = async () => {
    if (!currentValue.trim()) return;

    setError(null);
    setSaving(true);
    try {
      await updateSettings({ [currentStep.key]: currentValue.trim() });
      if (isLastStep) {
        onComplete();
      } else {
        setStep(step + 1);
        setShowPassword(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleSkip = () => {
    if (isLastStep) {
      onComplete();
    } else {
      setStep(step + 1);
      setShowPassword(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleNext();
    }
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="onboard-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[9990] bg-black/80"
          />

          <div className="fixed inset-0 z-[9991] flex items-center justify-center pointer-events-none">
            <motion.div
              key="onboard-content"
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ type: "spring", stiffness: 400, damping: 30 }}
              className="w-[480px] bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg shadow-2xl shadow-black/60 card-accent-top pointer-events-auto"
            >
              {/* Header */}
              <div className="px-5 py-4 border-b border-[#1a1a1a]">
                <div className="flex items-center gap-2.5">
                  <div className="flex items-center justify-center h-7 w-7 rounded bg-white/[0.04] border border-white/[0.08]">
                    <Image
                      src="/logo.svg"
                      alt="SignalPilot"
                      width={16}
                      height={16}
                    />
                  </div>
                  <div>
                    <h2 className="text-[12px] font-semibold text-[#e8e8e8]">
                      Welcome to Self-Improve
                    </h2>
                    <p className="text-[9px] text-[#999] mt-0.5">
                      Set up your credentials to get started
                    </p>
                  </div>
                </div>

                {/* Step indicators */}
                <div className="flex items-center gap-1.5 mt-3">
                  {STEPS.map((s, i) => (
                    <div key={s.key} className="flex items-center gap-1.5">
                      <div
                        className={clsx(
                          "h-1.5 rounded-full transition-all duration-300",
                          i === step
                            ? "w-8 bg-[#00ff88]"
                            : i < step || initialStatus[s.statusKey]
                              ? "w-4 bg-[#00ff88]/30"
                              : "w-4 bg-[#1a1a1a]",
                        )}
                      />
                    </div>
                  ))}
                </div>
              </div>

              {/* Body */}
              <div className="p-5">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={step}
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    transition={{ duration: 0.2 }}
                  >
                    <label className="text-[9px] uppercase tracking-[0.15em] text-[#999] font-semibold">
                      Step {step + 1} of {STEPS.length} &mdash;{" "}
                      {currentStep.label}
                    </label>

                    <div className="mt-3 relative">
                      <input
                        ref={inputRef}
                        type={
                          currentStep.type === "password" && !showPassword
                            ? "password"
                            : "text"
                        }
                        value={currentValue}
                        onChange={(e) =>
                          setValues({
                            ...values,
                            [currentStep.key]: e.target.value,
                          })
                        }
                        onKeyDown={handleKeyDown}
                        placeholder={currentStep.placeholder}
                        className="w-full bg-black/30 border border-[#1a1a1a] rounded px-3 py-2.5 text-[11px] text-[#ccc] font-mono placeholder-[#666] focus:outline-none focus:border-[#00ff88]/30 transition-all pr-10"
                        autoComplete="off"
                        spellCheck={false}
                      />
                      {currentStep.type === "password" && (
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[#999] hover:text-[#888] transition-colors"
                          tabIndex={-1}
                        >
                          {showPassword ? (
                            <svg
                              width="14"
                              height="14"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.5"
                            >
                              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                              <line x1="1" y1="1" x2="23" y2="23" />
                            </svg>
                          ) : (
                            <svg
                              width="14"
                              height="14"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.5"
                            >
                              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                              <circle cx="12" cy="12" r="3" />
                            </svg>
                          )}
                        </button>
                      )}
                    </div>

                    {initialStatus[currentStep.statusKey] && !currentValue && (
                      <p className="mt-2 text-[9px] text-[#00ff88]/60 flex items-center gap-1">
                        <svg
                          width="10"
                          height="10"
                          viewBox="0 0 10 10"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                        >
                          <polyline points="2 5 4 7 8 3" />
                        </svg>
                        Already configured &mdash; leave blank to keep current
                        value
                      </p>
                    )}

                    {error && (
                      <p className="mt-2 text-[9px] text-[#ff4444]">{error}</p>
                    )}

                    <div className="mt-4">{currentStep.help}</div>
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between px-5 py-3 border-t border-[#1a1a1a]">
                <div className="flex items-center gap-2">
                  {step > 0 && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setStep(step - 1);
                        setShowPassword(false);
                      }}
                    >
                      Back
                    </Button>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {(initialStatus[currentStep.statusKey] ||
                    !currentValue.trim()) && (
                    <Button variant="ghost" onClick={handleSkip}>
                      {isLastStep ? "Done" : "Skip"}
                    </Button>
                  )}
                  <Button
                    variant="success"
                    size="md"
                    onClick={handleNext}
                    disabled={saving || !currentValue.trim()}
                  >
                    {saving
                      ? "Saving..."
                      : isLastStep
                        ? "Save & Finish"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}
