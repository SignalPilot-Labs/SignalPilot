"use client";

/**
 * Custom SVG empty state illustrations for each section.
 * Developer-first, terminal-aesthetic, monochrome.
 */

export function EmptyTerminal({ className = "" }: { className?: string }) {
  return (
    <svg width="64" height="48" viewBox="0 0 64 48" fill="none" className={className}>
      {/* Terminal window */}
      <rect x="4" y="4" width="56" height="40" rx="0" stroke="var(--color-border-hover)" strokeWidth="1" />
      {/* Title bar */}
      <line x1="4" y1="12" x2="60" y2="12" stroke="var(--color-border)" strokeWidth="1" />
      <circle cx="10" cy="8" r="1.5" fill="var(--color-text-dim)" />
      <circle cx="16" cy="8" r="1.5" fill="var(--color-text-dim)" />
      <circle cx="22" cy="8" r="1.5" fill="var(--color-text-dim)" />
      {/* Terminal prompt */}
      <path d="M10 20L14 24L10 28" stroke="var(--color-text-dim)" strokeWidth="1.5" strokeLinecap="square" />
      <line x1="18" y1="28" x2="30" y2="28" stroke="var(--color-text-dim)" strokeWidth="1.5" strokeLinecap="square" />
      {/* Cursor blink */}
      <rect x="32" y="26" width="2" height="4" fill="var(--color-text-dim)">
        <animate attributeName="opacity" values="0.7;0;0.7" dur="1.2s" repeatCount="indefinite" />
      </rect>
      {/* Ghost lines typing in */}
      <line x1="10" y1="35" x2="35" y2="35" stroke="var(--color-border)" strokeWidth="1" opacity="0.3">
        <animate attributeName="x2" values="10;35" dur="2s" begin="0.5s" fill="freeze" />
        <animate attributeName="opacity" values="0;0.3" dur="0.5s" begin="0.5s" fill="freeze" />
      </line>
      <line x1="10" y1="39" x2="25" y2="39" stroke="var(--color-border)" strokeWidth="1" opacity="0.2">
        <animate attributeName="x2" values="10;25" dur="1.5s" begin="1s" fill="freeze" />
        <animate attributeName="opacity" values="0;0.2" dur="0.5s" begin="1s" fill="freeze" />
      </line>
      {/* Scan line */}
      <rect x="4" y="12" width="56" height="1" fill="var(--color-text-dim)" opacity="0">
        <animate attributeName="y" values="12;44;12" dur="4s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0;0.04;0" dur="4s" repeatCount="indefinite" />
      </rect>
    </svg>
  );
}

export function EmptyDatabase({ className = "" }: { className?: string }) {
  return (
    <svg width="64" height="48" viewBox="0 0 64 48" fill="none" className={className}>
      {/* Database cylinder */}
      <ellipse cx="32" cy="12" rx="20" ry="6" stroke="var(--color-border-hover)" strokeWidth="1" />
      <line x1="12" y1="12" x2="12" y2="36" stroke="var(--color-border-hover)" strokeWidth="1" />
      <line x1="52" y1="12" x2="52" y2="36" stroke="var(--color-border-hover)" strokeWidth="1" />
      <ellipse cx="32" cy="36" rx="20" ry="6" stroke="var(--color-border-hover)" strokeWidth="1" />
      {/* Middle ellipse with pulse */}
      <path d="M12 24 Q32 30 52 24" stroke="var(--color-border)" strokeWidth="1" strokeDasharray="2 2">
        <animate attributeName="stroke-dashoffset" values="0;8" dur="3s" repeatCount="indefinite" />
      </path>
      {/* Plus icon with subtle pulse */}
      <g>
        <line x1="32" y1="20" x2="32" y2="28" stroke="var(--color-text-dim)" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="28" y1="24" x2="36" y2="24" stroke="var(--color-text-dim)" strokeWidth="1.5" strokeLinecap="round" />
        <animate attributeName="opacity" values="0.6;1;0.6" dur="3s" repeatCount="indefinite" />
      </g>
    </svg>
  );
}

