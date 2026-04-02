import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex items-center justify-center min-h-screen mobile-negate-offset px-4">
      <div className="text-center max-w-md w-full">
        {/* Terminal-style 404 SVG */}
        <svg width="240" height="140" viewBox="0 0 240 140" fill="none" className="mx-auto mb-8 max-w-full h-auto">
          {/* Terminal window */}
          <rect x="0.5" y="0.5" width="239" height="139" stroke="var(--color-border)" fill="var(--color-bg-card)" />
          {/* Title bar */}
          <rect x="1" y="1" width="238" height="24" fill="var(--color-bg-elevated)" />
          <line x1="1" y1="25" x2="239" y2="25" stroke="var(--color-border)" />
          {/* Window dots */}
          <rect x="10" y="9" width="6" height="6" fill="var(--color-text-dim)" opacity="0.3" />
          <rect x="20" y="9" width="6" height="6" fill="var(--color-text-dim)" opacity="0.2" />
          <rect x="30" y="9" width="6" height="6" fill="var(--color-text-dim)" opacity="0.1" />

          {/* 404 text - large */}
          <text x="120" y="72" textAnchor="middle" fill="var(--color-text)" fontSize="28" fontFamily="monospace" fontWeight="300" letterSpacing="0.15em" opacity="0.8">
            404
          </text>

          {/* Prompt line */}
          <text x="40" y="100" fill="var(--color-success)" fontSize="10" fontFamily="monospace">$</text>
          <text x="52" y="100" fill="var(--color-text-dim)" fontSize="10" fontFamily="monospace">
            route not found
          </text>

          {/* Blinking cursor */}
          <rect x="155" y="91" width="6" height="11" fill="var(--color-text-dim)" opacity="0.5">
            <animate attributeName="opacity" values="0.5;0;0.5" dur="1.2s" repeatCount="indefinite" />
          </rect>

          {/* Error line */}
          <text x="40" y="118" fill="var(--color-error)" fontSize="9" fontFamily="monospace" opacity="0.6">
            ERR: the requested path does not exist
          </text>

          {/* Corner markers */}
          <path d="M1 6V1H6" stroke="var(--color-border-hover)" strokeWidth="1" />
          <path d="M234 1H239V6" stroke="var(--color-border-hover)" strokeWidth="1" />
          <path d="M239 134V139H234" stroke="var(--color-border-hover)" strokeWidth="1" />
          <path d="M6 139H1V134" stroke="var(--color-border-hover)" strokeWidth="1" />
        </svg>

        <h2 className="text-lg font-light text-[var(--color-text)] tracking-wide mb-2">
          path not found
        </h2>
        <p className="text-xs text-[var(--color-text-dim)] tracking-wider mb-8">
          the route you requested doesn&apos;t exist in this instance
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4">
          <Link
            href="/dashboard"
            className="flex items-center justify-center gap-2 px-6 py-3 sm:py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 w-full sm:w-auto active:opacity-80"
          >
            dashboard
          </Link>
          <Link
            href="/query"
            className="flex items-center justify-center gap-2 px-6 py-3 sm:py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider w-full sm:w-auto"
          >
            query explorer
          </Link>
        </div>

        <p className="mt-8 text-[9px] text-[var(--color-text-dim)] tracking-wider">
          <code className="text-[var(--color-text-dim)]">signalpilot v0.1.0</code>
        </p>
      </div>
    </div>
  );
}
