"use client";

import { useTierBranding } from "@/lib/hooks/use-tier-branding";

export function TierAccent() {
  const b = useTierBranding();

  if (!b.enabled || b.tier === "free") return null;

  const { brand } = b;

  return (
    <div
      className={`mt-px h-px bg-gradient-to-r ${brand.gradientFrom} ${brand.gradientVia} ${brand.gradientTo}`}
    />
  );
}
