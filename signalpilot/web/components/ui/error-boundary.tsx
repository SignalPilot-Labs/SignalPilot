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
    <svg width="80" height="80" viewBox="0 0 80 80" fill="none" className="mb-6">
      {/* Outer frame with animated stroke */}
      <rect x="4" y="4" width="72" height="72" stroke="var(--color-error)" strokeWidth="1" opacity="0.2" />
      {/* Scan line effect */}
      <rect x="4" y="4" width="72" height="2" fill="var(--color-error)" opacity="0.1">
        <animate attributeName="y" values="4;72;4" dur="3s" repeatCount="indefinite" />
      </rect>
      {/* Inner warning triangle */}
      <path
        d="M40 20L56 56H24L40 20Z"
        stroke="var(--color-error)"
        strokeWidth="1.5"
        fill="none"
        opacity="0.5"
      />
      {/* Exclamation mark */}
      <line x1="40" y1="30" x2="40" y2="44" stroke="var(--color-error)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="40" cy="50" r="1.5" fill="var(--color-error)" />
      {/* Corner marks */}
      <path d="M4 14V4H14" stroke="var(--color-error)" strokeWidth="1" opacity="0.4" />
      <path d="M66 4H76V14" stroke="var(--color-error)" strokeWidth="1" opacity="0.4" />
      <path d="M76 66V76H66" stroke="var(--color-error)" strokeWidth="1" opacity="0.4" />
      <path d="M14 76H4V66" stroke="var(--color-error)" strokeWidth="1" opacity="0.4" />
      {/* Error code */}
      <text x="40" y="72" textAnchor="middle" fill="var(--color-error)" fontSize="8" fontFamily="monospace" opacity="0.4">ERR</text>
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
          <div className="flex items-center gap-3">
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[10px] tracking-wider uppercase transition-all hover:opacity-90"
            >
              <RefreshCw className="w-3 h-3" />
              retry
            </button>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              className="flex items-center gap-2 px-4 py-2 border border-[var(--color-border)] text-[var(--color-text-dim)] text-[10px] tracking-wider uppercase transition-all hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
            >
              reload page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