export function EmptyQuery({ className = "" }: { className?: string }) {
  return (
    <svg width="64" height="48" viewBox="0 0 64 48" fill="none" className={className}>
      {/* Code editor frame */}
      <rect x="4" y="4" width="56" height="40" stroke="var(--color-border-hover)" strokeWidth="1" />
      {/* Line numbers gutter */}
      <line x1="16" y1="4" x2="16" y2="44" stroke="var(--color-border)" strokeWidth="1" />
      <text x="10" y="16" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" textAnchor="middle">1</text>
      <text x="10" y="24" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" textAnchor="middle">2</text>
      <text x="10" y="32" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" textAnchor="middle">3</text>
      <text x="10" y="40" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" textAnchor="middle">4</text>
      {/* SQL keyword lines */}
      <rect x="20" y="12" width="18" height="3" rx="0" fill="var(--color-text-dim)" opacity="0.4" />
      <rect x="40" y="12" width="12" height="3" rx="0" fill="var(--color-border-hover)" opacity="0.3" />
      <rect x="20" y="20" width="12" height="3" rx="0" fill="var(--color-text-dim)" opacity="0.4" />
      <rect x="34" y="20" width="16" height="3" rx="0" fill="var(--color-border-hover)" opacity="0.3" />
      <rect x="20" y="28" width="22" height="3" rx="0" fill="var(--color-text-dim)" opacity="0.3" />
      <rect x="20" y="36" width="8" height="3" rx="0" fill="var(--color-text-dim)" opacity="0.2" />
    </svg>
  );
}

export function EmptyChart({ className = "" }: { className?: string }) {
  return (
    <svg width="64" height="48" viewBox="0 0 64 48" fill="none" className={className}>
      {/* Axes */}
      <line x1="10" y1="6" x2="10" y2="40" stroke="var(--color-border-hover)" strokeWidth="1" />
      <line x1="10" y1="40" x2="58" y2="40" stroke="var(--color-border-hover)" strokeWidth="1" />
      {/* Grid lines */}
      <line x1="10" y1="16" x2="58" y2="16" stroke="var(--color-border)" strokeWidth="0.5" strokeDasharray="2 4" />
      <line x1="10" y1="28" x2="58" y2="28" stroke="var(--color-border)" strokeWidth="0.5" strokeDasharray="2 4" />
      {/* Signal line — draw in */}
      <polyline
        points="14,32 22,24 30,28 38,14 46,20 54,10"
        stroke="var(--color-text-dim)"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="80"
        strokeDashoffset="80"
      >
        <animate attributeName="stroke-dashoffset" from="80" to="0" dur="2s" fill="freeze" />
      </polyline>
      {/* Data points — fade in staggered */}
      <circle cx="14" cy="32" r="2" fill="var(--color-bg)" stroke="var(--color-text-dim)" strokeWidth="1" opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur="0.3s" begin="0.5s" fill="freeze" />
      </circle>
      <circle cx="38" cy="14" r="2" fill="var(--color-bg)" stroke="var(--color-text-dim)" strokeWidth="1" opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur="0.3s" begin="1.2s" fill="freeze" />
      </circle>
      <circle cx="54" cy="10" r="2" fill="var(--color-bg)" stroke="var(--color-text-dim)" strokeWidth="1" opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur="0.3s" begin="1.8s" fill="freeze" />
      </circle>
    </svg>
  );
}

export function EmptyShield({ className = "" }: { className?: string }) {
  return (
    <svg width="64" height="48" viewBox="0 0 64 48" fill="none" className={className}>
      {/* Shield shape */}
      <path
        d="M32 4L48 12V26C48 34 40 42 32 46C24 42 16 34 16 26V12L32 4Z"
        stroke="var(--color-border-hover)"
        strokeWidth="1"
        fill="none"
        strokeDasharray="100"
        strokeDashoffset="100"
      >
        <animate attributeName="stroke-dashoffset" from="100" to="0" dur="1.5s" fill="freeze" />
      </path>
      {/* Check mark — draw in after shield */}
      <path
        d="M24 24L30 30L40 18"
        stroke="var(--color-text-dim)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="30"
        strokeDashoffset="30"
      >
        <animate attributeName="stroke-dashoffset" from="30" to="0" dur="0.5s" begin="1.2s" fill="freeze" />
      </path>
    </svg>
  );
}

