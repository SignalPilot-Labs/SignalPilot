"use client";

import { useTierBranding } from "@/lib/hooks/use-tier-branding";

interface TierWordmarkProps {
  variant?: "sidebar" | "header";
}

export function TierWordmark({ variant = "sidebar" }: TierWordmarkProps) {
  const b = useTierBranding();

  if (!b.enabled || b.tier === "free") return null;

  const { brand } = b;
  const Icon = brand.icon;

  const iconSize = variant === "sidebar" ? 10 : 12;

  return (
    <span
      className={`inline-flex items-center gap-1 tracking-[0.15em] uppercase ${brand.accentText} ${variant === "sidebar" ? "text-[11px]" : "text-[12px]"}`}
    >
      {Icon && <Icon size={iconSize} className="flex-shrink-0" />}
      {brand.label.toUpperCase()}
    </span>
  );
}
