/**
 * Shared wrapper for auth pages.
 * Chrome lifted verbatim from app/sign-in/[[...sign-in]]/page.tsx:
 * background grid SVG, SignalPilot logo header, outer layout.
 */

import type { ReactNode } from "react";

export interface AuthShellProps {
  title: string;
  subtitle: string;
  children: ReactNode;
}

export function AuthShell({ title, subtitle, children }: AuthShellProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen relative">
      {/* Background grid — same pattern as boot page */}
      <div
        className="absolute inset-0 pointer-events-none overflow-hidden"
        aria-hidden="true"
      >
        <svg width="100%" height="100%" className="opacity-[0.025]">
          <defs>
            <pattern
              id="auth-shell-grid"
              width="32"
              height="32"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M32 0V32M0 32H32"
                stroke="currentColor"
                strokeWidth="0.5"
                fill="none"
              />
            </pattern>
            <radialGradient id="auth-shell-fade" cx="50%" cy="50%" r="40%">
              <stop offset="0%" stopColor="white" stopOpacity="1" />
              <stop offset="100%" stopColor="white" stopOpacity="0" />
            </radialGradient>
            <mask id="auth-shell-mask">
              <rect width="100%" height="100%" fill="url(#auth-shell-fade)" />
            </mask>
          </defs>
          <rect
            width="100%"
            height="100%"
            fill="url(#auth-shell-grid)"
            mask="url(#auth-shell-mask)"
          />
        </svg>
      </div>

      <div className="relative z-10 flex flex-col items-center gap-8 w-full max-w-sm px-4">
        {/* SignalPilot wordmark */}
        <div className="flex flex-col items-center gap-3">
          <svg
            width="40"
            height="40"
            viewBox="0 0 40 40"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
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
            <line
              x1="20"
              y1="28"
              x2="30"
              y2="28"
              stroke="white"
              strokeWidth="2.5"
              strokeLinecap="square"
            />
            <circle cx="30" cy="12" r="4" fill="#00ff88" opacity="0.15">
              <animate
                attributeName="r"
                values="4;6;4"
                dur="3s"
                repeatCount="indefinite"
              />
              <animate
                attributeName="opacity"
                values="0.15;0;0.15"
                dur="3s"
                repeatCount="indefinite"
              />
            </circle>
            <circle cx="30" cy="12" r="2.5" fill="#00ff88" />
          </svg>
          <div className="text-center">
            <p className="text-[13px] font-bold tracking-[0.2em] uppercase text-[var(--color-text)]">
              SignalPilot
            </p>
            <p className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase mt-0.5">
              governed infra
            </p>
          </div>
        </div>

        {/* Terminal card */}
        <div className="w-full border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          {/* Card header bar */}
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
            <span className="w-2 h-2 bg-[var(--color-border-hover)]" />
            <span className="w-2 h-2 bg-[var(--color-border-hover)]" />
            <span className="w-2 h-2 bg-[var(--color-border-hover)]" />
            <span className="ml-2 text-[11px] text-[var(--color-text-dim)] tracking-wider font-mono">
              {title}
            </span>
          </div>
          <div className="p-6">
            <p className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase mb-5">
              {subtitle}
            </p>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
