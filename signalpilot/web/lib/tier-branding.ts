import { Sparkles, Gem, Crown, type LucideIcon } from "lucide-react";

export type BrandTier = "free" | "pro" | "team" | "enterprise";

export interface TierBrand {
  label: string;
  icon: LucideIcon | null;
  accentText: string;
  accentBorder: string;
  accentBg: string;
  gradientFrom: string;
  gradientVia: string;
  gradientTo: string;
}

export const TIER_BRANDS: Record<BrandTier, TierBrand> = {
  free: {
    label: "Free",
    icon: null,
    accentText: "",
    accentBorder: "",
    accentBg: "",
    gradientFrom: "",
    gradientVia: "",
    gradientTo: "",
  },
  pro: {
    label: "Pro",
    icon: Sparkles,
    accentText: "text-indigo-400",
    accentBorder: "border-indigo-500/40",
    accentBg: "bg-indigo-500/10",
    gradientFrom: "from-indigo-500/0",
    gradientVia: "via-indigo-400/50",
    gradientTo: "to-indigo-500/0",
  },
  team: {
    label: "Team",
    icon: Gem,
    accentText: "text-violet-300",
    accentBorder: "border-violet-400/50",
    accentBg: "bg-violet-500/10",
    gradientFrom: "from-fuchsia-500/0",
    gradientVia: "via-violet-400/50",
    gradientTo: "to-indigo-500/0",
  },
  enterprise: {
    label: "Enterprise",
    icon: Crown,
    accentText: "text-amber-300",
    accentBorder: "border-amber-400/50",
    accentBg: "bg-amber-500/10",
    gradientFrom: "from-amber-500/0",
    gradientVia: "via-amber-300/60",
    gradientTo: "to-amber-500/0",
  },
};
