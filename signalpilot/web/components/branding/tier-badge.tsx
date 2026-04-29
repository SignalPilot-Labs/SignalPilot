"use client";

import { useTierBranding } from "@/lib/hooks/use-tier-branding";

interface TierBadgeProps {
  /**
   * @deprecated Size prop is ignored — there is one canonical size.
   * Accepted to avoid breaking existing call sites.
   */
  size?: "sm" | "md";
}

export function TierBadge({ size: _size }: TierBadgeProps) {
  const b = useTierBranding();

  if (!b.enabled || b.tier === "free") return null;

  const { brand } = b;

  if (!brand.accentHex) return null;

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block w-[5px] h-[5px] flex-shrink-0"
        style={{ backgroundColor: brand.accentHex }}
        aria-hidden="true"
      />
      <span className="text-[11px] leading-none tracking-[0.15em] uppercase text-[var(--color-text-muted)]">
        {brand.label}
      </span>
    </span>
  );
}
