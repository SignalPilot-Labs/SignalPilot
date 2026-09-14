/** Billable tiers that carry a visual brand. Free and local (unlimited) have none. */
export type BrandTier = "team" | "scale" | "enterprise";

export interface TierBrand {
  label: string;
  accentText: string;
  /** CSS hex color used in SVGs and inline styles. */
  accentHex: string;
}

export const TIER_BRANDS: Record<BrandTier, TierBrand> = {
  team: {
    label: "Team",
    accentText: "text-blue-400",
    accentHex: "#60a5fa",
  },
  scale: {
    label: "Scale",
    accentText: "text-violet-400",
    accentHex: "#a78bfa",
  },
  enterprise: {
    label: "Enterprise",
    accentText: "text-[var(--color-success)]",
    accentHex: "#00ff88",
  },
};

export function isBrandTier(value: string): value is BrandTier {
  return value in TIER_BRANDS;
}
