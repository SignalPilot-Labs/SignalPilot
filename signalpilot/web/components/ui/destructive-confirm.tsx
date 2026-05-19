"use client";

import React, { useState, useEffect, useRef } from "react";

export function DestructiveConfirmDialog({
  open,
  projectName,
  onConfirm,
  onCancel,
  confirming = false,
}: {
  open: boolean;
  projectName: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirming?: boolean;
}) {
  const [step, setStep] = useState(0);
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setStep(0);
      setTyped("");
    }
  }, [open]);

  useEffect(() => {
    if (step === 1) inputRef.current?.focus();
  }, [step]);

  if (!open) return null;

  const confirmPhrase = `delete ${projectName}`;
  const typedMatches = typed.toLowerCase() === confirmPhrase.toLowerCase();

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 !ml-0"
      onClick={onCancel}
    >
      <div
        className="w-[440px] bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-2xl animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 1L13 13H1L7 1Z" stroke="var(--color-error)" strokeWidth="1" fill="none" />
            <line x1="7" y1="5" x2="7" y2="9" stroke="var(--color-error)" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="7" cy="11" r="0.75" fill="var(--color-error)" />
          </svg>
          <span className="text-[12px] text-[var(--color-error)] uppercase tracking-[0.15em] font-medium">
            destructive action
          </span>
        </div>

        {/* Step 0: Initial warning */}
        {step === 0 && (
          <div className="px-5 py-5">
            <p className="text-sm text-[var(--color-text)] mb-2 font-medium">
              Delete project &ldquo;{projectName}&rdquo;?
            </p>
            <p className="text-xs text-[var(--color-text-dim)] leading-relaxed mb-1">
              This will permanently:
            </p>
            <ul className="text-xs text-[var(--color-text-dim)] leading-relaxed mb-4 space-y-1 ml-4">
              <li className="list-disc">Archive the project metadata</li>
              <li className="list-disc">Delete all files from S3 storage</li>
              <li className="list-disc">This action cannot be undone</li>
            </ul>
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--color-border)]">
              <button
                onClick={onCancel}
                className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase"
              >
                cancel
              </button>
              <button
                onClick={() => setStep(1)}
                className="px-4 py-2 text-[12px] text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
              >
                I understand, continue
              </button>
            </div>
          </div>
        )}

        {/* Step 1: Type to confirm */}
        {step === 1 && (
          <div className="px-5 py-5">
            <p className="text-xs text-[var(--color-text-dim)] mb-3 leading-relaxed">
              Type <code className="px-1.5 py-0.5 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[var(--color-error)] font-mono text-[11px]">{confirmPhrase}</code> to confirm:
            </p>
            <input
              ref={inputRef}
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && typedMatches && !confirming) onConfirm(); }}
              placeholder={confirmPhrase}
              className="w-full px-3 py-2.5 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs font-mono focus:outline-none focus:border-[var(--color-error)] tracking-wide mb-4"
              autoComplete="off"
              spellCheck={false}
            />
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--color-border)]">
              <button
                onClick={onCancel}
                className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase"
              >
                cancel
              </button>
              <button
                onClick={onConfirm}
                disabled={!typedMatches || confirming}
                className="px-4 py-2 text-[12px] font-medium tracking-wider uppercase transition-all bg-[var(--color-error)] text-white hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {confirming ? "deleting..." : "permanently delete"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
