"use client";

import { Component, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

function ErrorSVG() {
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" className="mb-6">
      {/* Outer frame */}
      <rect x="4" y="4" width="56" height="56" stroke="var(--color-error)" strokeWidth="1" opacity="0.3" />
      {/* Inner warning triangle */}
      <path
        d="M32 16L48 48H16L32 16Z"
        stroke="var(--color-error)"
        strokeWidth="1.5"
        fill="none"
        opacity="0.6"
      />
      {/* Exclamation */}
      <line x1="32" y1="26" x2="32" y2="38" stroke="var(--color-error)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="32" cy="43" r="1.5" fill="var(--color-error)" />
      {/* Corner marks */}
      <path d="M4 12V4H12" stroke="var(--color-error)" strokeWidth="1" opacity="0.5" />
      <path d="M52 4H60V12" stroke="var(--color-error)" strokeWidth="1" opacity="0.5" />
      <path d="M60 52V60H52" stroke="var(--color-error)" strokeWidth="1" opacity="0.5" />
      <path d="M12 60H4V52" stroke="var(--color-error)" strokeWidth="1" opacity="0.5" />
    </svg>
  );
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex flex-col items-center justify-center py-24 px-8 animate-fade-in">
          <ErrorSVG />
          <h2 className="text-xs tracking-wider mb-2 text-[var(--color-text)]">something went wrong</h2>
          <p className="text-[10px] text-[var(--color-text-dim)] mb-2 max-w-md text-center tracking-wider leading-relaxed">
            {this.state.error?.message || "an unexpected error occurred."}
          </p>
          <p className="text-[9px] text-[var(--color-text-dim)] mb-6 tracking-wider">
            try reloading the page to recover
          </p>
          <button
            onClick={() => {
              this.setState({ hasError: false, error: null });
              window.location.reload();
            }}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[10px] tracking-wider uppercase transition-all hover:opacity-90"
          >
            <RefreshCw className="w-3 h-3" />
            reload
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
