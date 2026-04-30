import React from "react";

/**
 * On-brand boot splash rendered inside <ClerkLoading> at app boot.
 * Static composition only — no Clerk hooks. Safe to import from app/layout.tsx
 * in the cloud branch. < 50 lines.
 */

export function ClerkBootSplash(): React.JSX.Element {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="initializing session"
      className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]"
    >
      <div className="flex flex-col items-center gap-4">
        {/* SignalPilot logo block lifted from auth-shell.tsx */}
        <svg
          width="40"
          height="40"
          viewBox="0 0 40 40"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <rect x="1" y="1" width="38" height="38" fill="white" />
          <rect x="3" y="3" width="34" height="34" fill="black" />
          <path
            d="M10 12L18 20L10 28"
            stroke="white"
            strokeWidth="2.5"
            strokeLinecap="square"
            strokeLinejoin="miter"
          />
          <line x1="20" y1="28" x2="30" y2="28" stroke="white" strokeWidth="2.5" strokeLinecap="square" />
          <circle cx="30" cy="12" r="2.5" fill="#00ff88" />
        </svg>

        <div className="text-center">
          <p className="text-[13px] font-bold tracking-[0.2em] uppercase text-[var(--color-text)] font-mono">
            SignalPilot
          </p>
          <p className="mt-3 text-[12px] text-[var(--color-text-dim)] tracking-wider font-mono">
            {">"} initializing session
            <span className="cursor-blink">_</span>
          </p>
        </div>
      </div>
    </div>
  );
}
