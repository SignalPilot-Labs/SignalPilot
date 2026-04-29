"use client";

import { TierBadge } from "@/components/branding/tier-badge";
import { TierAccent } from "@/components/branding/tier-accent";
import { TierSeal } from "@/components/branding/tier-seal";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

// Whole-token gradient class map — no concatenation, no arbitrary opacity.
const TIER_GRADIENT: Record<string, string> = {
  enterprise: "bg-gradient-to-r from-amber-500/10 via-transparent to-amber-500/10",
  team:       "bg-gradient-to-r from-violet-500/10 via-transparent to-violet-500/10",
  pro:        "bg-gradient-to-r from-indigo-500/10 via-transparent to-indigo-500/10",
};

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
  const showBackdrop = b.enabled && b.tier !== "free";

  const gradientClass = showBackdrop ? (TIER_GRADIENT[b.tier] ?? "") : "";
  const Icon = showBackdrop ? b.brand.icon : null;
  const accentText = showBackdrop ? b.brand.accentText : "";

  return (
    <div className="mb-8">
      {/* Relative container for backdrop layers */}
      <div className="relative">
        {/* Gradient band — behind everything */}
        {showBackdrop && gradientClass && (
          <div
            className={`absolute inset-x-0 -inset-y-2 ${gradientClass} pointer-events-none`}
            aria-hidden="true"
          />
        )}

        {/* Watermark icon — behind title row */}
        {showBackdrop && Icon && (
          <div
            className={`absolute right-2 top-1/2 -translate-y-1/2 opacity-10 ${accentText} pointer-events-none`}
            aria-hidden="true"
          >
            <Icon size={80} />
          </div>
        )}

        {/* Title row — above backdrop layers */}
        <div className="flex items-center justify-between relative z-10">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-xl font-light tracking-wide text-[var(--color-text)]">{title}</h1>
              <TierBadge size="sm" />
              <span className="text-[12px] text-[var(--color-text-muted)] tracking-[0.15em] uppercase px-1.5 py-0.5 border border-[var(--color-border)]">
                {subtitle}
              </span>
            </div>
            <p className="text-sm text-[var(--color-text-muted)] tracking-wider">{description}</p>
          </div>
          <div className="flex items-center gap-2">
            {actions}
            <TierSeal variant="header" />
          </div>
        </div>
      </div>

      {/* Neutral gradient accent line — always rendered */}
      <div className="mt-4 h-px bg-gradient-to-r from-transparent via-[var(--color-border-hover)] to-transparent" />
      {/* Tier-tinted accent — renders only for paid cloud tiers */}
      <TierAccent />
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
