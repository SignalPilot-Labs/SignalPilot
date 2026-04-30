"use client";

import { useTierBranding } from "@/lib/hooks/use-tier-branding";

export function TierAccent() {
  const b = useTierBranding();

  if (!b.enabled || b.tier === "free") return null;

  const { brand } = b;

  if (!brand.accentHex) return null;

  // Append hex '40' suffix = 25% opacity without Tailwind JIT dependency.
  const lineColor = brand.accentHex + "40";

  return (
    <div
      className="mt-4 h-px"
      style={{ backgroundColor: lineColor }}
    />
  );
}
