"use client";

import { useTierBranding } from "@/lib/hooks/use-tier-branding";

/**
 * Tiny absolute-positioned corner overlay for team avatar squares.
 * Returns null for free and pro (Pro stays calm — no avatar overlay,
 * only sidebar/header marks). Only Team and Enterprise get this crest.
 *
 * Usage: wrap the target element in `relative inline-flex` and render
 * <TierCrest /> as a sibling.
 */
export function TierCrest() {
  const b = useTierBranding();

  if (!b.enabled) return null;
  if (b.tier === "free" || b.tier === "pro") return null;

  const { brand } = b;
  const Icon = brand.icon;

  if (!Icon) return null;

  return (
    <span
      className={`absolute -bottom-0.5 -right-0.5 flex items-center justify-center w-3 h-3 bg-[var(--color-bg)] rounded-none ${brand.accentText}`}
      aria-hidden="true"
    >
      <Icon size={9} className="flex-shrink-0" />
    </span>
  );
}
