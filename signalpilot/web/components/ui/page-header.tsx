"use client";

import { TierBadge } from "@/components/branding/tier-badge";
import { TierAccent } from "@/components/branding/tier-accent";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

/**
 * Consistent page header with terminal-style breadcrumb.
 */
export function PageHeader({
  title,
  subtitle,
  description,
  actions,
}: {
  title: string;
  subtitle: string;
  description: string;
  actions?: React.ReactNode;
}) {
  const b = useTierBranding();
  // Paid tier: TierAccent renders the tinted line; suppress neutral hairline.
  // Free tier (or non-cloud): TierAccent returns null; show neutral hairline.
  const isPaidTier = b.enabled && b.tier !== "free";

  return (
    <div className="mb-8">
      {/* Title row */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-light tracking-wide text-[var(--color-text)]">{title}</h1>
            <TierBadge />
            <span className="text-[12px] leading-none tracking-[0.15em] uppercase text-[var(--color-text-muted)]">{subtitle}</span>
          </div>
          <p className="text-sm text-[var(--color-text-muted)] tracking-wider">{description}</p>
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>

      {/* Bottom rule — exactly one line. Paid tier: tier-tinted accent.
          Free / non-cloud: neutral gradient hairline. */}
      {isPaidTier ? (
        <TierAccent />
      ) : (
        <div className="mt-4 h-px bg-gradient-to-r from-transparent via-[var(--color-border-hover)] to-transparent" />
      )}
    </div>
  );
}

/**
 * Terminal-style command bar shown at top of pages.
 * Gives the "developer console" feel.
 */
export function TerminalBar({
  path,
  status,
  children,
}: {
  path: string;
  status?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
      <div className="px-4 py-2 flex items-center gap-3 border-b border-[var(--color-border)]">
        {/* Terminal dots */}
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-30" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-20" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-10" />
        </div>
        {/* Path */}
        <code className="text-[12px] text-[var(--color-text-dim)] tracking-wider flex-1">
          <span className="text-[var(--color-success)]">$</span>
          <span className="text-[var(--color-text-dim)]"> signalpilot </span>
          <span className="text-[var(--color-text-muted)]">{path}</span>
        </code>
        {status}
      </div>
      {children && (
        <div className="px-4 py-2.5 flex items-center justify-between">
          {children}
          {/* Animated data flow indicator */}
          <div className="w-8 h-px ml-4 overflow-hidden opacity-30">
            <div className="h-full animate-data-flow" />
          </div>
        </div>
      )}
    </div>
  );
}
