"use client";

import { useTierBranding } from "@/lib/hooks/use-tier-branding";

interface TierWordmarkProps {
  variant?: "sidebar" | "header";
}

export function TierWordmark({ variant = "sidebar" }: TierWordmarkProps) {
  const b = useTierBranding();

  if (!b.enabled || b.tier === "free") return null;

  const { brand } = b;

  if (!brand.accentHex) return null;

  const textSize = variant === "sidebar" ? "text-[11px]" : "text-[12px]";

  return (
    <span className={`inline-flex items-center gap-1.5 tracking-[0.15em] uppercase ${brand.accentText} ${textSize}`}>
      <span
        className="inline-block w-[5px] h-[5px] flex-shrink-0"
        style={{ backgroundColor: brand.accentHex }}
        aria-hidden="true"
      />
      {brand.label}
    </span>
  );
}