export function EmptyList({ className = "" }: { className?: string }) {
  return (
    <svg width="64" height="48" viewBox="0 0 64 48" fill="none" className={className}>
      {/* Log/list entries */}
      <rect x="8" y="6" width="48" height="8" rx="0" stroke="var(--color-border-hover)" strokeWidth="1" />
      <rect x="10" y="9" width="4" height="2" fill="var(--color-text-dim)" opacity="0.4" />
      <rect x="16" y="9" width="20" height="2" fill="var(--color-border-hover)" opacity="0.3" />

      <rect x="8" y="18" width="48" height="8" rx="0" stroke="var(--color-border)" strokeWidth="1" opacity="0.6" />
      <rect x="10" y="21" width="4" height="2" fill="var(--color-text-dim)" opacity="0.3" />
      <rect x="16" y="21" width="16" height="2" fill="var(--color-border-hover)" opacity="0.2" />

      <rect x="8" y="30" width="48" height="8" rx="0" stroke="var(--color-border)" strokeWidth="1" opacity="0.3" />
      <rect x="10" y="33" width="4" height="2" fill="var(--color-text-dim)" opacity="0.2" />
      <rect x="16" y="33" width="24" height="2" fill="var(--color-border-hover)" opacity="0.15" />

      {/* Fade out effect */}
      <rect x="8" y="42" width="48" height="4" rx="0" stroke="var(--color-border)" strokeWidth="1" opacity="0.15" />
    </svg>
  );
}

export function EmptySandbox({ className = "" }: { className?: string }) {
  return (
    <svg width="64" height="48" viewBox="0 0 64 48" fill="none" className={className}>
      {/* Sandbox box */}
      <rect x="8" y="8" width="48" height="32" rx="0" stroke="var(--color-border-hover)" strokeWidth="1" />
      {/* Inner sandbox boundary — rotating dash */}
      <rect x="14" y="14" width="36" height="20" rx="0" stroke="var(--color-border)" strokeWidth="1" strokeDasharray="3 3">
        <animate attributeName="stroke-dashoffset" values="0;12" dur="4s" repeatCount="indefinite" />
      </rect>
      {/* CPU icon inside */}
      <rect x="26" y="20" width="12" height="8" rx="0" stroke="var(--color-text-dim)" strokeWidth="1" />
      {/* CPU pins */}
      <line x1="29" y1="18" x2="29" y2="20" stroke="var(--color-text-dim)" strokeWidth="1" />
      <line x1="32" y1="18" x2="32" y2="20" stroke="var(--color-text-dim)" strokeWidth="1" />
      <line x1="35" y1="18" x2="35" y2="20" stroke="var(--color-text-dim)" strokeWidth="1" />
      <line x1="29" y1="28" x2="29" y2="30" stroke="var(--color-text-dim)" strokeWidth="1" />
      <line x1="32" y1="28" x2="32" y2="30" stroke="var(--color-text-dim)" strokeWidth="1" />
      <line x1="35" y1="28" x2="35" y2="30" stroke="var(--color-text-dim)" strokeWidth="1" />
      {/* Activity pulse inside CPU */}
      <rect x="29" y="22" width="6" height="4" fill="var(--color-text-dim)" opacity="0">
        <animate attributeName="opacity" values="0;0.15;0" dur="2s" repeatCount="indefinite" />
      </rect>
      {/* Label */}
      <text x="32" y="45" fill="var(--color-text-dim)" fontSize="5" fontFamily="monospace" textAnchor="middle" opacity="0.5">SANDBOX</text>
    </svg>
  );
}

/**
 * Reusable empty state wrapper component.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
      <div className="mb-5 opacity-40 relative" style={{ animation: "empty-float 6s ease-in-out infinite" }}>
        <Icon className="" />
        {/* Subtle radial glow behind icon */}
        <div
          className="absolute inset-0 -m-4 pointer-events-none"
          style={{
            background: "radial-gradient(circle at center, rgba(255,255,255,0.03) 0%, transparent 70%)",
          }}
        />
      </div>
      <p className="text-xs text-[var(--color-text-muted)] mb-1.5 tracking-wider">{title}</p>
      <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider max-w-xs leading-relaxed">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
