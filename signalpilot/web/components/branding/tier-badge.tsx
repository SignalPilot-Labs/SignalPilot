"use client";

import { useTierBranding } from "@/lib/hooks/use-tier-branding";

interface TierBadgeProps {
  size?: "sm" | "md";
}

export function TierBadge({ size = "sm" }: TierBadgeProps) {
  const b = useTierBranding();

  if (!b.enabled || b.tier === "free") return null;

  const { brand } = b;
  const Icon = brand.icon;

  const textSize = size === "sm" ? "text-[11px]" : "text-[12px]";
  const iconSize = size === "sm" ? 10 : 12;
  const padding = size === "sm" ? "px-1.5 py-0.5" : "px-2 py-1";

  return (
    <span
      className={`inline-flex items-center gap-1 border ${padding} ${textSize} tracking-[0.15em] uppercase ${brand.accentText} ${brand.accentBorder} ${brand.accentBg}`}
    >
      {Icon && <Icon size={iconSize} className="flex-shrink-0" />}
      {brand.label}
    </span>
  );
}
