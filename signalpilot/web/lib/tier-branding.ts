export type BrandTier = "free" | "pro" | "team" | "enterprise";

export interface TierBrand {
  label: string;
  accentText: string;
  /** CSS hex color used in SVGs and inline styles. null for Free (no accent). */
  accentHex: string | null;
}

export const TIER_BRANDS: Record<BrandTier, TierBrand> = {
  free: {
    label: "Free",
    accentText: "",
    accentHex: null,
  },
  pro: {
    label: "Pro",
    accentText: "text-[var(--color-text-muted)]",
    accentHex: "#d4d4d4",
  },
  team: {
    label: "Team",
    accentText: "text-blue-400",
    accentHex: "#60a5fa",
  },
  enterprise: {
    label: "Enterprise",
    accentText: "text-[var(--color-success)]",
    accentHex: "#00ff88",
  },
};
